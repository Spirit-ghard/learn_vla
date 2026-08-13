#!/usr/bin/env python3
"""Replay LWH HDF5 teleoperation episodes in IsaacLab simulation."""

from __future__ import annotations

import argparse
import os
import signal
import time
import traceback
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isaac_runtime import ensure_isaac_runtime


VALIDATION_ENV = "LWH_REPLAY_HDF5_VALIDATION"
VALIDATION_MODE = os.environ.get(VALIDATION_ENV) == "1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_FILE = PROJECT_ROOT / "datasets/hdf5/lwh_so101_table_leader.hdf5"


ensure_isaac_runtime(supervise_validation=VALIDATION_MODE)

from isaaclab.app import AppLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay HDF5 demonstrations in an LWH IsaacLab task.")
    parser.add_argument("--task", default="Lwh-SO101-Table-v0", help="Registered Gym task id.")
    parser.add_argument("--num_envs", type=int, default=1, help="Replay currently supports one simulated env.")
    parser.add_argument(
        "--dataset_file",
        type=Path,
        default=DEFAULT_DATASET_FILE,
        help="HDF5 file recorded by scripts/record_hdf5.py.",
    )
    parser.add_argument(
        "--episode",
        type=int,
        default=0,
        help="Episode index to load first. Use N/P in the GUI to switch without restarting IsaacSim.",
    )
    parser.add_argument(
        "--select_episodes",
        type=int,
        nargs="+",
        default=None,
        help="Optional episode index list to cycle through. Defaults to every episode in the file.",
    )
    parser.add_argument(
        "--teleop_device",
        default="auto",
        choices=["auto", "keyboard", "so101leader"],
        help="Action-space mode. auto reads HDF5 metadata and falls back to action dimension.",
    )
    parser.add_argument(
        "--camera_mode",
        default="dual",
        choices=["auto", "front", "dual"],
        help="Camera set. dual is the replay default so front+wrist can be inspected together.",
    )
    parser.add_argument(
        "--viewer_layout",
        default="tri",
        choices=["tri", "isaac"],
        help="GUI replay view. tri shows front+wrist on the top row and the main view on the bottom row.",
    )
    parser.add_argument(
        "--ground_mode",
        default="off",
        choices=["off", "on"],
        help="Ground plane mode. off matches the recording/teleop performance profile.",
    )
    parser.add_argument("--action_key", default="action", help="HDF5 action dataset path.")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier. 1.0 follows recorded timestamps.",
    )
    parser.add_argument("--autoplay", action="store_true", help="Start playback immediately after loading.")
    parser.add_argument("--loop", action="store_true", help="Loop through selected episodes.")
    parser.add_argument(
        "--max_frames",
        type=int,
        default=0,
        help="Stop after this many replayed frames. Useful for validation; 0 means unlimited.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Compare replayed robot/cube state and camera validity against recorded data when available.",
    )
    parser.add_argument(
        "--teleop_render_interval",
        type=int,
        default=2,
        help="Physics steps per render. Default matches Stage-3 recording.",
    )
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    args.dataset_file = args.dataset_file.expanduser().resolve()
    if not args.dataset_file.is_file():
        parser.error(f"HDF5 dataset file does not exist: {args.dataset_file}")
    if args.num_envs != 1:
        parser.error("Replay currently supports exactly --num_envs 1.")
    if args.speed <= 0.0:
        parser.error("--speed must be positive.")
    if args.max_frames < 0:
        parser.error("--max_frames cannot be negative.")
    if args.headless and not args.autoplay:
        args.autoplay = True
    args.enable_cameras = True
    return args


args_cli = parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import carb  # noqa: E402
import gymnasium as gym  # noqa: E402
import h5py  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import omni.ui as ui  # noqa: E402

import lwh_isaaclab_tasks  # noqa: E402,F401
from isaaclab_tasks.utils import parse_env_cfg  # noqa: E402


def write_process_status(status: str) -> None:
    """向 Python 监督进程写入验证状态。"""
    status_path = os.environ.get("LWH_VALIDATION_STATUS_FILE")
    if status_path:
        Path(status_path).write_text(status + "\n", encoding="utf-8")


def delete_attribute(obj, attr_name: str) -> None:
    """按回放参数移除不需要的 scene/observation 配置项。"""
    if hasattr(obj, attr_name):
        delattr(obj, attr_name)


def read_json_string_list(group: h5py.Group, key: str) -> list[str]:
    if key not in group:
        return []
    values = group[key].asstr()[:]
    return [str(value) for value in values.tolist()]


def episode_sort_key(name: str) -> int:
    return int(name.rsplit("_", 1)[-1]) if name.startswith("demo_") else int(name)


def read_nested_tensor_tree(group: h5py.Group, device: str) -> dict[str, Any]:
    """把 HDF5 initial_state 递归还原为 IsaacLab reset_to 需要的 tensor 树。"""
    state: dict[str, Any] = {}
    for key, item in group.items():
        if isinstance(item, h5py.Group):
            state[key] = read_nested_tensor_tree(item, device)
        else:
            state[key] = torch.as_tensor(item[()], device=device)
    return state


def get_nested_dataset(group: h5py.Group, path: str) -> h5py.Dataset:
    current: h5py.Group | h5py.Dataset = group
    for part in path.split("/"):
        current = current[part]
    if not isinstance(current, h5py.Dataset):
        raise TypeError(f"HDF5 path is not a dataset: {path}")
    return current


def rgb_tensor_to_numpy(value: torch.Tensor | np.ndarray | None, *, fallback_shape: tuple[int, int, int]) -> np.ndarray:
    """把 IsaacLab 相机张量转为 UI 可显示的 uint8 HWC 图像。"""
    if value is None:
        return np.zeros(fallback_shape, dtype=np.uint8)
    if isinstance(value, torch.Tensor):
        array = value.detach().cpu().numpy()
    else:
        array = np.asarray(value)
    if array.ndim == 4 and array.shape[0] == 1:
        array = array[0]
    if array.ndim == 3 and array.shape[0] in (3, 4):
        array = np.moveaxis(array, 0, -1)
    if array.ndim != 3 or array.shape[-1] < 3:
        return np.zeros(fallback_shape, dtype=np.uint8)
    rgb = array[..., :3]
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(rgb)


class ReplayTriView:
    """回放专用三画面窗口：上排双相机，下排主视角。"""

    def __init__(self, *, width: int = 1280, height: int = 920) -> None:
        self._providers = {
            "front": ui.ByteImageProvider(),
            "wrist": ui.ByteImageProvider(),
            "main": ui.ByteImageProvider(),
        }
        self._fallback = np.zeros((480, 640, 3), dtype=np.uint8)
        self._window = ui.Window(
            "LWH Replay View",
            width=width,
            height=height,
            visible=True,
            dock_preference=ui.DockPreference.LEFT_BOTTOM,
        )
        with self._window.frame:
            with ui.VStack(spacing=4):
                # 上排固定约 40% 高度，用于检查训练数据中的 front/wrist 传感器画面。
                with ui.HStack(height=ui.Percent(40), spacing=4):
                    self._build_image_cell("Front", self._providers["front"])
                    self._build_image_cell("Wrist", self._providers["wrist"])
                # 下排显示 Isaac viewer 主视角，便于同时确认机器人、桌面和方块全局轨迹。
                self._build_image_cell("Main View", self._providers["main"], height=ui.Percent(60))
        self.update(front=None, wrist=None, main=None)

    @staticmethod
    def _build_image_cell(label: str, provider: ui.ByteImageProvider, *, height=None) -> None:
        with ui.ZStack(height=height or ui.Fraction(1)):
            ui.Rectangle(style={"background_color": 0xFF101010})
            ui.ImageWithProvider(
                provider,
                width=ui.Fraction(1),
                height=ui.Fraction(1),
            )
            with ui.VStack():
                ui.Label(
                    label,
                    height=24,
                    alignment=ui.Alignment.LEFT_TOP,
                    style={"color": 0xFFE8E8E8, "background_color": 0xAA000000, "margin": 4},
                )
                ui.Spacer()

    def update(
        self,
        *,
        front: torch.Tensor | np.ndarray | None,
        wrist: torch.Tensor | np.ndarray | None,
        main: torch.Tensor | np.ndarray | None,
    ) -> None:
        for name, image in {
            "front": front,
            "wrist": wrist,
            "main": main,
        }.items():
            rgb = rgb_tensor_to_numpy(image, fallback_shape=self._fallback.shape)
            rgba = np.dstack((rgb, np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)))
            self._providers[name].set_bytes_data(rgba.flatten().data, [rgb.shape[1], rgb.shape[0]])

    def close(self) -> None:
        if self._window is not None:
            self._window.visible = False
            self._window.destroy()
            self._window = None


class HDF5ReplayFile:
    """Small reader for the Stage-3 HDF5 schema."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = h5py.File(path, "r")
        if "data" not in self.file:
            raise ValueError(f"HDF5 file has no /data group: {path}")
        self.episode_names = sorted(self.file["data"].keys(), key=episode_sort_key)
        if not self.episode_names:
            raise ValueError(f"HDF5 file has no episodes: {path}")
        self.metadata = self.file.get("metadata")

    @property
    def episode_count(self) -> int:
        return len(self.episode_names)

    @property
    def fps(self) -> float:
        if self.metadata is not None:
            return float(self.metadata.attrs.get("fps", 30))
        return 30.0

    @property
    def teleop_device(self) -> str:
        if self.metadata is not None and "teleop_device" in self.metadata.attrs:
            return str(self.metadata.attrs["teleop_device"])
        action_dim = int(self.episode_group(0)["action"].shape[-1])
        return "so101leader" if action_dim == 6 else "keyboard"

    @property
    def camera_keys(self) -> list[str]:
        if self.metadata is not None:
            keys = read_json_string_list(self.metadata, "camera_keys")
            if keys:
                return keys
        first = self.episode_group(0)
        if "observation/images" not in first:
            return []
        return sorted(first["observation/images"].keys())

    def episode_group(self, episode_index: int) -> h5py.Group:
        if episode_index < 0 or episode_index >= self.episode_count:
            raise IndexError(f"Episode index out of range: {episode_index}. Count={self.episode_count}")
        return self.file["data"][self.episode_names[episode_index]]

    def close(self) -> None:
        self.file.close()


@dataclass
class EpisodePlayback:
    episode_index: int
    group: h5py.Group
    actions: h5py.Dataset
    timestamps: np.ndarray
    frame: int = 0

    @property
    def num_frames(self) -> int:
        return int(self.actions.shape[0])

    @property
    def finished(self) -> bool:
        return self.frame >= self.num_frames

    def frame_dt(self) -> float:
        if self.frame + 1 < len(self.timestamps):
            return max(float(self.timestamps[self.frame + 1] - self.timestamps[self.frame]), 1.0e-4)
        if len(self.timestamps) > 1:
            return max(float(np.diff(self.timestamps).mean()), 1.0e-4)
        return 1.0 / 30.0


class ReplayVerifier:
    """运行时回放检查：关节、方块和相机是否基本有效。"""

    def __init__(self) -> None:
        self.frames = 0
        self.max_joint_error = 0.0
        self.max_cube_position_error = 0.0
        self.min_camera_std: float | None = None

    def update(self, env, episode: EpisodePlayback, observations: dict[str, torch.Tensor]) -> None:
        index = episode.frame
        group = episode.group
        robot = env.scene["robot"]
        if "observation/env_state/robot_joint_position" in group:
            recorded = torch.as_tensor(
                group["observation/env_state/robot_joint_position"][index],
                device=env.device,
                dtype=torch.float32,
            )
        else:
            recorded = torch.as_tensor(group["observation/state"][index], device=env.device, dtype=torch.float32)
        joint_error = torch.max(torch.abs(robot.data.joint_pos[0] - recorded)).item()
        self.max_joint_error = max(self.max_joint_error, float(joint_error))

        if "cube" in env.scene.keys() and "observation/env_state/cube_root_pose" in group:
            cube = env.scene["cube"]
            recorded_cube_pose = torch.as_tensor(
                group["observation/env_state/cube_root_pose"][index],
                device=env.device,
                dtype=torch.float32,
            )
            cube_error = torch.linalg.vector_norm(cube.data.root_pose_w[0, :3] - recorded_cube_pose[:3]).item()
            self.max_cube_position_error = max(self.max_cube_position_error, float(cube_error))

        policy_obs = observations.get("policy", {})
        for key, value in policy_obs.items():
            if isinstance(value, torch.Tensor) and key in ("front", "wrist"):
                std = float(value[0, ..., :3].float().std())
                self.min_camera_std = std if self.min_camera_std is None else min(self.min_camera_std, std)
        self.frames += 1

    def summary(self) -> dict[str, float | int | None]:
        return {
            "frames": self.frames,
            "max_joint_error_rad": self.max_joint_error,
            "max_cube_position_error_m": self.max_cube_position_error,
            "min_camera_std": self.min_camera_std,
        }


class ReplayKeyboard:
    """Carb 键盘控制：一次启动 IsaacSim 后反复加载/播放 episode。"""

    def __init__(self, *, paused: bool) -> None:
        import omni.appwindow

        self.paused = paused
        self.quit_requested = False
        self.single_step_requested = False
        self.commands: list[str] = []
        self._appwindow = omni.appwindow.get_default_app_window()
        self._input = carb.input.acquire_input_interface()
        self._keyboard = self._appwindow.get_keyboard()
        self._keyboard_sub = self._input.subscribe_to_keyboard_events(
            self._keyboard,
            lambda event, *args, obj=weakref.proxy(self): obj._on_keyboard_event(event, *args),
        )

    def close(self) -> None:
        if getattr(self, "_keyboard_sub", None) is not None:
            self._input.unsubscribe_to_keyboard_events(self._keyboard, self._keyboard_sub)
            self._keyboard_sub = None

    def pop_commands(self) -> list[str]:
        commands = self.commands
        self.commands = []
        return commands

    def _on_keyboard_event(self, event, *args, **kwargs) -> None:
        if event.type != carb.input.KeyboardEventType.KEY_PRESS:
            return
        key_name = event.input.name
        if key_name in ("B", "SPACE"):
            self.commands.append("toggle_pause")
        elif key_name in ("N", "RIGHT"):
            self.commands.append("next")
        elif key_name in ("P", "LEFT"):
            self.commands.append("previous")
        elif key_name == "R":
            self.commands.append("restart")
        elif key_name == "S":
            self.commands.append("single_step")
        elif key_name in ("Q", "ESCAPE"):
            self.commands.append("quit")

    def display_controls(self) -> None:
        print(
            "\n".join(
                [
                    "HDF5 Replay Controls",
                    "  B / Space: pause or resume",
                    "  N / Right: load next episode",
                    "  P / Left: load previous episode",
                    "  R: restart current episode",
                    "  S: single-step while paused",
                    "  Q / Esc: quit",
                ]
            ),
            flush=True,
        )


def resolve_episode_order(dataset: HDF5ReplayFile) -> list[int]:
    if args_cli.select_episodes:
        order = [index for index in args_cli.select_episodes if 0 <= index < dataset.episode_count]
        if not order:
            raise ValueError("--select_episodes did not contain any valid episode indices.")
        return order
    return list(range(dataset.episode_count))


def render_main_view(env) -> np.ndarray | None:
    """读取 Isaac viewer 主视角；普通 viewport 仍由 env.sim.render() 刷新。"""
    try:
        return env.render(recompute=True)
    except RuntimeError as exc:
        print(f"[WARN] Main replay view unavailable: {exc}", flush=True)
        return None


def update_replay_view(view: ReplayTriView | None, env, observations: dict[str, Any] | None) -> None:
    if view is None:
        return
    policy_obs = observations.get("policy", {}) if observations is not None else {}
    view.update(
        front=policy_obs.get("front"),
        wrist=policy_obs.get("wrist"),
        main=render_main_view(env),
    )


def load_episode(env, dataset: HDF5ReplayFile, episode_index: int) -> tuple[EpisodePlayback, dict[str, Any]]:
    group = dataset.episode_group(episode_index)
    if "initial_state" not in group:
        raise KeyError(f"Episode {episode_index} has no initial_state group.")
    initial_state = read_nested_tensor_tree(group["initial_state"], env.device)
    observations, _ = env.reset_to(initial_state, None, is_relative=True)
    env.sim.render()
    actions = get_nested_dataset(group, args_cli.action_key)
    timestamps = np.asarray(group["timestamp"][:], dtype=np.float64) if "timestamp" in group else np.array([])
    if len(timestamps) != actions.shape[0]:
        timestamps = np.arange(actions.shape[0], dtype=np.float64) / dataset.fps
    print(
        f"LWH_REPLAY_EPISODE_LOADED index={episode_index} name={dataset.episode_names[episode_index]} "
        f"success={bool(group.attrs.get('success', False))} outcome={group.attrs.get('outcome', 'unknown')} "
        f"frames={actions.shape[0]}",
        flush=True,
    )
    return EpisodePlayback(episode_index=episode_index, group=group, actions=actions, timestamps=timestamps), observations


def sleep_with_render(env, duration_s: float) -> None:
    deadline = time.perf_counter() + max(0.0, duration_s)
    while simulation_app.is_running():
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            break
        time.sleep(min(remaining, 0.01))
        if env.sim.has_gui():
            env.sim.render()


def main() -> None:
    dataset = HDF5ReplayFile(args_cli.dataset_file)
    controls: ReplayKeyboard | None = None
    replay_view: ReplayTriView | None = None
    env = None
    interrupted = False

    def handle_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True
        print("\nLWH_REPLAY_STOP_REQUESTED", flush=True)

    previous_sigint_handler = signal.signal(signal.SIGINT, handle_sigint)
    try:
        teleop_device = args_cli.teleop_device
        if teleop_device == "auto":
            teleop_device = dataset.teleop_device
        if teleop_device not in ("keyboard", "so101leader"):
            raise ValueError(f"Unsupported teleop_device in dataset: {teleop_device}")

        camera_mode = args_cli.camera_mode
        if camera_mode == "auto":
            camera_mode = "dual" if "wrist" in dataset.camera_keys else "front"

        env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs)
        env_cfg.use_teleop_device(teleop_device)
        env_cfg.recorders = None
        if camera_mode == "front":
            delete_attribute(env_cfg.scene, "wrist")
            delete_attribute(env_cfg.observations.policy, "wrist")
        if args_cli.ground_mode == "off":
            delete_attribute(env_cfg.scene, "ground")
        env_cfg.sim.render_interval = args_cli.teleop_render_interval
        if hasattr(env_cfg.terminations, "time_out"):
            env_cfg.terminations.time_out = None

        render_mode = "rgb_array" if (not args_cli.headless and args_cli.viewer_layout == "tri") else None
        env = gym.make(args_cli.task, cfg=env_cfg, render_mode=render_mode).unwrapped
        observations, _ = env.reset()
        episode_order = resolve_episode_order(dataset)
        if args_cli.episode in episode_order:
            order_pos = episode_order.index(args_cli.episode)
        else:
            order_pos = 0
        episode, observations = load_episode(env, dataset, episode_order[order_pos])
        verifier = ReplayVerifier()

        if not args_cli.headless:
            controls = ReplayKeyboard(paused=not args_cli.autoplay)
            controls.display_controls()
            if args_cli.viewer_layout == "tri":
                replay_view = ReplayTriView()
                update_replay_view(replay_view, env, observations)
        paused = not args_cli.autoplay
        total_replayed_frames = 0
        print(
            f"LWH_REPLAY_READY dataset={args_cli.dataset_file} task={args_cli.task} "
            f"teleop_device={teleop_device} camera_mode={camera_mode} "
            f"episodes={episode_order} autoplay={args_cli.autoplay} viewer_layout={args_cli.viewer_layout}",
            flush=True,
        )

        with torch.inference_mode():
            while simulation_app.is_running() and not interrupted:
                if controls is not None:
                    for command in controls.pop_commands():
                        if command == "toggle_pause":
                            paused = not paused
                            print(f"LWH_REPLAY_PAUSED value={paused}", flush=True)
                        elif command == "single_step":
                            paused = True
                            controls.single_step_requested = True
                        elif command == "restart":
                            episode, observations = load_episode(env, dataset, episode_order[order_pos])
                            verifier = ReplayVerifier()
                            paused = True
                            update_replay_view(replay_view, env, observations)
                        elif command == "next":
                            order_pos = (order_pos + 1) % len(episode_order)
                            episode, observations = load_episode(env, dataset, episode_order[order_pos])
                            verifier = ReplayVerifier()
                            paused = True
                            update_replay_view(replay_view, env, observations)
                        elif command == "previous":
                            order_pos = (order_pos - 1) % len(episode_order)
                            episode, observations = load_episode(env, dataset, episode_order[order_pos])
                            verifier = ReplayVerifier()
                            paused = True
                            update_replay_view(replay_view, env, observations)
                        elif command == "quit":
                            interrupted = True

                if interrupted:
                    break

                if paused and not (controls and controls.single_step_requested):
                    env.sim.render()
                    update_replay_view(replay_view, env, observations)
                    time.sleep(0.01)
                    continue

                if episode.finished:
                    print(
                        f"LWH_REPLAY_EPISODE_FINISHED index={episode.episode_index} "
                        f"summary={verifier.summary()}",
                        flush=True,
                    )
                    if args_cli.loop:
                        order_pos = (order_pos + 1) % len(episode_order)
                        episode, observations = load_episode(env, dataset, episode_order[order_pos])
                        verifier = ReplayVerifier()
                        paused = not args_cli.autoplay
                        update_replay_view(replay_view, env, observations)
                        continue
                    break

                frame_dt = episode.frame_dt() / args_cli.speed
                action = torch.as_tensor(
                    episode.actions[episode.frame],
                    device=env.device,
                    dtype=torch.float32,
                ).reshape(1, -1)
                if action.shape[-1] != env.action_manager.total_action_dim:
                    raise ValueError(
                        f"Action dimension mismatch: dataset={action.shape[-1]}, "
                        f"env={env.action_manager.total_action_dim}. "
                        "Use --teleop_device to select the matching action mode."
                    )

                observations, _, _, _, _ = env.step(action)
                if args_cli.verify or VALIDATION_MODE:
                    verifier.update(env, episode, observations)
                update_replay_view(replay_view, env, observations)
                episode.frame += 1
                total_replayed_frames += 1
                if controls is not None:
                    controls.single_step_requested = False

                if episode.frame == 1 or episode.frame % 120 == 0:
                    print(
                        f"LWH_REPLAY_FRAME episode={episode.episode_index} frame={episode.frame}/{episode.num_frames}",
                        flush=True,
                    )

                if args_cli.max_frames and total_replayed_frames >= args_cli.max_frames:
                    print(
                        f"LWH_REPLAY_MAX_FRAMES_REACHED frames={total_replayed_frames} "
                        f"summary={verifier.summary()}",
                        flush=True,
                    )
                    break
                sleep_with_render(env, frame_dt)

        if VALIDATION_MODE:
            summary = verifier.summary()
            if total_replayed_frames <= 0:
                raise AssertionError("Replay did not step any frames.")
            if args_cli.verify and summary["min_camera_std"] is not None and summary["min_camera_std"] < 1.0:
                raise AssertionError(f"Runtime camera appears blank: {summary}")
            print(f"LWH_STAGE4_REPLAY_VALIDATION_OK frames={total_replayed_frames} summary={summary}", flush=True)
            write_process_status("passed")
        print(f"LWH_REPLAY_STOPPED frames={total_replayed_frames}", flush=True)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
        if controls is not None:
            controls.close()
        if replay_view is not None:
            replay_view.close()
        if env is not None:
            env.close()
        dataset.close()


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except BaseException:
        exit_code = 1
        failure = traceback.format_exc()
        print(failure, flush=True)
        if VALIDATION_MODE:
            write_process_status("failed")
    finally:
        simulation_app.close()
    raise SystemExit(exit_code)
