#!/usr/bin/env python3
"""Evaluate a LeRobot policy asynchronously in the IsaacLab SO101 task."""

from __future__ import annotations

import argparse
import shutil
import signal
import socket
import subprocess
import time
import traceback
import weakref
from pathlib import Path
from typing import Any

from isaac_runtime import ensure_isaac_runtime


project_root = Path(__file__).resolve().parents[1]
default_policy_path = project_root / "checkpoints/act_so101_table_030000"
default_task_description = "Move the rod into the placement tray."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official-style LeRobot async inference in IsaacLab.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments.")
    parser.add_argument(
        "--server_address",
        default="127.0.0.1:8080",
        help="LeRobot async gRPC server as HOST:PORT.",
    )
    parser.add_argument(
        "--ssh_host",
        default=None,
        help="SSH server host. Setting this enables the managed SSH tunnel.",
    )
    parser.add_argument("--ssh_port", type=int, default=22, help="SSH server port.")
    parser.add_argument("--ssh_user", default="root", help="SSH server user.")
    parser.add_argument(
        "--ssh_local_port",
        type=int,
        default=18080,
        help="Local port used by the managed SSH tunnel.",
    )
    parser.add_argument(
        "--ssh_remote_port",
        type=int,
        default=8080,
        help="PolicyServer port on the SSH server loopback interface.",
    )
    parser.add_argument(
        "--ssh_connect_timeout_s",
        type=float,
        default=60.0,
        help="Maximum time allowed for SSH authentication and port forwarding.",
    )
    parser.add_argument(
        "--policy_path",
        default=str(default_policy_path),
        help="Checkpoint path visible to the policy server, or a Hugging Face repo id.",
    )
    parser.add_argument("--policy_type", default="act", help="LeRobot policy type.")
    parser.add_argument("--policy_device", default="cuda", help="Inference device on the server.")
    parser.add_argument(
        "--actions_per_chunk",
        type=int,
        default=60,
        help="Actions returned per inference request. 60 is two seconds at 30 Hz.",
    )
    parser.add_argument(
        "--chunk_size_threshold",
        type=float,
        default=0.65,
        help="Request a fresh chunk when the local queue falls below this ratio.",
    )
    parser.add_argument(
        "--aggregate_fn_name",
        default="weighted_average",
        choices=["weighted_average", "latest_only", "average", "conservative"],
        help="How overlapping action chunks are merged.",
    )
    parser.add_argument("--policy_hz", type=float, default=30.0, help="Action queue consumption frequency.")
    parser.add_argument("--timeout_s", type=float, default=5.0, help="gRPC request timeout.")
    parser.add_argument(
        "--camera_mode",
        default="dual",
        choices=["dual", "triple"],
        help="Policy always uses front+wrist; triple also keeps overview for inspection.",
    )
    parser.add_argument(
        "--ground_mode",
        default="off",
        choices=["off", "on"],
        help="Ground plane mode. off matches the teleoperation performance profile.",
    )
    parser.add_argument(
        "--render_interval",
        type=int,
        default=2,
        help="Physics steps per camera/render update.",
    )
    parser.add_argument(
        "--max_action_delta",
        type=float,
        default=0.05,
        help="Maximum target change per new policy action in radians; 0 disables it.",
    )
    parser.add_argument("--task_description", default=default_task_description, help="Task text sent to policy.")
    parser.add_argument("--max_steps", type=int, default=0, help="Stop after N simulation steps; 0 runs continuously.")
    parser.add_argument("--log_interval", type=int, default=60, help="Status log interval in simulation steps.")

    from isaaclab.app import AppLauncher

    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if args.num_envs != 1:
        parser.error("The async policy client supports --num_envs 1 only.")
    if args.actions_per_chunk < 1 or args.policy_hz <= 0 or args.timeout_s <= 0:
        parser.error("chunk size, policy frequency and timeout must be positive.")
    if not 0.0 <= args.chunk_size_threshold <= 1.0:
        parser.error("--chunk_size_threshold must be between 0 and 1.")
    if args.render_interval < 1 or args.max_steps < 0:
        parser.error("render_interval must be positive and max_steps cannot be negative.")
    if not 1 <= args.ssh_port <= 65535 or not 1 <= args.ssh_local_port <= 65535:
        parser.error("SSH ports must be between 1 and 65535.")
    if not 1 <= args.ssh_remote_port <= 65535 or args.ssh_connect_timeout_s <= 0:
        parser.error("SSH remote port and connect timeout must be positive.")
    if "://" in args.server_address:
        parser.error("--server_address uses HOST:PORT, not an HTTP URL.")
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
        local_port: int,
        remote_port: int,
        connect_timeout_s: float,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.local_port = local_port
        self.remote_port = remote_port
        self.connect_timeout_s = connect_timeout_s
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if shutil.which("ssh") is None:
            raise RuntimeError("Cannot find the ssh executable in PATH.")
        if port_is_open("127.0.0.1", self.local_port):
            raise RuntimeError(
                f"Local port {self.local_port} is already in use. "
                "Stop the old tunnel or choose --ssh_local_port."
            )

        command = [
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
        print(
            f"LWH_SSH_TUNNEL_CONNECT destination={self.user}@{self.host}:{self.port} "
            f"local_port={self.local_port} remote_port={self.remote_port}",
            flush=True,
        )
        # 继承当前终端，OpenSSH 才能直接读取用户输入的密码。
        self.process = subprocess.Popen(command)
        deadline = time.perf_counter() + self.connect_timeout_s
        while time.perf_counter() < deadline:
            return_code = self.process.poll()
            if return_code is not None:
                raise RuntimeError(f"SSH tunnel exited before becoming ready (code {return_code}).")
            if port_is_open("127.0.0.1", self.local_port):
                print(f"LWH_SSH_TUNNEL_READY local_port={self.local_port}", flush=True)
                return
            time.sleep(0.1)
        self.stop()
        raise TimeoutError(
            f"SSH tunnel did not become ready within {self.connect_timeout_s:.1f}s."
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1.0)
        print("LWH_SSH_TUNNEL_STOPPED", flush=True)


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
            self.reset_reason = "failure"
        elif key_name == "N":
            self.start_requested = False
            self.reset_reason = "success"

    def display_controls(self) -> None:
        print(
            "\n".join(
                [
                    "Policy Controls",
                    "  B: start policy inference",
                    "  R: stop inference and reset (failure)",
                    "  N: stop inference and reset (success)",
                    "  Ctrl+C: quit",
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
        raise ValueError(f"Expected action shape (1, 6), got {tuple(action.shape)}.")
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
        print("\nLWH_ASYNC_POLICY_CLIENT_STOP_REQUESTED", flush=True)

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
        print("LWH_ASYNC_POLICY_CLIENT_LOADING_POLICY", flush=True)
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
            f"LWH_ASYNC_POLICY_CLIENT_WAITING_FOR_B task={args_cli.task} "
            f"server={server_address} control_hz={control_hz:.1f} "
            f"policy_hz={effective_policy_hz:.1f} actions_per_chunk={args_cli.actions_per_chunk} "
            f"chunk_size_threshold={args_cli.chunk_size_threshold:.2f} camera_mode={args_cli.camera_mode} "
            "real_robot_access=False",
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
                    f"LWH_ASYNC_POLICY_CLIENT_RESET result={reset_reason} "
                    f"steps={control_steps} waiting_for_b=True",
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
                print("LWH_ASYNC_POLICY_CLIENT_PREPARING", flush=True)

            if not policy_active:
                if start_pending and client.received_chunks >= expected_chunk_count:
                    if client.queue_size() < 1:
                        raise RuntimeError("PolicyServer returned an empty action chunk.")
                    policy_active = True
                    start_pending = False
                    episode_steps = 0
                    episode_started_at = time.perf_counter()
                    rate_limiter.reset()
                    print(
                        f"LWH_ASYNC_POLICY_CLIENT_STARTED initial_queue={client.queue_size()}",
                        flush=True,
                    )
                elif start_pending and time.perf_counter() >= first_chunk_deadline:
                    raise TimeoutError(
                        "Timed out waiting for the first action chunk from PolicyServer: "
                        f"{client.last_error or 'no server error'}"
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
                            f"Policy server failed three observation requests: {client.last_error}"
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
                    f"LWH_ASYNC_POLICY_CLIENT_STEP steps={control_steps} "
                    f"wall_hz={wall_hz:.1f} "
                    f"chunks={client.received_chunks} queue={client.queue_size()} "
                    f"observations={client.sent_observations} dropped={client.dropped_observations} "
                    f"upload_ms={latency['latest_upload_ms']:.1f} "
                    f"chunk_latency_ms={latency['latest_chunk_latency_ms']:.1f} "
                    f"underflows={queue_underflows} "
                    f"last_error={client.last_error or 'none'}",
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
                    f"LWH_ASYNC_POLICY_CLIENT_RESET result=environment_done "
                    f"steps={control_steps} waiting_for_b=True",
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
        f"LWH_ASYNC_POLICY_CLIENT_STOPPED steps={control_steps} "
        f"chunks={client.received_chunks if client else 0} underflows={queue_underflows} "
        f"upload_ms_avg={latency.get('average_upload_ms', 0.0):.1f} "
        f"upload_ms_min={latency.get('minimum_upload_ms', 0.0):.1f} "
        f"upload_ms_max={latency.get('maximum_upload_ms', 0.0):.1f} "
        f"chunk_latency_ms_avg={latency.get('average_chunk_latency_ms', 0.0):.1f} "
        f"chunk_latency_ms_min={latency.get('minimum_chunk_latency_ms', 0.0):.1f} "
        f"chunk_latency_ms_max={latency.get('maximum_chunk_latency_ms', 0.0):.1f}",
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
