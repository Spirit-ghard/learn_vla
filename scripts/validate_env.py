#!/usr/bin/env python3
"""Run an end-to-end simulation validation for a registered LWH task."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

from isaac_runtime import ensure_isaac_runtime


ensure_isaac_runtime(supervise_validation=True)

from isaaclab.app import AppLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an LWH IsaacLab task in simulation.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments.")
    parser.add_argument(
        "--camera_mode",
        default="dual",
        choices=["front", "dual"],
        help="Camera set to validate. front disables wrist; dual validates front+wrist.",
    )
    parser.add_argument("--steps", type=int, default=600, help="Number of control steps before the reset test.")
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=Path("artifacts/stage1"),
        help="Directory for the report and camera samples.",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    # 阶段一必须真实创建并读取相机，即使运行在 headless 模式。
    args.enable_cameras = True
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

import lwh_isaaclab_tasks  # noqa: F401,E402  # 导入后注册自定义 task id。
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402


EXPECTED_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


def progress(message: str) -> None:
    print(f"LWH_STAGE1_PROGRESS {message}", flush=True)


def write_process_status(status: str) -> None:
    """在 Kit 关闭进程前向 Python 监督进程写入最终状态。"""
    status_path = os.environ.get("LWH_VALIDATION_STATUS_FILE")
    if status_path:
        Path(status_path).write_text(status + "\n", encoding="utf-8")


def delete_attribute(obj, attr_name: str) -> None:
    """按 LeIsaac 配置风格在运行时移除不需要的相机项。"""
    if hasattr(obj, attr_name):
        delattr(obj, attr_name)


def image_report(image: torch.Tensor, output_path: Path) -> dict[str, object]:
    """校验一批相机图像并保存第一个环境的 RGB 样图。"""
    if image.ndim != 4 or image.shape[0] < 1 or image.shape[-1] < 3:
        raise AssertionError(f"Unexpected image shape: {tuple(image.shape)}")
    if not torch.isfinite(image.float()).all():
        raise AssertionError("Camera image contains NaN or Inf values.")

    rgb = image[0, ..., :3].detach().cpu().numpy()
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if float(rgb.std()) < 1.0:
        raise AssertionError(f"Camera image is nearly blank: std={float(rgb.std()):.4f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(output_path)
    return {
        "shape": list(image.shape),
        "dtype": str(image.dtype),
        "min": int(rgb.min()),
        "max": int(rgb.max()),
        "mean": float(rgb.mean()),
        "std": float(rgb.std()),
        "sample": str(output_path),
    }


def assert_finite_observations(observations: dict[str, torch.Tensor]) -> None:
    for name, value in observations.items():
        if isinstance(value, torch.Tensor) and not torch.isfinite(value.float()).all():
            raise AssertionError(f"Observation '{name}' contains NaN or Inf values.")


def main() -> None:
    if args_cli.num_envs != 1:
        raise ValueError("Stage-1 camera/reset validation currently requires --num_envs 1.")
    if args_cli.steps < 1:
        raise ValueError("--steps must be positive.")

    args_cli.output_dir.mkdir(parents=True, exist_ok=True)
    (args_cli.output_dir / "failure.txt").unlink(missing_ok=True)
    progress("output-directory-ready")

    spec = gym.spec(args_cli.task)
    progress(f"task-registered id={spec.id}")
    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
    # 这里只配置仿真动作空间，不创建键盘设备，也不访问真实机器人。
    env_cfg.use_teleop_device("keyboard")
    env_cfg.recorders = None
    if args_cli.camera_mode == "front":
        delete_attribute(env_cfg.scene, "wrist")
        delete_attribute(env_cfg.observations.policy, "wrist")

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    progress("environment-created")
    try:
        observations, _ = env.reset()
        progress("initial-reset-complete")
        policy_obs = observations["policy"]
        required_terms = {"joint_pos", "joint_vel", "front"}
        if args_cli.camera_mode == "dual":
            required_terms.add("wrist")
        missing_terms = required_terms.difference(policy_obs)
        if missing_terms:
            raise AssertionError(f"Missing policy observations: {sorted(missing_terms)}")

        robot = env.scene["robot"]
        if list(robot.joint_names) != EXPECTED_JOINT_NAMES:
            raise AssertionError(f"Unexpected joint order: {robot.joint_names}")
        if tuple(policy_obs["joint_pos"].shape) != (1, 6):
            raise AssertionError(f"Unexpected joint state shape: {tuple(policy_obs['joint_pos'].shape)}")
        progress("observation-contract-validated")

        cube = env.scene["cube"]
        initial_cube_state = cube.data.root_state_w.clone()
        action = torch.zeros(
            (env.num_envs, env.action_manager.total_action_dim),
            dtype=torch.float32,
            device=env.device,
        )

        max_abs_joint_position = 0.0
        for _ in range(args_cli.steps):
            observations, _, _, _, _ = env.step(action)
            policy_obs = observations["policy"]
            assert_finite_observations(policy_obs)
            max_abs_joint_position = max(max_abs_joint_position, float(policy_obs["joint_pos"].abs().max()))
        progress(f"simulation-steps-complete count={args_cli.steps}")

        settled_cube_state = cube.data.root_state_w.clone()
        if not torch.isfinite(settled_cube_state).all():
            raise AssertionError("Cube state contains NaN or Inf values.")
        # 桌面顶面约为 z=0.041 m，3 cm 方块中心稳定高度应高于该位置。
        if float(settled_cube_state[0, 2]) < 0.050:
            raise AssertionError(f"Cube fell through the table: z={float(settled_cube_state[0, 2]):.6f}")

        gripper_ids, _ = robot.find_bodies("gripper")
        gripper_position = robot.data.body_pos_w[:, gripper_ids[0]].clone()
        gripper_quaternion = robot.data.body_quat_w[:, gripper_ids[0]].clone()

        front = image_report(policy_obs["front"], args_cli.output_dir / "front.png")
        wrist = None
        if args_cli.camera_mode == "dual":
            wrist = image_report(policy_obs["wrist"], args_cli.output_dir / "wrist.png")
        progress("camera-samples-saved")

        # 先把方块移开，再调用环境 reset，验证默认 reset_scene_to_default 事件。
        displaced_state = settled_cube_state.clone()
        displaced_state[:, 0] += 0.12
        displaced_state[:, 2] += 0.08
        displaced_state[:, 7:] = 0.0
        cube.write_root_state_to_sim(displaced_state)
        env.step(action)
        displaced_position = cube.data.root_pos_w.clone()

        env.reset()
        reset_position = cube.data.root_pos_w.clone()
        if torch.linalg.vector_norm(displaced_position - reset_position, dim=1).min() < 0.05:
            raise AssertionError("Cube displacement was too small to validate reset behavior.")
        if not torch.allclose(reset_position, initial_cube_state[:, :3], atol=2.0e-3, rtol=0.0):
            raise AssertionError(
                f"Cube did not reset: expected={initial_cube_state[:, :3]}, actual={reset_position}"
            )
        progress("cube-reset-validated")

        report = {
            "status": "passed",
            "task": spec.id,
            "entry_point": str(spec.entry_point),
            "num_envs": env.num_envs,
            "camera_mode": args_cli.camera_mode,
            "device": str(env.device),
            "steps": args_cli.steps,
            "physics_dt_s": float(env.physics_dt),
            "control_dt_s": float(env.step_dt),
            "control_hz": float(1.0 / env.step_dt),
            "action_dimension": env.action_manager.total_action_dim,
            "joint_names": list(robot.joint_names),
            "joint_position_shape": list(policy_obs["joint_pos"].shape),
            "max_abs_joint_position_rad": max_abs_joint_position,
            "cube_initial_position_m": initial_cube_state[0, :3].cpu().tolist(),
            "cube_settled_position_m": settled_cube_state[0, :3].cpu().tolist(),
            "cube_displaced_position_m": displaced_position[0].cpu().tolist(),
            "cube_reset_position_m": reset_position[0].cpu().tolist(),
            "gripper_position_m": gripper_position[0].cpu().tolist(),
            "gripper_quaternion_wxyz": gripper_quaternion[0].cpu().tolist(),
            "front_camera": front,
        }
        if wrist is not None:
            report["wrist_camera"] = wrist
        report_path = args_cli.output_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
        print(f"LWH_STAGE1_VALIDATION_OK report={report_path}", flush=True)
        write_process_status("passed")
    finally:
        env.close()


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:
        exit_code = 1
        failure = traceback.format_exc()
        args_cli.output_dir.mkdir(parents=True, exist_ok=True)
        (args_cli.output_dir / "failure.txt").write_text(failure, encoding="utf-8")
        print(failure, flush=True)
        write_process_status("failed")
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
