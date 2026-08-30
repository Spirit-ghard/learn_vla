#!/usr/bin/env python3
"""Record SO101 teleoperation episodes from IsaacLab simulation into HDF5."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import traceback
from pathlib import Path
from typing import Any

from isaac_runtime import ensure_isaac_runtime


VALIDATION_ENV = "LWH_RECORD_HDF5_VALIDATION"
VALIDATION_MODE = os.environ.get(VALIDATION_ENV) == "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "datasets/hdf5/lwh_so101_table.hdf5"
VALIDATION_OUTPUT_DIR = PROJECT_ROOT / "artifacts/stage3"


ensure_isaac_runtime(supervise_validation=VALIDATION_MODE)

from isaaclab.app import AppLauncher


def next_available_output_path(path: Path) -> Path:
    """目标文件存在时生成 _01/_02 后缀文件名。"""
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Cannot find an available HDF5 output path near: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record an LWH IsaacLab teleoperation session to HDF5.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Number of simulated environments. Recording supports 1.")
    parser.add_argument(
        "--teleop_device",
        default="so101leader",
        choices=["keyboard", "so101leader"],
        help="Teleoperation input device. so101leader only reads the real leader arm and drives simulation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="HDF5 file path. Existing files auto-increment to _01/_02 unless --overwrite or --append is used.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Delete an existing output HDF5 file before recording.")
    parser.add_argument("--append", action="store_true", help="Append new episodes to an existing HDF5 file.")
    parser.add_argument(
        "--camera_mode",
        default="dual",
        choices=["front", "dual", "triple"],
        help=(
            "Camera set to record. front records front; dual records front+wrist; "
            "triple also records overview for visual inspection."
        ),
    )
    parser.add_argument(
        "--ground_mode",
        default="off",
        choices=["off", "on"],
        help="Ground plane mode. off matches the Stage-2 teleop performance profile.",
    )
    parser.add_argument(
        "--teleop_render_interval",
        type=int,
        default=2,
        help="Physics steps per render. Default 2 targets 60 Hz control and 30 Hz camera/render updates.",
    )
    parser.add_argument(
        "--teleop_antialiasing_mode",
        default=None,
        choices=["Off", "TAA", "FXAA", "DLSS"],
        help="Optional render anti-aliasing override. Leave unset to match the current task default.",
    )
    parser.add_argument(
        "--teleop_rendering_mode",
        default=None,
        choices=["performance", "balanced", "quality"],
        help="Optional IsaacLab rendering preset. Leave unset to match the current task default.",
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Use FXAA and the quality rendering preset for sharper visual inspection.",
    )
    parser.add_argument(
        "--compression",
        default="lzf",
        choices=["none", "lzf", "gzip"],
        help="HDF5 compression for appendable datasets. lzf is fast and suitable for online recording.",
    )
    parser.add_argument("--chunk_size", type=int, default=32, help="Target chunk length for non-image datasets.")
    parser.add_argument("--min_frames", type=int, default=1, help="Minimum frames required before saving an episode.")
    parser.add_argument(
        "--leader_port",
        default="/dev/ttyACM0",
        help="Serial port for --teleop_device so101leader.",
    )
    parser.add_argument(
        "--leader_calibration",
        default=None,
        help=(
            "SO101 leader calibration JSON. Defaults to LWH_SO101_LEADER_CALIBRATION, "
            "project configs, LeRobot cache, then LeIsaac cache."
        ),
    )
    parser.add_argument(
        "--leader_id",
        default=None,
        help="Optional LeRobot leader id used to find ~/.cache/huggingface calibration.",
    )
    parser.add_argument(
        "--leader_start_immediately",
        action="store_true",
        help="Mark the first recording episode active immediately; leader position sync is always immediate.",
    )
    parser.add_argument(
        "--leader_keep_torque",
        action="store_true",
        help="Do not disable leader arm torque on connect. Default disables torque for safe passive input.",
    )
    parser.add_argument(
        "--leader_skip_handshake",
        action="store_true",
        help="Skip ping checks for leader motors before reading positions.",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if args.headless:
        parser.error("HDF5 teleoperation recording requires a GUI; do not use --headless.")
    if args.overwrite and args.append:
        parser.error("--overwrite and --append are mutually exclusive.")
    if args.chunk_size < 1:
        parser.error("--chunk_size must be positive.")
    if args.min_frames < 1:
        parser.error("--min_frames must be positive.")
    args.requested_output = args.output.expanduser().resolve()
    args.output = args.requested_output
    if not args.overwrite and not args.append:
        args.output = next_available_output_path(args.requested_output)
    args.enable_cameras = True
    if args.rendering_mode is None and args.teleop_rendering_mode is not None:
        args.rendering_mode = args.teleop_rendering_mode
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import carb  # noqa: E402
import gymnasium as gym  # noqa: E402
import h5py  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401  # 导入后注册自定义 task id。
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402
from lwh_isaaclab_tasks.devices import SO101Keyboard, SO101LeaderArm, resolve_leader_calibration_path  # noqa: E402


def delete_attribute(obj, attr_name: str) -> None:
    """按运行入口参数移除不需要的 scene/observation 配置项。"""
    if hasattr(obj, attr_name):
        delattr(obj, attr_name)


def configure_camera_mode(env_cfg, camera_mode: str) -> None:
    """按入口参数裁剪相机；overview 只供 HDF5/Web 可视化，不默认进入训练转换。"""
    if camera_mode == "front":
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


def write_process_status(status: str) -> None:
    """向 Isaac 运行时监督进程写入最终状态，便于自动验证捕获。"""
    status_path = os.environ.get("LWH_VALIDATION_STATUS_FILE")
    if status_path:
        Path(status_path).write_text(status + "\n", encoding="utf-8")


def build_validation_input() -> tuple[object, object, dict[int, tuple[object, object]]]:
    """构造一段成功 episode 和一段会被丢弃的失败 episode。"""
    import omni.appwindow

    provider = carb.input.acquire_input_provider()
    keyboard = omni.appwindow.get_default_app_window().get_keyboard()
    press = carb.input.KeyboardEventType.KEY_PRESS
    release = carb.input.KeyboardEventType.KEY_RELEASE
    key = carb.input.KeyboardInput
    events = {
        5: (press, key.B),
        7: (release, key.B),
        18: (press, key.D),
        62: (release, key.D),
        76: (press, key.N),
        78: (release, key.N),
        96: (press, key.B),
        98: (release, key.B),
        112: (press, key.U),
        148: (release, key.U),
        164: (press, key.R),
        166: (release, key.R),
    }
    return provider, keyboard, events


def numpy_from_value(value: Any, *, squeeze_first_env: bool = False) -> np.ndarray:
    """把 IsaacLab 的 tensor/scalar 统一转为可写入 HDF5 的 numpy 数组。"""
    if isinstance(value, torch.Tensor):
        array = value.detach().cpu().numpy()
    else:
        array = np.asarray(value)
    if squeeze_first_env and array.ndim > 0 and array.shape[0] == 1:
        array = array[0]
    return array


def normalize_image(image: Any) -> np.ndarray:
    """取第一个环境的 RGB 图像，并保证 HDF5 内保存 uint8 HWC。"""
    array = numpy_from_value(image, squeeze_first_env=True)
    if array.ndim != 3 or array.shape[-1] < 3:
        raise ValueError(f"Unexpected camera image shape: {array.shape}")
    rgb = array[..., :3]
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(rgb)


def write_json_attr(group: h5py.Group, key: str, value: Any) -> None:
    group.attrs[key] = json.dumps(value, ensure_ascii=False)


def write_string_dataset(group: h5py.Group, key: str, values: list[str]) -> None:
    if key in group:
        del group[key]
    dtype = h5py.string_dtype(encoding="utf-8")
    group.create_dataset(key, data=np.asarray(values, dtype=object), dtype=dtype)


def read_string_dataset(group: h5py.Group, key: str) -> list[str] | None:
    """读取 HDF5 字符串数组；用于验证 metadata 中的相机契约。"""
    if key not in group:
        return None
    dataset = group[key]
    values = dataset.asstr()[:]
    return [str(value) for value in values.tolist()]


class HDF5TeleopRecorder:
    """LeIsaac/IsaacLab 风格的在线 HDF5 episode 写入器。"""

    def __init__(
        self,
        path: Path,
        *,
        task: str,
        fps: int,
        joint_names: list[str],
        camera_keys: list[str],
        training_camera_keys: list[str],
        visualization_camera_keys: list[str],
        action_dim: int,
        teleop_device: str,
        append: bool,
        overwrite: bool,
        compression: str,
        chunk_size: int,
        min_frames: int,
        render_config: dict[str, Any],
    ) -> None:
        if path.exists() and not (append or overwrite):
            raise FileExistsError(f"HDF5 output already exists: {path}. Use --overwrite or --append.")
        if overwrite and path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)

        self.path = path
        self.task = task
        self.fps = fps
        self.joint_names = joint_names
        self.camera_keys = camera_keys
        self.training_camera_keys = training_camera_keys
        self.visualization_camera_keys = visualization_camera_keys
        self.action_dim = action_dim
        self.teleop_device = teleop_device
        self.compression = None if compression == "none" else compression
        self.chunk_size = chunk_size
        self.min_frames = min_frames
        self.append = append
        self._file = h5py.File(path, "a" if append else "w")
        self._data_group = self._file.require_group("data")
        self._episodes_group = self._file.require_group("episodes")
        self._metadata_group = self._file.require_group("metadata")
        self._episode_group: h5py.Group | None = None
        self._episode_index: int | None = None
        self._episode_frames = 0
        self._episode_started_at = 0.0

        self._write_metadata(render_config)
        self._next_episode_index = int(self._data_group.attrs.get("total", 0))

    @property
    def is_recording(self) -> bool:
        return self._episode_group is not None

    @property
    def episode_index(self) -> int | None:
        return self._episode_index

    @property
    def episode_frames(self) -> int:
        return self._episode_frames

    def _write_metadata(self, render_config: dict[str, Any]) -> None:
        metadata = self._metadata_group
        metadata.attrs["format"] = "lwh_isaaclab_hdf5_v1"
        metadata.attrs["task"] = self.task
        metadata.attrs["fps"] = int(self.fps)
        metadata.attrs["action_dim"] = int(self.action_dim)
        metadata.attrs["teleop_device"] = self.teleop_device
        metadata.attrs["created_unix_ns"] = int(time.time_ns())
        write_json_attr(metadata, "camera_keys", self.camera_keys)
        write_json_attr(metadata, "training_camera_keys", self.training_camera_keys)
        write_json_attr(metadata, "visualization_camera_keys", self.visualization_camera_keys)
        write_json_attr(metadata, "joint_names", self.joint_names)
        write_json_attr(metadata, "render_config", render_config)
        write_string_dataset(metadata, "camera_keys", self.camera_keys)
        write_string_dataset(metadata, "training_camera_keys", self.training_camera_keys)
        write_string_dataset(metadata, "visualization_camera_keys", self.visualization_camera_keys)
        write_string_dataset(metadata, "joint_names", self.joint_names)

        self._data_group.attrs["env_args"] = json.dumps(
            {
                "task": self.task,
                "type": "lwh_isaaclab_hdf5_v1",
                "fps": int(self.fps),
                "camera_keys": self.camera_keys,
                "training_camera_keys": self.training_camera_keys,
                "visualization_camera_keys": self.visualization_camera_keys,
                "teleop_device": self.teleop_device,
            },
            ensure_ascii=False,
        )
        self._data_group.attrs.setdefault("total", 0)

    def begin_episode(self, initial_state: dict[str, Any]) -> int:
        if self._episode_group is not None:
            raise RuntimeError("Previous episode is still open.")

        episode_index = self._next_episode_index
        demo_name = f"demo_{episode_index}"
        if demo_name in self._data_group:
            raise ValueError(f"Episode group already exists: data/{demo_name}")
        link_name = f"{episode_index:06d}"
        if link_name in self._episodes_group:
            raise ValueError(f"Episode link already exists: episodes/{link_name}")

        group = self._data_group.create_group(demo_name)
        self._episodes_group[link_name] = group
        group.attrs["episode_index"] = int(episode_index)
        group.attrs["task"] = self.task
        group.attrs["teleop_device"] = self.teleop_device
        group.attrs["success"] = False
        group.attrs["valid"] = False
        group.attrs["num_samples"] = 0
        group.attrs["started_unix_ns"] = int(time.time_ns())
        write_json_attr(group, "camera_keys", self.camera_keys)
        write_json_attr(group, "training_camera_keys", self.training_camera_keys)
        write_json_attr(group, "visualization_camera_keys", self.visualization_camera_keys)
        write_json_attr(group, "joint_names", self.joint_names)
        self._write_static_nested(group.require_group("initial_state"), initial_state)

        self._episode_group = group
        self._episode_index = episode_index
        self._episode_frames = 0
        self._episode_started_at = time.perf_counter()
        self._file.flush()
        return episode_index

    def append_frame(
        self,
        *,
        policy_observation: dict[str, torch.Tensor],
        action: torch.Tensor,
        env,
        timestamp_s: float,
    ) -> None:
        if self._episode_group is None or self._episode_index is None:
            raise RuntimeError("No active episode.")

        action_array = numpy_from_value(action, squeeze_first_env=True).astype(np.float32, copy=False)
        state_array = numpy_from_value(policy_observation["joint_pos"], squeeze_first_env=True).astype(
            np.float32,
            copy=False,
        )

        frame: dict[str, Any] = {
            "observation/state": state_array,
            "observation/joint_pos": state_array,
            "action": action_array,
            "actions": action_array,
            "timestamp": np.float64(timestamp_s),
            "frame_index": np.int64(self._episode_frames),
            "episode_index": np.int64(self._episode_index),
            "task": self.task,
        }

        optional_observation_terms = (
            "joint_vel",
            "joint_pos_rel",
            "joint_vel_rel",
            "actions",
            "joint_pos_target",
            "ee_frame_state",
        )
        for term_name in optional_observation_terms:
            if term_name in policy_observation:
                frame[f"observation/{term_name}"] = numpy_from_value(
                    policy_observation[term_name],
                    squeeze_first_env=True,
                ).astype(np.float32, copy=False)

        for camera_key in self.camera_keys:
            if camera_key not in policy_observation:
                raise KeyError(f"Camera observation '{camera_key}' is missing from policy observations.")
            frame[f"observation/images/{camera_key}"] = normalize_image(policy_observation[camera_key])

        # 录制环境状态便于后续回放验证物体轨迹；训练转换默认只使用 state/image/action。
        robot = env.scene["robot"]
        frame["observation/env_state/robot_joint_position"] = numpy_from_value(
            robot.data.joint_pos,
            squeeze_first_env=True,
        ).astype(np.float32, copy=False)
        frame["observation/env_state/robot_joint_velocity"] = numpy_from_value(
            robot.data.joint_vel,
            squeeze_first_env=True,
        ).astype(np.float32, copy=False)
        # banana 是兼容旧数据的 scene key；当前几何是可抓取棍子。
        for object_key in ("banana", "cube"):
            if object_key not in env.scene.keys():
                continue
            object_asset = env.scene[object_key]
            frame[f"observation/env_state/{object_key}_root_pose"] = numpy_from_value(
                object_asset.data.root_pose_w,
                squeeze_first_env=True,
            ).astype(np.float32, copy=False)
            frame[f"observation/env_state/{object_key}_root_velocity"] = numpy_from_value(
                object_asset.data.root_vel_w,
                squeeze_first_env=True,
            ).astype(np.float32, copy=False)
            frame["observation/env_state/object_root_pose"] = frame[f"observation/env_state/{object_key}_root_pose"]
            frame["observation/env_state/object_root_velocity"] = frame[
                f"observation/env_state/{object_key}_root_velocity"
            ]
            break

        for key, value in frame.items():
            self._append_dataset(key, value)
        self._episode_frames += 1

    def finish_episode(self, *, success: bool, outcome: str) -> dict[str, Any]:
        if self._episode_group is None or self._episode_index is None:
            raise RuntimeError("No active episode.")

        group = self._episode_group
        episode_index = self._episode_index
        valid = self._episode_frames >= self.min_frames
        group.attrs["success"] = bool(success)
        group.attrs["valid"] = bool(valid)
        group.attrs["outcome"] = outcome
        group.attrs["num_samples"] = int(self._episode_frames)
        group.attrs["ended_unix_ns"] = int(time.time_ns())
        group.attrs["duration_s"] = float(time.perf_counter() - self._episode_started_at)
        self._write_scalar_dataset(group, "success", np.bool_(success))
        self._write_scalar_dataset(group, "valid", np.bool_(valid))
        self._write_scalar_dataset(group, "num_samples", np.int64(self._episode_frames))
        self._data_group.attrs["total"] = int(max(int(self._data_group.attrs.get("total", 0)), episode_index + 1))

        summary = {
            "episode_index": episode_index,
            "success": bool(success),
            "valid": bool(valid),
            "outcome": outcome,
            "num_samples": self._episode_frames,
        }
        self._episode_group = None
        self._episode_index = None
        self._episode_frames = 0
        self._next_episode_index = episode_index + 1
        self._file.flush()
        return summary

    def discard_episode(self, *, reason: str) -> dict[str, Any] | None:
        """废弃失败、中断或帧数不足的 episode。"""
        if self._episode_group is None or self._episode_index is None:
            return None

        episode_index = self._episode_index
        frame_count = self._episode_frames
        demo_name = f"demo_{episode_index}"
        link_name = f"{episode_index:06d}"
        self._episode_group = None
        self._episode_index = None
        self._episode_frames = 0

        if link_name in self._episodes_group:
            del self._episodes_group[link_name]
        if demo_name in self._data_group:
            del self._data_group[demo_name]
        self._file.flush()
        return {
            "episode_index": episode_index,
            "num_samples": frame_count,
            "reason": reason,
        }

    def close(self) -> None:
        remove_empty_file = (not self.append) and len(self._data_group.keys()) == 0
        self._file.flush()
        self._file.close()
        if remove_empty_file:
            self.path.unlink(missing_ok=True)

    def _append_dataset(self, path: str, value: Any) -> None:
        if self._episode_group is None:
            raise RuntimeError("No active episode.")
        parent, name = self._ensure_parent(path)

        if isinstance(value, str):
            if name not in parent:
                parent.create_dataset(
                    name,
                    shape=(0,),
                    maxshape=(None,),
                    chunks=(self.chunk_size,),
                    dtype=h5py.string_dtype(encoding="utf-8"),
                )
            dataset = parent[name]
            dataset.resize((dataset.shape[0] + 1,))
            dataset[-1] = value
            return

        array = numpy_from_value(value)
        if array.dtype.kind == "f" and array.dtype != np.float64:
            array = array.astype(np.float32, copy=False)
        if array.dtype.kind in ("i", "u") and array.dtype.itemsize > 8:
            array = array.astype(np.int64, copy=False)
        if array.ndim > 0:
            array = np.ascontiguousarray(array)

        if name not in parent:
            frame_shape = array.shape
            frame_nbytes = max(int(array.nbytes), 1)
            frame_chunk = max(1, min(self.chunk_size, max(1, 4_000_000 // frame_nbytes)))
            chunk_shape = (frame_chunk, *frame_shape)
            compression = self.compression if array.nbytes >= 1024 else None
            parent.create_dataset(
                name,
                shape=(0, *frame_shape),
                maxshape=(None, *frame_shape),
                chunks=chunk_shape,
                dtype=array.dtype,
                compression=compression,
            )

        dataset = parent[name]
        expected_shape = dataset.shape[1:]
        if expected_shape != array.shape:
            raise ValueError(f"HDF5 dataset '{path}' shape changed from {expected_shape} to {array.shape}.")
        dataset.resize((dataset.shape[0] + 1, *expected_shape))
        dataset[-1] = array

    def _ensure_parent(self, path: str) -> tuple[h5py.Group, str]:
        if self._episode_group is None:
            raise RuntimeError("No active episode.")
        parts = path.split("/")
        parent = self._episode_group
        for part in parts[:-1]:
            parent = parent.require_group(part)
        return parent, parts[-1]

    def _write_static_nested(self, group: h5py.Group, value: dict[str, Any]) -> None:
        for key, nested_value in value.items():
            key = str(key)
            if isinstance(nested_value, dict):
                self._write_static_nested(group.require_group(key), nested_value)
            else:
                array = numpy_from_value(nested_value)
                compression = self.compression if array.size >= 256 else None
                group.create_dataset(key, data=array, compression=compression)

    @staticmethod
    def _write_scalar_dataset(group: h5py.Group, key: str, value: Any) -> None:
        if key in group:
            del group[key]
        group.create_dataset(key, data=value)


class RateLimiter:
    """将录制控制循环限制在约 60 Hz，并在等待时刷新 Kit 窗口事件。"""

    def __init__(self, hz: float) -> None:
        self._period = 1.0 / hz
        self._render_period = min(0.0166, self._period)
        self._next_step = time.perf_counter()

    def sleep(self, env, *, render_during_wait: bool) -> None:
        self._next_step += self._period
        while simulation_app.is_running():
            remaining = self._next_step - time.perf_counter()
            if remaining <= 0.0:
                break
            time.sleep(min(self._render_period, remaining))
            if render_during_wait:
                env.sim.render()

        if self._next_step < time.perf_counter() - self._period:
            self._next_step = time.perf_counter()


def read_render_config(env) -> dict[str, Any]:
    """读取最终生效的相机、渲染和控制频率配置。"""
    settings = carb.settings.get_settings()
    aa_value = int(settings.get("/rtx/post/aa/op"))
    dlss_value = int(settings.get("/rtx/post/dlss/execMode"))
    aa_names = {0: "Off", 1: "TAA", 2: "FXAA", 3: "DLSS", 4: "DLAA"}
    dlss_names = {0: "performance", 1: "balanced", 2: "quality", 3: "auto"}
    camera_hz: dict[str, float] = {}
    for camera_key in ("front", "wrist", "overview"):
        if camera_key in env.scene.keys():
            camera_hz[camera_key] = float(1.0 / env.scene[camera_key].cfg.update_period)
    return {
        "preset": args_cli.rendering_mode,
        "antialiasing": aa_names.get(aa_value, f"unknown-{aa_value}"),
        "dlss_mode": dlss_names.get(dlss_value, f"unknown-{dlss_value}"),
        "control_hz": float(1.0 / env.step_dt),
        "render_hz": float(1.0 / (env.physics_dt * env.cfg.sim.render_interval)),
        "render_interval": int(env.cfg.sim.render_interval),
        "camera_hz": camera_hz,
    }


def validate_hdf5_recording(path: Path, *, expected_camera_keys: list[str], expected_task: str) -> dict[str, Any]:
    """读取刚生成的 HDF5，确认 episode、图像、动作和时间戳基本有效。"""
    with h5py.File(path, "r") as h5_file:
        if "data" not in h5_file or "episodes" not in h5_file or "metadata" not in h5_file:
            raise AssertionError("HDF5 file misses one of required groups: data, episodes, metadata.")
        demo_names = sorted(h5_file["data"].keys(), key=lambda name: int(name.rsplit("_", 1)[-1]))
        if len(demo_names) != 1:
            raise AssertionError(f"Expected one saved validation episode, got {demo_names}.")
        if sorted(h5_file["episodes"].keys()) != ["000000"]:
            raise AssertionError(f"Unexpected /episodes links: {sorted(h5_file['episodes'].keys())}.")

        metadata = h5_file["metadata"]
        if metadata.attrs["task"] != expected_task:
            raise AssertionError(f"Unexpected task metadata: {metadata.attrs['task']}")
        if int(metadata.attrs["fps"]) != 30:
            raise AssertionError(f"Unexpected HDF5 fps metadata: {metadata.attrs['fps']}")
        metadata_camera_keys = read_string_dataset(metadata, "camera_keys") or []
        if metadata_camera_keys and metadata_camera_keys != expected_camera_keys:
            raise AssertionError(f"Unexpected camera_keys metadata: {metadata_camera_keys}")
        training_camera_keys = read_string_dataset(metadata, "training_camera_keys") or []
        expected_training_camera_keys = [key for key in expected_camera_keys if key in ("front", "wrist")]
        if training_camera_keys and training_camera_keys != expected_training_camera_keys:
            raise AssertionError(f"Unexpected training_camera_keys metadata: {training_camera_keys}")

        summaries: list[dict[str, Any]] = []
        for demo_name in demo_names:
            group = h5_file["data"][demo_name]
            if not bool(group.attrs["success"]):
                raise AssertionError(f"{demo_name} success mismatch: {group.attrs['success']}")
            num_samples = int(group.attrs["num_samples"])
            if num_samples < 10:
                raise AssertionError(f"{demo_name} has too few frames: {num_samples}.")
            if group["observation/state"].shape != (num_samples, 6):
                raise AssertionError(f"{demo_name} state shape mismatch: {group['observation/state'].shape}.")
            if group["action"].shape[0] != num_samples:
                raise AssertionError(f"{demo_name} action frame count mismatch.")
            timestamps = group["timestamp"][:]
            if not np.all(np.diff(timestamps) >= 0.0):
                raise AssertionError(f"{demo_name} timestamps are not monotonic.")

            image_stats: dict[str, Any] = {}
            for camera_key in expected_camera_keys:
                image_dataset = group[f"observation/images/{camera_key}"]
                if image_dataset.shape != (num_samples, 480, 640, 3):
                    raise AssertionError(f"{demo_name}/{camera_key} image shape mismatch: {image_dataset.shape}.")
                sample = image_dataset[min(3, num_samples - 1)]
                std = float(sample.std())
                if std < 1.0:
                    raise AssertionError(f"{demo_name}/{camera_key} image is nearly blank: std={std:.6f}.")
                image_stats[camera_key] = {"shape": list(image_dataset.shape), "std": std}

            summaries.append(
                {
                    "name": demo_name,
                    "success": True,
                    "num_samples": num_samples,
                    "action_shape": list(group["action"].shape),
                    "state_shape": list(group["observation/state"].shape),
                    "images": image_stats,
                }
            )

    return {
        "status": "passed",
        "file": str(path),
        "episodes": summaries,
        "camera_keys": expected_camera_keys,
    }


def main() -> None:
    if args_cli.num_envs != 1:
        raise ValueError("HDF5 recording currently supports exactly --num_envs 1.")
    if args_cli.output != args_cli.requested_output:
        print(
            f"LWH_RECORD_OUTPUT_AUTO_INCREMENT requested={args_cli.requested_output} output={args_cli.output}",
            flush=True,
        )

    if VALIDATION_MODE:
        VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (VALIDATION_OUTPUT_DIR / "record_report.json").unlink(missing_ok=True)
        (VALIDATION_OUTPUT_DIR / "record_failure.txt").unlink(missing_ok=True)

    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
    env_cfg.use_teleop_device(args_cli.teleop_device)
    env_cfg.recorders = None
    configure_camera_mode(env_cfg, args_cli.camera_mode)
    if args_cli.ground_mode == "off":
        delete_attribute(env_cfg.scene, "ground")
    env_cfg.sim.render_interval = args_cli.teleop_render_interval
    if args_cli.quality:
        env_cfg.sim.render.antialiasing_mode = "FXAA"
        env_cfg.sim.render.rendering_mode = "quality"
    else:
        if args_cli.teleop_antialiasing_mode is not None:
            env_cfg.sim.render.antialiasing_mode = args_cli.teleop_antialiasing_mode
        if args_cli.teleop_rendering_mode is not None:
            env_cfg.sim.render.rendering_mode = args_cli.teleop_rendering_mode
    if hasattr(env_cfg.terminations, "time_out"):
        env_cfg.terminations.time_out = None

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped
    recorder: HDF5TeleopRecorder | None = None
    teleop = None
    pending_reset: str | None = None
    interrupted = False
    was_started = False
    finished_episodes: list[dict[str, Any]] = []
    loop_iterations = 0
    loop_started_at = 0.0
    control_steps = 0

    validation_provider = None
    validation_keyboard = None
    validation_events: dict[int, tuple[object, object]] = {}
    validation_stop_frame = 190
    injected_events: list[dict[str, Any]] = []
    if VALIDATION_MODE:
        validation_provider, validation_keyboard, validation_events = build_validation_input()

    def request_failed_reset() -> None:
        nonlocal pending_reset
        pending_reset = "failure"

    def request_successful_reset() -> None:
        nonlocal pending_reset
        pending_reset = "success"

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\nLWH_RECORD_STOP_REQUESTED", flush=True)

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    try:
        observations, _ = env.reset()
        if args_cli.teleop_device == "keyboard":
            teleop = SO101Keyboard(env)
        elif args_cli.teleop_device == "so101leader":
            calibration_path = resolve_leader_calibration_path(args_cli.leader_calibration, args_cli.leader_id)
            teleop = SO101LeaderArm(
                env,
                port=args_cli.leader_port,
                calibration_path=calibration_path,
                start_immediately=args_cli.leader_start_immediately,
                disable_torque_on_connect=not args_cli.leader_keep_torque,
                handshake=not args_cli.leader_skip_handshake,
            )
            print(
                f"LWH_SO101_LEADER_CONNECTED port={args_cli.leader_port} calibration={calibration_path} "
                f"torque_disabled={not args_cli.leader_keep_torque}",
                flush=True,
            )
        else:
            raise ValueError(f"Unsupported teleop device: {args_cli.teleop_device}")

        teleop.add_callback("R", request_failed_reset)
        teleop.add_callback("N", request_successful_reset)
        teleop.display_controls()

        render_config = read_render_config(env)
        camera_keys = ["front"]
        if "wrist" in env.scene.keys():
            camera_keys.append("wrist")
        if "overview" in env.scene.keys():
            camera_keys.append("overview")
        training_camera_keys = [key for key in camera_keys if key in ("front", "wrist")]
        visualization_camera_keys = [key for key in camera_keys if key not in training_camera_keys]
        recorder = HDF5TeleopRecorder(
            args_cli.output,
            task=args_cli.task,
            fps=30,
            joint_names=list(env.scene["robot"].joint_names),
            camera_keys=camera_keys,
            training_camera_keys=training_camera_keys,
            visualization_camera_keys=visualization_camera_keys,
            action_dim=int(env.action_manager.total_action_dim),
            teleop_device=args_cli.teleop_device,
            append=args_cli.append,
            overwrite=args_cli.overwrite,
            compression=args_cli.compression,
            chunk_size=args_cli.chunk_size,
            min_frames=args_cli.min_frames,
            render_config=render_config,
        )

        print(
            f"LWH_RECORD_READY task={args_cli.task} output={args_cli.output} "
            f"teleop_device={args_cli.teleop_device} camera_mode={args_cli.camera_mode} "
            f"camera_keys={camera_keys} training_camera_keys={training_camera_keys} "
            f"visualization_camera_keys={visualization_camera_keys} control_hz=60.0 fps=30",
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

        rate_limiter = RateLimiter(60.0)
        loop_started_at = time.perf_counter()
        while simulation_app.is_running() and not interrupted:
            loop_iterations += 1
            render_during_wait = False
            if loop_iterations in validation_events:
                event_type, key = validation_events[loop_iterations]
                validation_provider.buffer_keyboard_key_event(validation_keyboard, event_type, key, 0)
                injected_events.append({"frame": loop_iterations, "type": event_type.name, "key": key.name})
                print(
                    f"LWH_RECORD_VALIDATION_EVENT frame={loop_iterations} "
                    f"type={event_type.name} key={key.name}",
                    flush=True,
                )

            with torch.inference_mode():
                action = teleop.advance()
                if teleop.started and not was_started and not recorder.is_recording:
                    episode_index = recorder.begin_episode(env.scene.get_state(is_relative=True))
                    print(f"LWH_RECORD_EPISODE_STARTED index={episode_index}", flush=True)
                was_started = teleop.started

                if pending_reset is not None or isinstance(action, dict):
                    outcome = pending_reset or "failure"
                    if recorder.is_recording:
                        if outcome == "success" and recorder.episode_frames >= recorder.min_frames:
                            summary = recorder.finish_episode(success=True, outcome=outcome)
                            finished_episodes.append(summary)
                            print(
                                f"LWH_RECORD_EPISODE_FINISHED index={summary['episode_index']} "
                                f"success={summary['success']} frames={summary['num_samples']} "
                                f"valid={summary['valid']}",
                                flush=True,
                            )
                        else:
                            reason = "too_few_frames" if outcome == "success" else outcome
                            discarded = recorder.discard_episode(reason=reason)
                            if discarded is not None:
                                print(
                                    f"LWH_RECORD_EPISODE_DISCARDED index={discarded['episode_index']} "
                                    f"frames={discarded['num_samples']} reason={discarded['reason']}",
                                    flush=True,
                                )
                    env.reset()
                    teleop.reset()
                    pending_reset = None
                    render_during_wait = True
                elif action is None:
                    env.sim.render()
                    render_during_wait = True
                else:
                    observations, _, _, _, _ = env.step(action)
                    # B 之前也要让仿真跟随真实 leader，但这些同步帧不属于任何 episode。
                    if recorder.is_recording:
                        policy_observation = observations["policy"]
                        timestamp_s = time.perf_counter() - recorder._episode_started_at
                        recorder.append_frame(
                            policy_observation=policy_observation,
                            action=action,
                            env=env,
                            timestamp_s=timestamp_s,
                        )
                        control_steps += 1
                        if recorder.episode_frames == 1 or recorder.episode_frames % 60 == 0:
                            print(
                                f"LWH_RECORD_FRAME episode={recorder.episode_index} "
                                f"frame={recorder.episode_frames}",
                                flush=True,
                            )

            rate_limiter.sleep(env, render_during_wait=render_during_wait)

            if VALIDATION_MODE and loop_iterations >= validation_stop_frame:
                print("LWH_RECORD_VALIDATION_SEQUENCE_COMPLETE", flush=True)
                break

        if recorder.is_recording:
            discarded = recorder.discard_episode(reason="interrupted")
            if discarded is not None:
                print(
                    f"LWH_RECORD_EPISODE_DISCARDED index={discarded['episode_index']} "
                    f"frames={discarded['num_samples']} reason={discarded['reason']}",
                    flush=True,
                )

        loop_elapsed_s = time.perf_counter() - loop_started_at
        if VALIDATION_MODE:
            recorder.close()
            recorder = None
            report = validate_hdf5_recording(
                args_cli.output,
                expected_camera_keys=camera_keys,
                expected_task=args_cli.task,
            )
            report.update(
                {
                    "validation_method": "carb.input.InputProvider.buffer_keyboard_key_event",
                    "finished_episodes": finished_episodes,
                    "injected_events": injected_events,
                    "loop_iterations": loop_iterations,
                    "loop_elapsed_s": loop_elapsed_s,
                    "control_steps": control_steps,
                    "real_robot_access": False,
                    "render_config": render_config,
                }
            )
            VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            report_path = VALIDATION_OUTPUT_DIR / "record_report.json"
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"LWH_STAGE3_RECORD_VALIDATION_OK report={report_path}", flush=True)
            write_process_status("passed")
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        if teleop is not None and hasattr(teleop, "disconnect"):
            teleop.disconnect()
        if recorder is not None:
            if recorder.is_recording:
                discarded = recorder.discard_episode(reason="aborted")
                if discarded is not None:
                    print(
                        f"LWH_RECORD_EPISODE_DISCARDED index={discarded['episode_index']} "
                        f"frames={discarded['num_samples']} reason={discarded['reason']}",
                        flush=True,
                    )
            recorder.close()
        env.close()

    print(
        f"LWH_RECORD_STOPPED output={args_cli.output} episodes={len(finished_episodes)} "
        f"control_steps={control_steps}",
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
            (VALIDATION_OUTPUT_DIR / "record_failure.txt").write_text(failure, encoding="utf-8")
            write_process_status("failed")
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
