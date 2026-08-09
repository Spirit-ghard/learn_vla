#!/usr/bin/env python3
"""Keyboard teleoperation entry point for registered LWH simulation tasks."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import traceback
from pathlib import Path

from isaac_runtime import ensure_isaac_runtime


VALIDATION_ENV = "LWH_TELEOP_INPUT_VALIDATION"
VALIDATION_MODE = os.environ.get(VALIDATION_ENV) == "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_OUTPUT_DIR = PROJECT_ROOT / "artifacts/stage2"


ensure_isaac_runtime(supervise_validation=VALIDATION_MODE)

from isaaclab.app import AppLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Teleoperate an LWH IsaacLab task with the keyboard.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments.")
    parser.add_argument(
        "--teleop_render_interval",
        type=int,
        default=1,
        help="Physics steps per render. LeIsaac LiftCube keeps the IsaacLab default 1.",
    )
    parser.add_argument(
        "--teleop_antialiasing_mode",
        default=None,
        choices=["Off", "TAA", "FXAA", "DLSS"],
        help="Optional render anti-aliasing override. Leave unset to match LeIsaac defaults.",
    )
    parser.add_argument(
        "--teleop_rendering_mode",
        default=None,
        choices=["performance", "balanced", "quality"],
        help="Optional IsaacLab rendering preset. Leave unset to match LeIsaac defaults.",
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Match LeIsaac --quality: set FXAA and the quality rendering preset.",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if args.headless:
        parser.error("Keyboard teleoperation requires a GUI; do not use --headless.")
    args.enable_cameras = True
    if args.rendering_mode is None and args.teleop_rendering_mode is not None:
        args.rendering_mode = args.teleop_rendering_mode
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import carb  # noqa: E402
import torch  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401  # 导入后注册自定义 task id。
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402
from lwh_isaaclab_tasks.devices import SO101Keyboard  # noqa: E402


def write_process_status(status: str) -> None:
    """在 Kit 关闭进程前向 Python 监督进程写入最终状态。"""
    status_path = os.environ.get("LWH_VALIDATION_STATUS_FILE")
    if status_path:
        Path(status_path).write_text(status + "\n", encoding="utf-8")


def build_validation_input() -> tuple[object, object, dict[int, tuple[object, object]]]:
    """构造与 Kit UI 测试相同的 Carb 键盘事件注入序列。"""
    import carb  # Kit 启动后再导入，避免脱离 Isaac Sim 运行时。
    import omni.appwindow

    provider = carb.input.acquire_input_provider()
    keyboard = omni.appwindow.get_default_app_window().get_keyboard()
    press = carb.input.KeyboardEventType.KEY_PRESS
    release = carb.input.KeyboardEventType.KEY_RELEASE
    key = carb.input.KeyboardInput
    events = {
        5: (press, key.B),
        7: (release, key.B),
        20: (press, key.D),
        70: (release, key.D),
        85: (press, key.R),
        87: (release, key.R),
        100: (press, key.B),
        102: (release, key.B),
        115: (press, key.U),
        145: (release, key.U),
        160: (press, key.N),
        162: (release, key.N),
    }
    return provider, keyboard, events


def validate_camera_observation(image: torch.Tensor) -> dict[str, object]:
    """确认遥操作步进期间的相机张量尺寸正确且不是空白帧。"""
    if tuple(image.shape) != (1, 480, 640, 3):
        raise AssertionError(f"Unexpected camera shape: {tuple(image.shape)}.")
    image_float = image.float()
    if not torch.isfinite(image_float).all():
        raise AssertionError("Camera observation contains NaN or Inf values.")
    std = float(image_float.std())
    if std < 1.0:
        raise AssertionError(f"Camera observation is nearly blank: std={std:.6f}.")
    return {"shape": list(image.shape), "dtype": str(image.dtype), "std": std}


def read_render_config(env) -> dict[str, object]:
    """读取 Kit 中最终生效的渲染配置，避免只根据启动参数推断。"""
    settings = carb.settings.get_settings()
    aa_value = int(settings.get("/rtx/post/aa/op"))
    dlss_value = int(settings.get("/rtx/post/dlss/execMode"))
    aa_names = {0: "Off", 1: "TAA", 2: "FXAA", 3: "DLSS", 4: "DLAA"}
    dlss_names = {0: "performance", 1: "balanced", 2: "quality", 3: "auto"}
    camera_hz = {"front": float(1.0 / env.scene["front"].cfg.update_period)}
    if "wrist" in env.scene.keys():
        camera_hz["wrist"] = float(1.0 / env.scene["wrist"].cfg.update_period)
    return {
        "preset": args_cli.rendering_mode,
        "antialiasing": aa_names.get(aa_value, f"unknown-{aa_value}"),
        "dlss_mode": dlss_names.get(dlss_value, f"unknown-{dlss_value}"),
        "control_hz": float(1.0 / env.step_dt),
        "render_hz": float(1.0 / (env.physics_dt * env.cfg.sim.render_interval)),
        "render_interval": int(env.cfg.sim.render_interval),
        "camera_hz": camera_hz,
    }


class RateLimiter:
    """将控制循环上限限制在约 60 Hz，并在等待时刷新窗口。"""

    def __init__(self, hz: float) -> None:
        self._period = 1.0 / hz
        self._render_period = min(0.0166, self._period)
        self._next_step = time.perf_counter()

    def sleep(self, env) -> None:
        self._next_step += self._period
        while simulation_app.is_running():
            remaining = self._next_step - time.perf_counter()
            if remaining <= 0.0:
                break
            time.sleep(min(self._render_period, remaining))
            env.sim.render()

        if self._next_step < time.perf_counter() - self._period:
            self._next_step = time.perf_counter()


def main() -> None:
    if args_cli.num_envs < 1:
        raise ValueError("--num_envs must be positive.")
    if args_cli.num_envs != 1:
        print("[WARN] Keyboard teleoperation is intended for --num_envs 1.", flush=True)
    if VALIDATION_MODE:
        VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (VALIDATION_OUTPUT_DIR / "report.json").unlink(missing_ok=True)
        (VALIDATION_OUTPUT_DIR / "failure.txt").unlink(missing_ok=True)

    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
    env_cfg.use_teleop_device("keyboard")
    env_cfg.recorders = None
    # 默认对齐 LeIsaac LiftCube：单 front 相机，IsaacLab 默认渲染设置，render_interval=1。
    env_cfg.sim.render_interval = args_cli.teleop_render_interval
    if args_cli.quality:
        env_cfg.sim.render.antialiasing_mode = "FXAA"
        env_cfg.sim.render.rendering_mode = "quality"
    else:
        if args_cli.teleop_antialiasing_mode is not None:
            env_cfg.sim.render.antialiasing_mode = args_cli.teleop_antialiasing_mode
        if args_cli.teleop_rendering_mode is not None:
            env_cfg.sim.render.rendering_mode = args_cli.teleop_rendering_mode
    # 遥操作 episode 只由 R/N 显式重置，不使用模板中的自动超时。
    if hasattr(env_cfg.terminations, "time_out"):
        env_cfg.terminations.time_out = None

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    render_config = read_render_config(env)
    teleop = SO101Keyboard(env)
    pending_reset: str | None = None
    interrupted = False

    def request_failed_reset() -> None:
        nonlocal pending_reset
        pending_reset = "failure"

    def request_successful_reset() -> None:
        nonlocal pending_reset
        pending_reset = "success"

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\nLWH_TELEOP_STOP_REQUESTED", flush=True)

    teleop.add_callback("R", request_failed_reset)
    teleop.add_callback("N", request_successful_reset)
    teleop.display_controls()

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    control_steps = 0
    reset_count = 0
    was_started = False
    action_was_active = False
    max_joint_delta = 0.0
    episode_max_joint_delta = 0.0
    rate_limiter = RateLimiter(60.0)
    started_count = 0
    seen_action_active = False
    reset_outcomes: list[str] = []
    injected_events: list[dict[str, object]] = []
    episode_control_timestamps: list[float] = []
    control_segments: list[dict[str, object]] = []
    loop_iterations = 0
    loop_started_at = 0.0
    latest_policy_observation: dict[str, torch.Tensor] | None = None

    validation_provider = None
    validation_keyboard = None
    validation_events: dict[int, tuple[object, object]] = {}
    validation_stop_frame = 180
    if VALIDATION_MODE:
        validation_provider, validation_keyboard, validation_events = build_validation_input()

    try:
        env.reset()
        teleop.reset()
        robot = env.scene["robot"]
        episode_initial_joint_pos = robot.data.joint_pos.clone()
        print(
            f"LWH_TELEOP_READY task={args_cli.task} num_envs={env.num_envs} control_hz=60.0",
            flush=True,
        )
        print(
            "LWH_RENDER_CONFIG "
            f"preset={render_config['preset']} antialiasing={render_config['antialiasing']} "
            f"dlss_mode={render_config['dlss_mode']} render_hz={render_config['render_hz']:.1f} "
            f"camera_hz={render_config['camera_hz']} "
            f"render_interval={render_config['render_interval']}",
            flush=True,
        )
        loop_started_at = time.perf_counter()

        while simulation_app.is_running() and not interrupted:
            loop_iterations += 1
            if loop_iterations in validation_events:
                event_type, key = validation_events[loop_iterations]
                validation_provider.buffer_keyboard_key_event(validation_keyboard, event_type, key, 0)
                injected_events.append(
                    {"frame": loop_iterations, "type": event_type.name, "key": key.name}
                )
                print(
                    f"LWH_TELEOP_VALIDATION_EVENT frame={loop_iterations} "
                    f"type={event_type.name} key={key.name}",
                    flush=True,
                )

            with torch.inference_mode():
                action = teleop.advance()
                if teleop.started and not was_started:
                    started_count += 1
                    print("LWH_TELEOP_STARTED", flush=True)
                # 在本轮 render/step 前保存状态，下一轮才能识别期间到达的 B/R/N 回调。
                was_started = teleop.started

                if pending_reset is not None or isinstance(action, dict):
                    outcome = pending_reset or "unspecified"
                    if VALIDATION_MODE and len(episode_control_timestamps) >= 2:
                        segment_elapsed_s = episode_control_timestamps[-1] - episode_control_timestamps[0]
                        control_segments.append(
                            {
                                "outcome": outcome,
                                "steps": len(episode_control_timestamps),
                                "elapsed_s": segment_elapsed_s,
                                "measured_hz": (len(episode_control_timestamps) - 1) / segment_elapsed_s,
                            }
                        )
                    episode_control_timestamps.clear()
                    env.reset()
                    teleop.reset()
                    reset_count += 1
                    reset_outcomes.append(outcome)
                    pending_reset = None
                    action_was_active = False
                    print(
                        f"LWH_TELEOP_RESET outcome={outcome} count={reset_count} "
                        f"max_joint_delta_rad={episode_max_joint_delta:.6f}",
                        flush=True,
                    )
                    episode_initial_joint_pos = robot.data.joint_pos.clone()
                    episode_max_joint_delta = 0.0
                elif action is None:
                    # B 之前仍需渲染，Omniverse 才能持续派发键盘事件。
                    env.sim.render()
                else:
                    if not action_was_active and bool(torch.any(torch.abs(action) > 1.0e-7)):
                        action_was_active = True
                        seen_action_active = True
                        print("LWH_TELEOP_ACTION_ACTIVE", flush=True)
                    if VALIDATION_MODE:
                        episode_control_timestamps.append(time.perf_counter())
                    step_result = env.step(action)
                    if VALIDATION_MODE:
                        latest_policy_observation = step_result[0]["policy"]
                    control_steps += 1
                    joint_delta = float(torch.max(torch.abs(robot.data.joint_pos - episode_initial_joint_pos)))
                    episode_max_joint_delta = max(episode_max_joint_delta, joint_delta)
                    max_joint_delta = max(max_joint_delta, joint_delta)

            rate_limiter.sleep(env)

            if VALIDATION_MODE and loop_iterations >= validation_stop_frame:
                print("LWH_TELEOP_VALIDATION_SEQUENCE_COMPLETE", flush=True)
                break

        loop_elapsed_s = time.perf_counter() - loop_started_at
        if VALIDATION_MODE:
            sim_control_hz = float(1.0 / env.step_dt)
            if args_cli.quality and render_config["antialiasing"] != "FXAA":
                raise AssertionError(f"Expected FXAA, got {render_config}.")
            if abs(sim_control_hz - 60.0) > 1.0e-6:
                raise AssertionError(f"Expected a 60 Hz simulation control step, got {sim_control_hz}.")
            if started_count != 2:
                raise AssertionError(f"Expected two B start events, got {started_count}.")
            if reset_outcomes != ["failure", "success"]:
                raise AssertionError(f"Unexpected R/N reset outcomes: {reset_outcomes}.")
            if len(control_segments) != 2:
                raise AssertionError(f"Expected two measured control segments, got {control_segments}.")
            if not seen_action_active:
                raise AssertionError("Motion keys did not produce a non-zero action.")
            if max_joint_delta < 0.01:
                raise AssertionError(
                    f"Simulated robot did not move enough: max_joint_delta={max_joint_delta:.6f} rad."
                )
            if latest_policy_observation is None:
                raise AssertionError("No policy observation was produced during teleoperation.")
            camera_names = ["front"]
            if "wrist" in latest_policy_observation:
                camera_names.append("wrist")
            camera_observations = {
                name: validate_camera_observation(latest_policy_observation[name])
                for name in camera_names
            }

            report = {
                "status": "passed",
                "task": args_cli.task,
                "num_envs": env.num_envs,
                "validation_method": "carb.input.InputProvider.buffer_keyboard_key_event",
                "render_config": render_config,
                "target_loop_hz": 60.0,
                "sim_control_hz": sim_control_hz,
                "camera_render_hz": float(1.0 / (env.physics_dt * env.cfg.sim.render_interval)),
                "loop_iterations": loop_iterations,
                "loop_elapsed_s": loop_elapsed_s,
                "measured_wall_loop_hz": loop_iterations / loop_elapsed_s,
                "control_steps": control_steps,
                "control_segments": control_segments,
                "started_count": started_count,
                "reset_outcomes": reset_outcomes,
                "max_joint_delta_rad": max_joint_delta,
                "camera_observations": camera_observations,
                "injected_events": injected_events,
                "real_robot_access": False,
            }
            VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            report_path = VALIDATION_OUTPUT_DIR / "report.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                f"LWH_STAGE2_VALIDATION_OK report={report_path} "
                f"max_joint_delta_rad={max_joint_delta:.6f}",
                flush=True,
            )
            write_process_status("passed")
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        env.close()

    print(
        f"LWH_TELEOP_STOPPED control_steps={control_steps} resets={reset_count} "
        f"max_joint_delta_rad={max_joint_delta:.6f}",
        flush=True,
    )


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:
        exit_code = 1
        failure = traceback.format_exc()
        print(failure, flush=True)
        if VALIDATION_MODE:
            VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            (VALIDATION_OUTPUT_DIR / "failure.txt").write_text(failure, encoding="utf-8")
            write_process_status("failed")
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
