#!/usr/bin/env python3
"""Inspect SO101 reset zero pose and leader-to-sim joint mapping."""

from __future__ import annotations

import argparse
import math
import signal
import time
from pathlib import Path

from isaac_runtime import ensure_isaac_runtime


ensure_isaac_runtime()

from isaaclab.app import AppLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect SO101 zero pose, joint targets, and leader mapping.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments.")
    parser.add_argument(
        "--camera_mode",
        default="none",
        choices=["none", "front", "dual", "triple"],
        help="Camera sensors to enable. none keeps only the Isaac Sim viewport for lightweight inspection.",
    )
    parser.add_argument(
        "--ground_mode",
        default="off",
        choices=["off", "on"],
        help="Ground plane mode. off matches the teleop/record default.",
    )
    parser.add_argument("--poll_hz", type=float, default=2.0, help="Terminal print frequency.")
    parser.add_argument(
        "--no_leader",
        action="store_true",
        help="Do not connect the SO101 leader; inspect only the simulated reset pose.",
    )
    parser.add_argument(
        "--apply_leader",
        action="store_true",
        help="Apply the leader mapped joint angles to simulation. Default only reads and prints leader values.",
    )
    parser.add_argument("--leader_port", default="/dev/ttyACM0", help="Serial port for the SO101 leader.")
    parser.add_argument(
        "--leader_calibration",
        default=None,
        help="SO101 leader calibration JSON. Defaults to project config, LeRobot cache, then LeIsaac cache.",
    )
    parser.add_argument("--leader_id", default=None, help="Optional LeRobot leader id used to find calibration.")
    parser.add_argument(
        "--leader_keep_torque",
        action="store_true",
        help="Do not disable leader torque on connect. Default disables torque for passive input.",
    )
    parser.add_argument("--leader_skip_handshake", action="store_true", help="Skip leader motor ping checks.")
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if args.num_envs != 1:
        parser.error("SO101 zero-pose inspection currently supports exactly --num_envs 1.")
    if args.poll_hz <= 0.0:
        parser.error("--poll_hz must be positive.")
    if args.apply_leader and args.no_leader:
        parser.error("--apply_leader requires leader connection; remove --no_leader.")
    args.enable_cameras = args.camera_mode != "none"
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import torch  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401  # 导入后注册自定义 task id。
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402
from lwh_isaaclab_tasks.assets import SO101_JOINT_NAMES  # noqa: E402
from lwh_isaaclab_tasks.devices.so101_leader import (  # noqa: E402
    SO101LeaderBus,
    normalized_positions_to_sim_radians,
    resolve_leader_calibration_path,
)


def delete_attribute(obj, attr_name: str) -> None:
    """按检测参数移除不需要的 scene/observation 配置项。"""
    if hasattr(obj, attr_name):
        delattr(obj, attr_name)


def configure_camera_mode(env_cfg, camera_mode: str) -> None:
    """裁剪传感器相机；主窗口 viewport 不受影响。"""
    if camera_mode == "none":
        for attr_name in ("front", "wrist", "overview"):
            delete_attribute(env_cfg.scene, attr_name)
            delete_attribute(env_cfg.observations.policy, attr_name)
    elif camera_mode == "front":
        for attr_name in ("wrist", "overview"):
            delete_attribute(env_cfg.scene, attr_name)
            delete_attribute(env_cfg.observations.policy, attr_name)
    elif camera_mode == "dual":
        delete_attribute(env_cfg.scene, "overview")
        delete_attribute(env_cfg.observations.policy, "overview")
    elif camera_mode == "triple":
        return
    else:
        raise ValueError(f"Unsupported camera mode: {camera_mode}")


def tensor_row(tensor: torch.Tensor) -> list[float]:
    """读取第一个 env 的一维 tensor。"""
    row = tensor[0] if tensor.ndim > 1 else tensor
    return [float(value) for value in row.detach().cpu().tolist()]


def deg(rad_value: float) -> float:
    return math.degrees(rad_value)


def format_joint_table(
    *,
    joint_names: list[str],
    default_joint_pos: list[float],
    joint_pos: list[float],
    joint_pos_target: list[float],
    leader_normalized: dict[str, float] | None,
    leader_sim_rad: list[float] | None,
) -> str:
    """生成终端关节检查表。"""
    lines = [
        "joint                 default_deg   current_deg    target_deg  cur-def_deg  tgt-def_deg  leader_norm  leader_sim_deg",
        "-" * 112,
    ]
    for index, joint_name in enumerate(joint_names):
        default_rad = default_joint_pos[index]
        current_rad = joint_pos[index]
        target_rad = joint_pos_target[index]
        if leader_normalized is None or leader_sim_rad is None:
            leader_norm_text = "      n/a"
            leader_sim_text = "       n/a"
        else:
            leader_norm_text = f"{leader_normalized[joint_name]:11.3f}"
            leader_sim_text = f"{deg(leader_sim_rad[index]):14.3f}"
        lines.append(
            f"{joint_name:<18}"
            f"{deg(default_rad):12.3f}"
            f"{deg(current_rad):14.3f}"
            f"{deg(target_rad):13.3f}"
            f"{deg(current_rad - default_rad):13.3f}"
            f"{deg(target_rad - default_rad):13.3f}"
            f"{leader_norm_text}"
            f"{leader_sim_text}"
        )
    return "\n".join(lines)


def print_snapshot(env, leader_bus: SO101LeaderBus | None, *, apply_leader: bool) -> torch.Tensor | None:
    """打印一次仿真关节和 leader 映射状态；需要时返回可应用到 sim 的 action。"""
    robot = env.scene["robot"]
    joint_names = list(robot.joint_names)
    default_joint_pos = tensor_row(robot.data.default_joint_pos)
    joint_pos = tensor_row(robot.data.joint_pos)
    joint_pos_target = tensor_row(robot.data.joint_pos_target)

    leader_normalized = None
    leader_sim_rad = None
    action = None
    if leader_bus is not None:
        leader_normalized = leader_bus.read_normalized_positions()
        leader_sim_rad = [float(value) for value in normalized_positions_to_sim_radians(leader_normalized).tolist()]
        if apply_leader:
            action = torch.tensor([leader_sim_rad], dtype=torch.float32, device=env.device)

    max_abs_default = max(abs(value) for value in default_joint_pos)
    max_abs_current = max(abs(value) for value in joint_pos)
    max_abs_target = max(abs(value) for value in joint_pos_target)

    gripper_ids, _ = robot.find_bodies("gripper")
    gripper_pos = tensor_row(robot.data.body_pos_w[:, gripper_ids[0], :])

    print("\n" + time.strftime("[%H:%M:%S] SO101 zero-pose inspection"), flush=True)
    print(
        f"max_abs_deg default={deg(max_abs_default):.3f} "
        f"current={deg(max_abs_current):.3f} target={deg(max_abs_target):.3f} "
        f"apply_leader={apply_leader}",
        flush=True,
    )
    print(
        f"gripper_pos_w=({gripper_pos[0]:.4f}, {gripper_pos[1]:.4f}, {gripper_pos[2]:.4f})",
        flush=True,
    )
    print(
        format_joint_table(
            joint_names=joint_names,
            default_joint_pos=default_joint_pos,
            joint_pos=joint_pos,
            joint_pos_target=joint_pos_target,
            leader_normalized=leader_normalized,
            leader_sim_rad=leader_sim_rad,
        ),
        flush=True,
    )
    return action


def main() -> None:
    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
    env_cfg.use_teleop_device("so101leader")
    env_cfg.recorders = None
    configure_camera_mode(env_cfg, args_cli.camera_mode)
    if args_cli.ground_mode == "off":
        delete_attribute(env_cfg.scene, "ground")
    if hasattr(env_cfg.terminations, "time_out"):
        env_cfg.terminations.time_out = None

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    leader_bus = None
    interrupted = False

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\nLWH_SO101_ZERO_INSPECT_STOP_REQUESTED", flush=True)

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    try:
        env.reset()
        robot = env.scene["robot"]
        if list(robot.joint_names) != SO101_JOINT_NAMES:
            raise RuntimeError(f"Unexpected SO101 joint order: {list(robot.joint_names)}")

        if not args_cli.no_leader:
            calibration_path = resolve_leader_calibration_path(args_cli.leader_calibration, args_cli.leader_id)
            leader_bus = SO101LeaderBus(
                args_cli.leader_port,
                calibration_path,
                disable_torque_on_connect=not args_cli.leader_keep_torque,
                handshake=not args_cli.leader_skip_handshake,
            )
            leader_bus.connect()
            print(
                f"LWH_SO101_ZERO_INSPECT_LEADER_CONNECTED port={args_cli.leader_port} "
                f"calibration={calibration_path} torque_disabled={not args_cli.leader_keep_torque}",
                flush=True,
            )

        print(
            f"LWH_SO101_ZERO_INSPECT_READY task={args_cli.task} camera_mode={args_cli.camera_mode} "
            f"apply_leader={args_cli.apply_leader} poll_hz={args_cli.poll_hz}",
            flush=True,
        )
        print("Close Isaac Sim or press Ctrl+C to stop.", flush=True)

        period = 1.0 / args_cli.poll_hz
        next_print_at = 0.0
        while simulation_app.is_running() and not interrupted:
            now = time.perf_counter()
            action = None
            if now >= next_print_at:
                with torch.inference_mode():
                    action = print_snapshot(env, leader_bus, apply_leader=args_cli.apply_leader)
                next_print_at = now + period

            with torch.inference_mode():
                if action is not None:
                    env.step(action)
                else:
                    env.sim.render()
            time.sleep(0.01)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        if leader_bus is not None:
            leader_bus.disconnect()
        env.close()

    print("LWH_SO101_ZERO_INSPECT_STOPPED", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        simulation_app.close()
