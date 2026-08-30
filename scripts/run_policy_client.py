#!/usr/bin/env python3
"""在 IsaacLab SO101 任务中异步评估 LeRobot 策略。"""

from __future__ import annotations

import argparse
import os
import runpy
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import traceback
import weakref
from pathlib import Path
from typing import Any

from isaac_runtime import ensure_isaac_runtime


project_root = Path(__file__).resolve().parents[1]
default_policy_path = project_root / "checkpoints/act_so101_table_030000"
default_task_description = "Move the rod into the placement tray."
default_remote_config_path = project_root / "configs/remote_policy_server_config.py"


def load_remote_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        config = runpy.run_path(str(path))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"无法读取远程策略配置 {path}：{exc}") from exc
    if config.get("password"):
        path.chmod(0o600)
    return config


def parse_args() -> argparse.Namespace:
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--remote_config", default=str(default_remote_config_path))
    config_args, _ = config_parser.parse_known_args()
    remote_config_path = Path(config_args.remote_config).expanduser().resolve()
    remote_config = load_remote_config(remote_config_path)
    remote_enabled = bool(remote_config.get("enabled", False))

    parser = argparse.ArgumentParser(description="在 IsaacLab 中运行 LeRobot 异步策略推理。")
    parser.add_argument(
        "--remote_config",
        default=str(remote_config_path),
        help="远程 SSH 和策略服务端配置文件。",
    )
    parser.add_argument(
        "--local_policy_server",
        action="store_true",
        help="忽略远程 SSH 配置，直接连接 --server_address。",
    )
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="已注册的 Gym 任务 ID。")
    parser.add_argument("--num_envs", type=int, default=1, help="并行仿真环境数量。")
    parser.add_argument(
        "--server_address",
        default="127.0.0.1:8080",
        help="LeRobot 异步 gRPC 服务地址，格式为 HOST:PORT。",
    )
    parser.add_argument(
        "--ssh_host",
        default=remote_config.get("host") if remote_enabled else None,
        help="SSH 服务器地址；设置后启用自动管理的 SSH 隧道。",
    )
    parser.add_argument(
        "--ssh_port", type=int, default=remote_config.get("port", 22), help="SSH 服务器端口。"
    )
    parser.add_argument(
        "--ssh_user", default=remote_config.get("user", "root"), help="SSH 登录用户。"
    )
    parser.add_argument(
        "--ssh_local_port",
        type=int,
        default=remote_config.get("local_port", 18080),
        help="SSH 隧道使用的本地端口。",
    )
    parser.add_argument(
        "--ssh_remote_port",
        type=int,
        default=remote_config.get("remote_port", 8080),
        help="服务器回环地址上的策略服务端口。",
    )
    parser.add_argument(
        "--ssh_connect_timeout_s",
        type=float,
        default=60.0,
        help="SSH 认证和端口转发的最长等待时间。",
    )
    parser.add_argument(
        "--policy_path",
        default=remote_config.get("policy_path", str(default_policy_path)),
        help="策略服务端可访问的 checkpoint 路径或 Hugging Face 仓库 ID。",
    )
    parser.add_argument("--policy_type", default="act", help="LeRobot 策略类型。")
    parser.add_argument(
        "--policy_device",
        default=remote_config.get("policy_device", "cuda"),
        help="服务端执行推理的设备。",
    )
    parser.add_argument(
        "--actions_per_chunk",
        type=int,
        default=60,
        help="每次推理返回的动作数；60 个动作对应 30 Hz 下约 2 秒。",
    )
    parser.add_argument(
        "--chunk_size_threshold",
        type=float,
        default=0.65,
        help="本地动作队列低于该比例时请求新的动作块。",
    )
    parser.add_argument(
        "--aggregate_fn_name",
        default="weighted_average",
        choices=["weighted_average", "latest_only", "average", "conservative"],
        help="重叠动作块的融合方式。",
    )
    parser.add_argument("--policy_hz", type=float, default=30.0, help="动作队列消费频率。")
    parser.add_argument("--timeout_s", type=float, default=5.0, help="gRPC 请求超时时间。")
    parser.add_argument(
        "--camera_mode",
        default="dual",
        choices=["dual", "triple"],
        help="策略固定使用 front+wrist；triple 额外保留 overview 供观察。",
    )
    parser.add_argument(
        "--ground_mode",
        default="off",
        choices=["off", "on"],
        help="地面启用模式；off 与遥操作性能配置一致。",
    )
    parser.add_argument(
        "--render_interval",
        type=int,
        default=2,
        help="每次相机和渲染更新对应的物理步数。",
    )
    parser.add_argument(
        "--max_action_delta",
        type=float,
        default=0.05,
        help="每个新策略动作允许的最大目标变化，单位为弧度；0 表示关闭限制。",
    )
    parser.add_argument("--task_description", default=default_task_description, help="发送给策略的任务文本。")
    parser.add_argument("--max_steps", type=int, default=0, help="运行 N 个仿真步后停止；0 表示持续运行。")
    parser.add_argument("--log_interval", type=int, default=60, help="状态日志间隔，单位为仿真步。")

    from isaaclab.app import AppLauncher

    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    args.ssh_password = remote_config.get("password") if remote_enabled else None
    if args.local_policy_server:
        args.ssh_host = None
        args.ssh_password = None
    if args.num_envs != 1:
        parser.error("异步策略客户端目前只支持 --num_envs 1。")
    if args.actions_per_chunk < 1 or args.policy_hz <= 0 or args.timeout_s <= 0:
        parser.error("动作块大小、策略频率和超时时间必须为正数。")
    if not 0.0 <= args.chunk_size_threshold <= 1.0:
        parser.error("--chunk_size_threshold 必须在 0 到 1 之间。")
    if args.render_interval < 1 or args.max_steps < 0:
        parser.error("render_interval 必须为正数，max_steps 不能为负数。")
    if not 1 <= args.ssh_port <= 65535 or not 1 <= args.ssh_local_port <= 65535:
        parser.error("SSH 端口必须在 1 到 65535 之间。")
    if not 1 <= args.ssh_remote_port <= 65535 or args.ssh_connect_timeout_s <= 0:
        parser.error("SSH 远程端口和连接超时时间必须为正数。")
    if "://" in args.server_address:
        parser.error("--server_address 应使用 HOST:PORT，不能填写 HTTP URL。")
    args.enable_cameras = True
    return args


ensure_isaac_runtime()
args_cli = parse_args()

from isaaclab.app import AppLauncher  # noqa: E402


app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
import carb  # noqa: E402
import omni.appwindow  # noqa: E402
import torch  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402
from lwh_isaaclab_tasks.assets.so101_constants import SO101_JOINT_NAMES  # noqa: E402
from lwh_isaaclab_tasks.policy.async_client import IsaacLabAsyncPolicyClient  # noqa: E402


def delete_attribute(obj, attr_name: str) -> None:
    if hasattr(obj, attr_name):
        delattr(obj, attr_name)


def configure_camera_mode(env_cfg, camera_mode: str) -> None:
    """front+wrist 始终进入策略，overview 仅用于人工观察。"""
    if camera_mode == "dual":
        delete_attribute(env_cfg.scene, "overview")
        delete_attribute(env_cfg.observations.policy, "overview")


class RateLimiter:
    def __init__(self, hz: float) -> None:
        self.period = 1.0 / hz
        self.next_step = time.perf_counter()

    def sleep(self) -> None:
        self.next_step += self.period
        while simulation_app.is_running():
            remaining = self.next_step - time.perf_counter()
            if remaining <= 0.0:
                break
            # env.step 已按 render_interval 更新窗口和相机，等待时不重复触发完整渲染。
            time.sleep(min(remaining, self.period))
        if self.next_step < time.perf_counter() - self.period:
            self.next_step = time.perf_counter()

    def reset(self) -> None:
        self.next_step = time.perf_counter()


class ManagedSshTunnel:
    """在客户端进程内维护 SSH 本地端口转发。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str | None,
        local_port: int,
        remote_port: int,
        connect_timeout_s: float,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.local_port = local_port
        self.remote_port = remote_port
        self.connect_timeout_s = connect_timeout_s
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if shutil.which("ssh") is None:
            raise RuntimeError("系统 PATH 中找不到 ssh 命令。")
        if self.password and shutil.which("sshpass") is None:
            raise RuntimeError("自动密码认证需要安装 sshpass。")
        if port_is_open("127.0.0.1", self.local_port):
            raise RuntimeError(
                f"本地端口 {self.local_port} 已被占用。请关闭旧隧道，或修改配置中的 local_port。"
            )

        ssh_command = [
            "ssh",
            "-N",
            "-p",
            str(self.port),
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-L",
            f"{self.local_port}:127.0.0.1:{self.remote_port}",
            f"{self.user}@{self.host}",
        ]
        password_path: str | None = None
        if self.password:
            password_fd, password_path = tempfile.mkstemp(prefix="lwh_ssh_", text=True)
            os.fchmod(password_fd, 0o600)
            with os.fdopen(password_fd, "w", encoding="utf-8") as password_file:
                password_file.write(self.password)
                password_file.write("\n")
            command = ["sshpass", "-f", password_path, *ssh_command]
        else:
            command = ssh_command
        print(
            f"[远程连接] 正在建立 SSH 隧道：服务器={self.user}@{self.host}:{self.port} "
            f"本地端口={self.local_port} 服务端口={self.remote_port}",
            flush=True,
        )
        try:
            # 自动密码模式不依赖当前终端，Ctrl+C 由客户端统一回收隧道。
            self.process = subprocess.Popen(command, start_new_session=bool(self.password))
            deadline = time.perf_counter() + self.connect_timeout_s
            while time.perf_counter() < deadline:
                return_code = self.process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"SSH 隧道尚未就绪便退出，返回码为 {return_code}。"
                    )
                if port_is_open("127.0.0.1", self.local_port):
                    print(f"[远程连接] SSH 隧道已建立：本地端口={self.local_port}", flush=True)
                    return
                time.sleep(0.1)
            self.stop()
            raise TimeoutError(
                f"SSH 隧道在 {self.connect_timeout_s:.1f} 秒内未能建立。"
            )
        finally:
            if password_path is not None:
                Path(password_path).unlink(missing_ok=True)

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1.0)
        print("[远程连接] SSH 隧道已关闭", flush=True)


class PolicyKeyboard:
    """通过 Omniverse/Carb 键盘事件控制策略开始和场景重置。"""

    def __init__(self) -> None:
        self.start_requested = False
        self.reset_reason: str | None = None
        appwindow = omni.appwindow.get_default_app_window()
        self.input = carb.input.acquire_input_interface()
        self.keyboard = appwindow.get_keyboard()
        self.keyboard_sub = self.input.subscribe_to_keyboard_events(
            self.keyboard,
            lambda event, *args, obj=weakref.proxy(self): obj.on_keyboard_event(event, *args),
        )

    def close(self) -> None:
        if self.keyboard_sub is not None:
            self.input.unsubscribe_to_keyboard_events(self.keyboard, self.keyboard_sub)
            self.keyboard_sub = None

    def consume_start(self) -> bool:
        requested = self.start_requested
        self.start_requested = False
        return requested

    def consume_reset(self) -> str | None:
        reason = self.reset_reason
        self.reset_reason = None
        return reason

    def on_keyboard_event(self, event, *args, **kwargs) -> None:
        if event.type != carb.input.KeyboardEventType.KEY_PRESS:
            return
        key_name = event.input.name
        if key_name == "B":
            self.start_requested = True
        elif key_name == "R":
            self.start_requested = False
            self.reset_reason = "失败"
        elif key_name == "N":
            self.start_requested = False
            self.reset_reason = "成功"

    def display_controls(self) -> None:
        print(
            "\n".join(
                [
                    "策略控制按键",
                    "  B：开始策略推理",
                    "  R：停止推理并重置（失败）",
                    "  N：停止推理并重置（成功）",
                    "  Ctrl+C：退出",
                ]
            ),
            flush=True,
        )


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def to_uint8_image(image: torch.Tensor) -> np.ndarray:
    image_cpu = image.detach().cpu()
    if image_cpu.ndim == 4:
        image_cpu = image_cpu[0]
    array = image_cpu.numpy()
    if array.dtype != np.uint8:
        if np.nanmax(array) <= 1.0:
            array = array * 255.0
        array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def raw_policy_observation(observations: dict[str, Any], task: str) -> dict[str, Any]:
    """构造官方 RobotClient 发送给 PolicyServer 的原始硬件观测格式。"""
    policy_obs = observations["policy"]
    state = policy_obs["joint_pos"][0].detach().cpu().numpy().astype(np.float32)
    raw = {f"{name}.pos": float(value) for name, value in zip(SO101_JOINT_NAMES, state, strict=True)}
    raw["front"] = to_uint8_image(policy_obs["front"])
    raw["wrist"] = to_uint8_image(policy_obs["wrist"])
    raw["task"] = task
    return raw


def hold_current_joint_action(observations: dict[str, Any], device: str) -> torch.Tensor:
    return observations["policy"]["joint_pos"].detach().to(device=device, dtype=torch.float32).clone()


def tensor_action(
    action: torch.Tensor,
    *,
    device: str,
    previous_action: torch.Tensor,
    max_delta: float,
) -> torch.Tensor:
    action = action.reshape(1, -1).to(device=device, dtype=torch.float32)
    if action.shape != (1, len(SO101_JOINT_NAMES)):
        raise ValueError(f"策略动作应为 (1, 6)，实际为 {tuple(action.shape)}。")
    if max_delta > 0:
        action = previous_action + torch.clamp(
            action - previous_action,
            min=-max_delta,
            max=max_delta,
        )
    return action


def extract_observations(reset_or_step_result) -> dict[str, Any]:
    return reset_or_step_result[0] if isinstance(reset_or_step_result, tuple) else reset_or_step_result


def main() -> None:
    env = None
    client: IsaacLabAsyncPolicyClient | None = None
    keyboard: PolicyKeyboard | None = None
    tunnel: ManagedSshTunnel | None = None
    interrupted = False

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\n[策略客户端] 收到退出请求", flush=True)

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    control_steps = 0
    queue_underflows = 0
    send_failures = 0

    try:
        server_address = args_cli.server_address
        if args_cli.ssh_host:
            tunnel = ManagedSshTunnel(
                host=args_cli.ssh_host,
                port=args_cli.ssh_port,
                user=args_cli.ssh_user,
                password=args_cli.ssh_password,
                local_port=args_cli.ssh_local_port,
                remote_port=args_cli.ssh_remote_port,
                connect_timeout_s=args_cli.ssh_connect_timeout_s,
            )
            tunnel.start()
            server_address = f"127.0.0.1:{args_cli.ssh_local_port}"

        env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
        env_cfg.use_teleop_device("so101leader")
        env_cfg.recorders = None
        configure_camera_mode(env_cfg, args_cli.camera_mode)
        if args_cli.ground_mode == "off":
            delete_attribute(env_cfg.scene, "ground")
        env_cfg.sim.render_interval = args_cli.render_interval
        if hasattr(env_cfg.terminations, "time_out"):
            env_cfg.terminations.time_out = None

        env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
        observations = extract_observations(env.reset())
        front = to_uint8_image(observations["policy"]["front"])
        client = IsaacLabAsyncPolicyClient(
            server_address=server_address,
            policy_type=args_cli.policy_type,
            policy_path=args_cli.policy_path,
            policy_device=args_cli.policy_device,
            actions_per_chunk=args_cli.actions_per_chunk,
            chunk_size_threshold=args_cli.chunk_size_threshold,
            aggregate_fn_name=args_cli.aggregate_fn_name,
            timeout_s=args_cli.timeout_s,
            joint_names=list(SO101_JOINT_NAMES),
            image_shape=tuple(front.shape),
        )
        print("[策略客户端] 正在加载策略模型", flush=True)
        client.start()

        control_hz = 1.0 / env.step_dt
        if args_cli.policy_hz > control_hz:
            raise ValueError(f"policy_hz {args_cli.policy_hz} exceeds simulation control_hz {control_hz}.")
        policy_interval_steps = max(1, round(control_hz / args_cli.policy_hz))
        effective_policy_hz = control_hz / policy_interval_steps
        rate_limiter = RateLimiter(control_hz)
        keyboard = PolicyKeyboard()
        keyboard.display_controls()
        last_action = hold_current_joint_action(observations, env.device)
        policy_active = False
        start_pending = False
        expected_chunk_count = 0
        first_chunk_deadline = 0.0
        episode_steps = 0
        episode_started_at = time.perf_counter()
        print(
            f"[策略客户端] 已就绪，等待按 B 开始：任务={args_cli.task} "
            f"服务地址={server_address} 控制频率={control_hz:.1f}Hz "
            f"策略频率={effective_policy_hz:.1f}Hz 每块动作数={args_cli.actions_per_chunk} "
            f"预取阈值={args_cli.chunk_size_threshold:.2f} 相机模式={args_cli.camera_mode} "
            "真实机器人访问=关闭",
            flush=True,
        )

        while simulation_app.is_running() and not interrupted:
            if args_cli.max_steps and control_steps >= args_cli.max_steps:
                break

            reset_reason = keyboard.consume_reset()
            start_requested = keyboard.consume_start()
            if reset_reason is not None:
                observations = extract_observations(env.reset())
                client.reset()
                last_action = hold_current_joint_action(observations, env.device)
                policy_active = False
                start_pending = False
                episode_steps = 0
                print(
                    f"[策略客户端] 场景已重置：结果={reset_reason} "
                    f"累计步数={control_steps}，等待再次按 B",
                    flush=True,
                )

            if start_requested and not policy_active and not start_pending:
                client.reset()
                expected_chunk_count = client.received_chunks + 1
                client.send_observation(
                    raw_policy_observation(observations, args_cli.task_description)
                )
                first_chunk_deadline = time.perf_counter() + max(args_cli.timeout_s, 10.0)
                start_pending = True
                print("[策略客户端] 已发送观测，正在等待首个动作块", flush=True)

            if not policy_active:
                if start_pending and client.received_chunks >= expected_chunk_count:
                    if client.queue_size() < 1:
                        raise RuntimeError("策略服务端返回了空动作块。")
                    policy_active = True
                    start_pending = False
                    episode_steps = 0
                    episode_started_at = time.perf_counter()
                    rate_limiter.reset()
                    print(
                        f"[策略客户端] 策略已开始：初始队列={client.queue_size()}",
                        flush=True,
                    )
                elif start_pending and time.perf_counter() >= first_chunk_deadline:
                    raise TimeoutError(
                        "等待策略服务端首个动作块超时："
                        f"{client.last_error or '服务端未返回明确错误'}"
                    )
                else:
                    env.sim.render()
                    time.sleep(1.0 / 60.0)
                    continue

            policy_tick = control_steps % policy_interval_steps == 0
            if policy_tick:
                next_action = client.pop_action()
                if next_action is None:
                    queue_underflows += 1
                else:
                    last_action = tensor_action(
                        next_action,
                        device=env.device,
                        previous_action=last_action,
                        max_delta=args_cli.max_action_delta,
                    )

                if client.ready_to_send_observation():
                    sent = client.send_observation(
                        raw_policy_observation(observations, args_cli.task_description)
                    )
                    send_failures = 0 if sent else send_failures + 1
                    if send_failures >= 3:
                        raise RuntimeError(
                            f"策略服务端连续三次观测请求失败：{client.last_error}"
                        )

            step_result = env.step(last_action)
            observations = step_result[0]
            done = torch.logical_or(step_result[2], step_result[3])
            control_steps += 1
            episode_steps += 1

            if args_cli.log_interval and control_steps % args_cli.log_interval == 0:
                wall_hz = episode_steps / max(
                    time.perf_counter() - episode_started_at,
                    1.0e-6,
                )
                latency = client.latency_metrics()
                print(
                    f"[策略客户端] 运行状态：步数={control_steps} "
                    f"实际循环={wall_hz:.1f}Hz "
                    f"动作块={client.received_chunks} 队列={client.queue_size()} "
                    f"已发观测={client.sent_observations} 丢弃观测={client.dropped_observations} "
                    f"上传延迟={latency['latest_upload_ms']:.1f}ms "
                    f"动作延迟={latency['latest_chunk_latency_ms']:.1f}ms "
                    f"队列欠载={queue_underflows} "
                    f"最近错误={client.last_error or '无'}",
                    flush=True,
                )

            if bool(torch.any(done)):
                observations = extract_observations(env.reset())
                client.reset()
                last_action = hold_current_joint_action(observations, env.device)
                policy_active = False
                start_pending = False
                episode_steps = 0
                print(
                    f"[策略客户端] 环境结束并已重置：累计步数={control_steps}，等待再次按 B",
                    flush=True,
                )

            rate_limiter.sleep()
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        if keyboard is not None:
            keyboard.close()
        if client is not None:
            client.stop()
        if env is not None:
            env.close()
        if tunnel is not None:
            tunnel.stop()

    latency = client.latency_metrics() if client is not None else {}
    print(
        f"[策略客户端] 已停止：步数={control_steps} "
        f"动作块={client.received_chunks if client else 0} 队列欠载={queue_underflows} "
        f"平均上传延迟={latency.get('average_upload_ms', 0.0):.1f}ms "
        f"最小上传延迟={latency.get('minimum_upload_ms', 0.0):.1f}ms "
        f"最大上传延迟={latency.get('maximum_upload_ms', 0.0):.1f}ms "
        f"平均动作延迟={latency.get('average_chunk_latency_ms', 0.0):.1f}ms "
        f"最小动作延迟={latency.get('minimum_chunk_latency_ms', 0.0):.1f}ms "
        f"最大动作延迟={latency.get('maximum_chunk_latency_ms', 0.0):.1f}ms",
        flush=True,
    )


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:
        exit_code = 1
        print(traceback.format_exc(), flush=True)
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
