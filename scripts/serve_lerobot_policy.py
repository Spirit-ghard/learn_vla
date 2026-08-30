#!/usr/bin/env python3
"""为 IsaacLab 客户端运行 LeRobot 官方异步策略服务。"""

from __future__ import annotations

import argparse
import io
import pickle
import sys
from concurrent import futures
from pathlib import Path
from typing import Iterator

import grpc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过 gRPC 提供 LeRobot 异步策略推理。")
    parser.add_argument("--host", default="127.0.0.1", help="服务监听地址。")
    parser.add_argument("--port", type=int, default=8080, help="服务端口。")
    parser.add_argument("--fps", type=int, default=30, help="动作块时间戳使用的策略频率。")
    parser.add_argument(
        "--inference_latency",
        type=float,
        default=0.0,
        help="可选的最小推理周期，单位为秒。",
    )
    parser.add_argument(
        "--obs_queue_timeout",
        type=float,
        default=2.0,
        help="GetActions 等待新观测的时间，单位为秒。",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间。")
    if args.fps <= 0:
        parser.error("--fps 必须为正数。")
    if args.inference_latency < 0 or args.obs_queue_timeout < 0:
        parser.error("延迟和超时时间不能为负数。")
    return args


def receive_bytes_in_chunks(request_iterator: Iterator) -> bytes:
    """读取 LeRobot 官方 Observation 分块。"""
    from lerobot.transport import services_pb2

    buffer = io.BytesIO()
    for item in request_iterator:
        if item.transfer_state == services_pb2.TRANSFER_BEGIN:
            buffer.seek(0)
            buffer.truncate(0)
            buffer.write(item.data)
        elif item.transfer_state == services_pb2.TRANSFER_MIDDLE:
            buffer.write(item.data)
        elif item.transfer_state == services_pb2.TRANSFER_END:
            buffer.write(item.data)
            return buffer.getvalue()
        else:
            raise ValueError(f"未知的观测传输状态：{item.transfer_state}")
    raise ValueError("观测流在 TRANSFER_END 之前结束。")


class IsaacLabPolicyServerAdapter:
    """保持 LeRobot 策略执行不变，只适配网络传输数据。"""

    @staticmethod
    def create(config):
        import lerobot.async_inference.policy_server as policy_server_module
        from lerobot.async_inference.helpers import RemotePolicyConfig, TimedObservation
        from lerobot.async_inference.policy_server import PolicyServer
        from lerobot.transport import services_pb2
        from lerobot.transport.utils import send_bytes_in_chunks

        # 本机 LeRobot 0.5.1 fork 的本地 checkpoint 补丁漏导入 Path。
        if not hasattr(policy_server_module, "Path"):
            policy_server_module.Path = Path

        class Adapter(PolicyServer):
            def SendPolicyInstructions(self, request, context):  # noqa: N802
                wire_config = pickle.loads(request.data)  # nosec B301: trusted client only.
                if not isinstance(wire_config, dict):
                    context.abort(grpc.StatusCode.INVALID_ARGUMENT, "策略配置必须是字典。")
                official_config = RemotePolicyConfig(**wire_config)
                official_request = services_pb2.PolicySetup(
                    data=pickle.dumps(official_config, protocol=pickle.HIGHEST_PROTOCOL)
                )
                return super().SendPolicyInstructions(official_request, context)

            def SendObservations(self, request_iterator, context):  # noqa: N802
                wire_observation = pickle.loads(  # nosec B301: trusted client only.
                    receive_bytes_in_chunks(request_iterator)
                )
                official_observation = TimedObservation(
                    timestamp=float(wire_observation["timestamp"]),
                    timestep=int(wire_observation["timestep"]),
                    observation=wire_observation["observation"],
                    must_go=bool(wire_observation["must_go"]),
                )
                payload = pickle.dumps(official_observation, protocol=pickle.HIGHEST_PROTOCOL)
                official_iterator = send_bytes_in_chunks(
                    payload,
                    services_pb2.Observation,
                    log_prefix="[Isaac 客户端] 观测",
                    silent=True,
                )
                return super().SendObservations(official_iterator, context)

            def GetActions(self, request, context):  # noqa: N802
                response = super().GetActions(request, context)
                if not getattr(response, "data", b""):
                    return services_pb2.Actions()
                official_actions = pickle.loads(response.data)  # nosec B301: local policy output.
                wire_actions = [
                    {
                        "timestamp": float(action.get_timestamp()),
                        "timestep": int(action.get_timestep()),
                        # 普通 list 避免 LeRobot NumPy 2.x 与 Isaac NumPy 1.x 的 pickle 路径不兼容。
                        "action": action.get_action().detach().float().cpu().tolist(),
                    }
                    for action in official_actions
                ]
                return services_pb2.Actions(
                    data=pickle.dumps(wire_actions, protocol=pickle.HIGHEST_PROTOCOL)
                )

        return Adapter(config)


def main() -> None:
    from lerobot.async_inference.configs import PolicyServerConfig
    from lerobot.transport import services_pb2_grpc

    args = parse_args()
    config = PolicyServerConfig(
        host=args.host,
        port=args.port,
        fps=args.fps,
        inference_latency=args.inference_latency,
        obs_queue_timeout=args.obs_queue_timeout,
    )
    policy_server = IsaacLabPolicyServerAdapter.create(config)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    services_pb2_grpc.add_AsyncInferenceServicer_to_server(policy_server, server)
    bound_port = server.add_insecure_port(f"{config.host}:{config.port}")
    if bound_port == 0:
        raise RuntimeError(f"无法将 gRPC 服务绑定到 {config.host}:{config.port}。")

    print(
        f"[策略服务端] 已启动：监听地址={config.host} 端口={bound_port} "
        f"策略频率={config.fps}Hz 协议=LeRobot官方异步协议",
        flush=True,
    )
    server.start()
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\n[策略服务端] 收到停止请求", flush=True)
    finally:
        policy_server.stop()
        server.stop(grace=1.0).wait(timeout=2.0)
        print("[策略服务端] 已停止", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[策略服务端] 启动失败：{exc}", file=sys.stderr, flush=True)
        raise
