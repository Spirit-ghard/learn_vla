#!/usr/bin/env python3
"""Continuously run a registered LWH task until the simulator is closed."""

from __future__ import annotations

import argparse
import signal
import time

from isaac_runtime import ensure_isaac_runtime


ensure_isaac_runtime()

from isaaclab.app import AppLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continuously run an LWH IsaacLab simulation task.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments.")
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    args.enable_cameras = True
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import torch  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401  # 导入后注册自定义 task id。
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402


class RateLimiter:
    """按仿真控制周期限速，并在等待时持续处理窗口事件。"""

    def __init__(self, hz: float) -> None:
        self._period = 1.0 / hz
        self._next_step = time.perf_counter()

    def sleep(self, env) -> None:
        self._next_step += self._period
        while simulation_app.is_running():
            remaining = self._next_step - time.perf_counter()
            if remaining <= 0.0:
                break
            time.sleep(min(remaining, 0.005))
            env.sim.render()

        # 仿真本身慢于实时频率时，从当前时刻重新计时，避免累计追赶。
        if self._next_step < time.perf_counter() - self._period:
            self._next_step = time.perf_counter()


def main() -> None:
    if args_cli.num_envs < 1:
        raise ValueError("--num_envs must be positive.")

    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
    # 阶段一只打开仿真场景并持续执行零动作，不创建遥操作或真实机器人设备。
    env_cfg.recorders = None

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    interrupted = False

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\nLWH_STAGE1_STOP_REQUESTED", flush=True)

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    try:
        env.reset()
        action = torch.zeros(
            (env.num_envs, env.action_manager.total_action_dim),
            dtype=torch.float32,
            device=env.device,
        )
        rate_limiter = RateLimiter(1.0 / env.step_dt)
        print(
            f"LWH_STAGE1_RUNNING task={args_cli.task} num_envs={env.num_envs} "
            f"control_hz={1.0 / env.step_dt:.1f}",
            flush=True,
        )

        while simulation_app.is_running() and not interrupted:
            with torch.inference_mode():
                env.step(action)
            rate_limiter.sleep(env)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        env.close()

    print("LWH_STAGE1_STOPPED", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        simulation_app.close()
