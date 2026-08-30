"""IsaacLab adapter for LeRobot's official asynchronous inference protocol."""

from __future__ import annotations

import io
import json
import pickle
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from queue import Queue
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
        self.received_chunks = 0
        self.sent_observations = 0
        self.last_error: str | None = None

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
        self.receiver_thread.start()

    def stop(self) -> None:
        self.shutdown_event.set()
        self.channel.close()
        if self.receiver_thread is not None:
            self.receiver_thread.join(timeout=2.0)

    def reset(self) -> None:
        """清空本地 action queue；官方 Ready 会清空服务端观测队列但不重载模型。"""
        with self.action_queue_lock:
            self.action_queue = Queue()
        with self.latest_action_lock:
            self.latest_action = -1
        self.action_chunk_size = -1
        self.must_go.set()
        self.stub.Ready(services_pb2.Empty(), timeout=self.timeout_s)

    def queue_size(self) -> int:
        with self.action_queue_lock:
            return self.action_queue.qsize()

    def ready_to_send_observation(self) -> bool:
        """队列降到官方阈值后请求下一段 action chunk。"""
        with self.action_queue_lock:
            return self.action_queue.qsize() / self.action_chunk_size <= self.chunk_size_threshold

    def send_observation(self, raw_observation: dict[str, Any]) -> bool:
        with self.latest_action_lock:
            latest_action = self.latest_action
        with self.action_queue_lock:
            must_go = self.must_go.is_set() and self.action_queue.empty()

        timed_observation = {
            "timestamp": time.time(),
            "timestep": max(latest_action, 0),
            "must_go": must_go,
            "observation": raw_observation,
        }
        payload = pickle.dumps(timed_observation, protocol=pickle.HIGHEST_PROTOCOL)
        try:
            self.stub.SendObservations(send_bytes_in_chunks(payload), timeout=self.timeout_s)
        except grpc.RpcError as exc:
            self.last_error = f"{exc.code().name}: {exc.details()}"
            return False

        self.sent_observations += 1
        if must_go:
            self.must_go.clear()
        return True

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
                self.aggregate_action_queues(incoming_actions)
                self.action_chunk_size = max(self.action_chunk_size, len(incoming_actions))
                self.received_chunks += 1
                self.last_error = None
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
