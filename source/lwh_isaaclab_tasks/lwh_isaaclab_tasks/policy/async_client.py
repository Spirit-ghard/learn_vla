"""IsaacLab adapter for LeRobot's official asynchronous inference protocol."""

from __future__ import annotations

import io
import json
import pickle
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any

import grpc
import numpy as np
import torch

from .transport import services_pb2, services_pb2_grpc


chunk_size = 2 * 1024 * 1024
max_message_size = 4 * 1024 * 1024

aggregate_functions: dict[str, Callable[[torch.Tensor, torch.Tensor], torch.Tensor]] = {
    "weighted_average": lambda old, new: 0.3 * old + 0.7 * new,
    "latest_only": lambda old, new: new,
    "average": lambda old, new: 0.5 * old + 0.5 * new,
    "conservative": lambda old, new: 0.7 * old + 0.3 * new,
}


@dataclass
class TimedAction:
    """LeRobot TimedAction 在 Isaac Python 进程中的轻量表示。"""

    timestamp: float
    timestep: int
    action: torch.Tensor


def grpc_channel_options(initial_backoff: str = "0.1s") -> list[tuple[str, Any]]:
    """与 LeRobot 官方 transport 使用相同的 gRPC 重试配置。"""
    service_config = {
        "methodConfig": [
            {
                "name": [{}],
                "retryPolicy": {
                    "maxAttempts": 5,
                    "initialBackoff": initial_backoff,
                    "maxBackoff": "2s",
                    "backoffMultiplier": 2,
                    "retryableStatusCodes": ["UNAVAILABLE", "DEADLINE_EXCEEDED"],
                },
            }
        ]
    }
    return [
        ("grpc.max_receive_message_length", max_message_size),
        ("grpc.max_send_message_length", max_message_size),
        ("grpc.enable_retries", 1),
        ("grpc.service_config", json.dumps(service_config)),
    ]


def send_bytes_in_chunks(payload: bytes) -> Iterator[services_pb2.Observation]:
    """按 LeRobot 官方 2 MiB 分块规则发送双相机观测。"""
    buffer = io.BytesIO(payload)
    total = len(payload)
    sent = 0
    while sent < total:
        if sent + chunk_size >= total:
            transfer_state = services_pb2.TRANSFER_END
        elif sent == 0:
            transfer_state = services_pb2.TRANSFER_BEGIN
        else:
            transfer_state = services_pb2.TRANSFER_MIDDLE
        data = buffer.read(min(chunk_size, total - sent))
        sent += len(data)
        yield services_pb2.Observation(transfer_state=transfer_state, data=data)


class IsaacLabAsyncPolicyClient:
    """复用 LeRobot RobotClient 的握手、action queue 和 chunk 聚合语义。"""

    def __init__(
        self,
        *,
        server_address: str,
        policy_type: str,
        policy_path: str,
        policy_device: str,
        actions_per_chunk: int,
        chunk_size_threshold: float,
        aggregate_fn_name: str,
        timeout_s: float,
        joint_names: list[str],
        image_shape: tuple[int, int, int],
    ) -> None:
        if not 0.0 <= chunk_size_threshold <= 1.0:
            raise ValueError("chunk_size_threshold must be between 0 and 1.")
        if actions_per_chunk < 1:
            raise ValueError("actions_per_chunk must be positive.")
        if aggregate_fn_name not in aggregate_functions:
            raise ValueError(
                f"Unknown aggregate function {aggregate_fn_name!r}; "
                f"choose from {sorted(aggregate_functions)}."
            )

        self.server_address = server_address
        self.timeout_s = timeout_s
        self.actions_per_chunk = actions_per_chunk
        self.chunk_size_threshold = chunk_size_threshold
        self.aggregate_fn = aggregate_functions[aggregate_fn_name]
        self.action_dim = len(joint_names)
        self.action_queue: Queue[TimedAction] = Queue()
        self.action_queue_lock = threading.Lock()
        self.latest_action_lock = threading.Lock()
        self.latest_action = -1
        self.action_chunk_size = -1
        self.must_go = threading.Event()
        self.must_go.set()
        self.shutdown_event = threading.Event()
        self.receiver_thread: threading.Thread | None = None
        self.sender_thread: threading.Thread | None = None
        self.observation_queue: Queue[dict[str, Any]] = Queue(maxsize=1)
        self.sender_busy = threading.Event()
        self.observation_pending = threading.Event()
        self.chunk_request_pending = threading.Event()
        self.chunk_request_started_at = 0.0
        self.received_chunks = 0
        self.queued_observations = 0
        self.sent_observations = 0
        self.dropped_observations = 0
        self.last_error: str | None = None
        self.metrics_lock = threading.Lock()
        self.latest_upload_ms = 0.0
        self.total_upload_ms = 0.0
        self.minimum_upload_ms = float("inf")
        self.maximum_upload_ms = 0.0
        self.latest_chunk_latency_ms = 0.0
        self.total_chunk_latency_ms = 0.0
        self.minimum_chunk_latency_ms = float("inf")
        self.maximum_chunk_latency_ms = 0.0

        lerobot_features = {
            "observation.state": {
                "dtype": "float32",
                "shape": (self.action_dim,),
                "names": [f"{name}.pos" for name in joint_names],
            },
            "observation.images.front": {
                "dtype": "image",
                "shape": image_shape,
                "names": ["height", "width", "channels"],
            },
            "observation.images.wrist": {
                "dtype": "image",
                "shape": image_shape,
                "names": ["height", "width", "channels"],
            },
        }
        self.policy_setup = {
            "policy_type": policy_type,
            "pretrained_name_or_path": policy_path,
            "lerobot_features": lerobot_features,
            "actions_per_chunk": actions_per_chunk,
            "device": policy_device,
            "rename_map": {},
        }

        channel = grpc.insecure_channel(
            server_address,
            options=grpc_channel_options(initial_backoff="0.0333s"),
        )
        self.channel = channel
        self.stub = services_pb2_grpc.AsyncInferenceStub(channel)

    @property
    def running(self) -> bool:
        return not self.shutdown_event.is_set()

    def start(self) -> None:
        """执行官方 Ready/SendPolicyInstructions 握手并启动 action 接收线程。"""
        self.stub.Ready(services_pb2.Empty(), timeout=self.timeout_s)
        request = services_pb2.PolicySetup(
            data=pickle.dumps(self.policy_setup, protocol=pickle.HIGHEST_PROTOCOL)
        )
        self.stub.SendPolicyInstructions(request, timeout=max(self.timeout_s, 120.0))
        self.shutdown_event.clear()
        self.receiver_thread = threading.Thread(
            target=self.receive_actions,
            name="lerobot-action-receiver",
            daemon=True,
        )
        self.sender_thread = threading.Thread(
            target=self.send_observations,
            name="lerobot-observation-sender",
            daemon=True,
        )
        self.receiver_thread.start()
        self.sender_thread.start()

    def stop(self) -> None:
        self.shutdown_event.set()
        self.channel.close()
        if self.sender_thread is not None:
            self.sender_thread.join(timeout=2.0)
        if self.receiver_thread is not None:
            self.receiver_thread.join(timeout=2.0)

    def reset(self) -> None:
        """清空本地 action queue；官方 Ready 会清空服务端观测队列但不重载模型。"""
        with self.action_queue_lock:
            self.action_queue = Queue()
        with self.latest_action_lock:
            self.latest_action = -1
        while True:
            try:
                self.observation_queue.get_nowait()
            except Empty:
                break
        self.action_chunk_size = -1
        self.observation_pending.clear()
        self.chunk_request_pending.clear()
        self.must_go.set()
        self.stub.Ready(services_pb2.Empty(), timeout=self.timeout_s)

    def queue_size(self) -> int:
        with self.action_queue_lock:
            return self.action_queue.qsize()

    def ready_to_send_observation(self) -> bool:
        """队列降到官方阈值后请求下一段 action chunk。"""
        if self.observation_pending.is_set():
            return False
        if self.chunk_request_pending.is_set():
            if time.perf_counter() - self.chunk_request_started_at <= self.timeout_s:
                return False
            self.chunk_request_pending.clear()
            self.last_error = f"Action chunk request exceeded {self.timeout_s:.1f}s; retrying."
        if self.action_chunk_size < 1:
            return self.sent_observations == 0
        with self.action_queue_lock:
            return self.action_queue.qsize() / self.action_chunk_size <= self.chunk_size_threshold

    def send_observation(self, raw_observation: dict[str, Any]) -> bool:
        """将最新观测交给独立上传线程，避免公网传输阻塞仿真循环。"""
        with self.latest_action_lock:
            latest_action = self.latest_action
        # 公网延迟可能长于剩余动作时域，预取请求必须绕过服务端的相似观测过滤。
        must_go = self.must_go.is_set()

        timed_observation = {
            "timestamp": time.time(),
            "timestep": max(latest_action, 0),
            "must_go": must_go,
            "observation": raw_observation,
        }
        self.observation_pending.set()
        self.chunk_request_pending.set()
        self.chunk_request_started_at = time.perf_counter()

        try:
            self.observation_queue.put_nowait(timed_observation)
        except Full:
            try:
                self.observation_queue.get_nowait()
            except Empty:
                pass
            self.observation_queue.put_nowait(timed_observation)
            self.dropped_observations += 1

        self.queued_observations += 1
        if must_go:
            self.must_go.clear()
        return True

    def send_observations(self) -> None:
        """后台上传观测；积压时只发送最新一帧。"""
        while self.running:
            try:
                timed_observation = self.observation_queue.get(timeout=0.1)
            except Empty:
                continue

            self.sender_busy.set()
            upload_started = time.perf_counter()
            try:
                payload = pickle.dumps(timed_observation, protocol=pickle.HIGHEST_PROTOCOL)
                self.stub.SendObservations(send_bytes_in_chunks(payload), timeout=self.timeout_s)
                upload_ms = (time.perf_counter() - upload_started) * 1000.0
                with self.metrics_lock:
                    self.latest_upload_ms = upload_ms
                    self.total_upload_ms += upload_ms
                    self.minimum_upload_ms = min(self.minimum_upload_ms, upload_ms)
                    self.maximum_upload_ms = max(self.maximum_upload_ms, upload_ms)
                self.sent_observations += 1
                self.last_error = None
            except grpc.RpcError as exc:
                self.last_error = f"{exc.code().name}: {exc.details()}"
                self.chunk_request_pending.clear()
                if timed_observation["must_go"]:
                    self.must_go.set()
            finally:
                self.sender_busy.clear()
                self.observation_pending.clear()

    def receive_actions(self) -> None:
        """独立线程持续等待服务端 chunk，模型推理不会阻塞 IsaacLab 主循环。"""
        while self.running:
            try:
                response = self.stub.GetActions(
                    services_pb2.Empty(),
                    timeout=max(self.timeout_s, 3.0),
                )
                if not response.data:
                    continue
                payload = pickle.loads(response.data)  # nosec B301: trusted policy server only.
                incoming_actions = self.parse_actions(payload)
                if incoming_actions:
                    chunk_latency_ms = max(
                        0.0,
                        (time.time() - incoming_actions[0].timestamp) * 1000.0,
                    )
                    with self.metrics_lock:
                        self.latest_chunk_latency_ms = chunk_latency_ms
                        self.total_chunk_latency_ms += chunk_latency_ms
                        self.minimum_chunk_latency_ms = min(
                            self.minimum_chunk_latency_ms, chunk_latency_ms
                        )
                        self.maximum_chunk_latency_ms = max(
                            self.maximum_chunk_latency_ms, chunk_latency_ms
                        )
                self.aggregate_action_queues(incoming_actions)
                self.action_chunk_size = max(self.action_chunk_size, len(incoming_actions))
                self.received_chunks += 1
                self.last_error = None
                self.chunk_request_pending.clear()
                self.must_go.set()
            except grpc.RpcError as exc:
                if not self.running:
                    break
                if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    continue
                self.last_error = f"{exc.code().name}: {exc.details()}"
                time.sleep(0.1)
            except (KeyError, TypeError, ValueError, pickle.UnpicklingError) as exc:
                self.last_error = str(exc)
                time.sleep(0.1)

    def latency_metrics(self) -> dict[str, float]:
        """返回远程传输和 action chunk 的累计延迟指标。"""
        with self.metrics_lock:
            upload_count = max(self.sent_observations, 1)
            chunk_count = max(self.received_chunks, 1)
            return {
                "latest_upload_ms": self.latest_upload_ms,
                "average_upload_ms": self.total_upload_ms / upload_count,
                "minimum_upload_ms": 0.0 if self.sent_observations == 0 else self.minimum_upload_ms,
                "maximum_upload_ms": self.maximum_upload_ms,
                "latest_chunk_latency_ms": self.latest_chunk_latency_ms,
                "average_chunk_latency_ms": self.total_chunk_latency_ms / chunk_count,
                "minimum_chunk_latency_ms": (
                    0.0 if self.received_chunks == 0 else self.minimum_chunk_latency_ms
                ),
                "maximum_chunk_latency_ms": self.maximum_chunk_latency_ms,
            }

    def parse_actions(self, payload: Any) -> list[TimedAction]:
        if not isinstance(payload, list):
            raise TypeError(f"Expected an action list, got {type(payload).__name__}.")
        actions: list[TimedAction] = []
        for item in payload:
            action = torch.as_tensor(np.asarray(item["action"], dtype=np.float32))
            if action.shape != (self.action_dim,) or not bool(torch.isfinite(action).all()):
                raise ValueError(f"Invalid policy action shape/value: {action}.")
            actions.append(
                TimedAction(
                    timestamp=float(item["timestamp"]),
                    timestep=int(item["timestep"]),
                    action=action,
                )
            )
        return actions

    def aggregate_action_queues(self, incoming_actions: list[TimedAction]) -> None:
        """逐 timestep 聚合重叠 chunk，与 LeRobot RobotClient 保持一致。"""
        future_action_queue: Queue[TimedAction] = Queue()
        with self.action_queue_lock:
            current_actions = {
                action.timestep: action.action for action in list(self.action_queue.queue)
            }
        with self.latest_action_lock:
            latest_action = self.latest_action

        for new_action in incoming_actions:
            if new_action.timestep <= latest_action:
                continue
            if new_action.timestep in current_actions:
                new_action.action = self.aggregate_fn(
                    current_actions[new_action.timestep], new_action.action
                )
            future_action_queue.put(new_action)

        with self.action_queue_lock:
            self.action_queue = future_action_queue

    def pop_action(self) -> torch.Tensor | None:
        with self.action_queue_lock:
            if self.action_queue.empty():
                return None
            timed_action = self.action_queue.get_nowait()
        with self.latest_action_lock:
            self.latest_action = timed_action.timestep
        return timed_action.action
