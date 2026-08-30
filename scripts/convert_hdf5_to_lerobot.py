#!/usr/bin/env python3
"""Convert LWH IsaacLab HDF5 recordings into LeRobotDataset v3."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import h5py
import numpy as np


DEFAULT_TASK_DESCRIPTION = "Move the rod into the placement tray."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert HDF5 files produced by scripts/record_hdf5.py into a LeRobotDataset v3 directory. "
            "Run this in a LeRobot Python environment, not inside IsaacSim."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="Input HDF5 file.")
    parser.add_argument("--repo_id", default="lwh/so101_table", help="LeRobot dataset repo id.")
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=None,
        help="LeRobot dataset root directory. If omitted, LeRobot uses its default cache path.",
    )
    parser.add_argument("--fps", type=int, default=None, help="Target LeRobot dataset FPS. Defaults to HDF5 metadata.")
    parser.add_argument("--robot_type", default=None, help="LeRobot robot_type. Defaults to HDF5 metadata.")
    parser.add_argument(
        "--task_description",
        default=DEFAULT_TASK_DESCRIPTION,
        help="Natural-language task string stored in LeRobot frames.",
    )
    parser.add_argument(
        "--camera_keys",
        default=None,
        help=(
            "Comma-separated camera keys to convert. Defaults to HDF5 training_camera_keys; "
            "standard dual/triple recordings use front,wrist. overview is never included "
            "unless explicitly requested."
        ),
    )
    parser.add_argument(
        "--episodes",
        default="successful",
        choices=["successful", "all"],
        help="Convert only successful episodes by default.",
    )
    parser.add_argument(
        "--include_invalid",
        action="store_true",
        help="Also convert episodes marked invalid. By default invalid/empty episodes are skipped.",
    )
    parser.add_argument(
        "--skip_first_frames",
        type=int,
        default=5,
        help="Frames skipped at the start of each episode, matching LeIsaac's conversion practice.",
    )
    parser.add_argument(
        "--action_key",
        default="action",
        help="HDF5 dataset path used as LeRobot action. Examples: action, actions, observation/joint_pos_target.",
    )
    parser.add_argument(
        "--image_format",
        default="image",
        choices=["video", "image"],
        help="Store LeRobot image observations as videos or individual image files.",
    )
    parser.add_argument("--image_writer_threads", type=int, default=4, help="LeRobot image writer threads.")
    parser.add_argument("--overwrite", action="store_true", help="Remove an existing --output_dir before conversion.")
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Only inspect HDF5 schema and print the LeRobot features; do not import or write LeRobotDataset.",
    )
    args = parser.parse_args()
    args.input = args.input.expanduser().resolve()
    if args.output_dir is not None:
        args.output_dir = args.output_dir.expanduser().resolve()
    if args.fps is not None and args.fps <= 0:
        parser.error("--fps must be positive.")
    if args.skip_first_frames < 0:
        parser.error("--skip_first_frames cannot be negative.")
    return args


def read_json_attr(attrs: h5py.AttributeManager, key: str, default: Any) -> Any:
    if key not in attrs:
        return default
    value = attrs[key]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except TypeError:
        return default
    except json.JSONDecodeError:
        return default


def read_string_dataset(group: h5py.Group, key: str) -> list[str] | None:
    if key not in group:
        return None
    dataset = group[key]
    values = dataset.asstr()[:]
    return [str(value) for value in values.tolist()]


def episode_sort_key(name: str) -> int:
    if name.startswith("demo_"):
        return int(name.rsplit("_", 1)[-1])
    return int(name)


def get_episode_groups(h5_file: h5py.File) -> list[tuple[str, h5py.Group]]:
    if "data" in h5_file:
        root = h5_file["data"]
    elif "episodes" in h5_file:
        root = h5_file["episodes"]
    else:
        raise ValueError("Input HDF5 has neither /data nor /episodes group.")
    names = sorted(root.keys(), key=episode_sort_key)
    return [(name, root[name]) for name in names]


def get_nested_dataset(group: h5py.Group, path: str) -> h5py.Dataset:
    current: h5py.Group | h5py.Dataset = group
    for part in path.split("/"):
        current = current[part]
    if not isinstance(current, h5py.Dataset):
        raise TypeError(f"HDF5 path is not a dataset: {path}")
    return current


def selected_episode_groups(h5_file: h5py.File, args: argparse.Namespace) -> list[tuple[str, h5py.Group]]:
    selected: list[tuple[str, h5py.Group]] = []
    for name, group in get_episode_groups(h5_file):
        if args.episodes == "successful" and not bool(group.attrs.get("success", False)):
            continue
        if not args.include_invalid and not bool(group.attrs.get("valid", True)):
            continue
        num_samples = int(group.attrs.get("num_samples", group["action"].shape[0]))
        if num_samples <= args.skip_first_frames:
            continue
        selected.append((name, group))
    return selected


def read_camera_keys(h5_file: h5py.File, args: argparse.Namespace, first_episode: h5py.Group) -> list[str]:
    if args.camera_keys:
        return [key.strip() for key in args.camera_keys.split(",") if key.strip()]
    metadata = h5_file.get("metadata")
    if metadata is not None:
        training_keys = read_string_dataset(metadata, "training_camera_keys")
        if training_keys:
            return training_keys
        training_keys = read_json_attr(metadata.attrs, "training_camera_keys", None)
        if training_keys:
            return [str(key) for key in training_keys]
        keys = read_string_dataset(metadata, "camera_keys")
        if keys:
            policy_keys = [key for key in keys if key in ("front", "wrist")]
            return policy_keys or keys
        keys = read_json_attr(metadata.attrs, "camera_keys", None)
        if keys:
            normalized_keys = [str(key) for key in keys]
            policy_keys = [key for key in normalized_keys if key in ("front", "wrist")]
            return policy_keys or normalized_keys
    if "observation" not in first_episode or "images" not in first_episode["observation"]:
        return []
    keys = sorted(first_episode["observation/images"].keys())
    policy_keys = [key for key in keys if key in ("front", "wrist")]
    return policy_keys or keys


def read_joint_names(h5_file: h5py.File, state_dim: int) -> list[str]:
    metadata = h5_file.get("metadata")
    if metadata is not None:
        names = read_string_dataset(metadata, "joint_names")
        if names:
            return names
        names = read_json_attr(metadata.attrs, "joint_names", None)
        if names:
            return [str(name) for name in names]
    return [f"joint_{index}.pos" for index in range(state_dim)]


def build_features(
    *,
    state_sample: np.ndarray,
    action_sample: np.ndarray,
    camera_samples: dict[str, np.ndarray],
    joint_names: list[str],
    use_videos: bool,
) -> dict[str, dict[str, Any]]:
    state_shape = tuple(state_sample.astype(np.float32, copy=False).shape)
    action_shape = tuple(action_sample.astype(np.float32, copy=False).shape)
    state_names = joint_names if len(joint_names) == state_shape[0] else [f"state_{i}" for i in range(state_shape[0])]
    action_names = (
        joint_names
        if len(joint_names) == action_shape[0]
        else [f"action_{index}" for index in range(action_shape[0])]
    )
    features: dict[str, dict[str, Any]] = {
        "observation.state": {
            "dtype": "float32",
            "shape": state_shape,
            "names": state_names,
        },
        "action": {
            "dtype": "float32",
            "shape": action_shape,
            "names": action_names,
        },
    }
    for camera_key, image in camera_samples.items():
        features[f"observation.images.{camera_key}"] = {
            "dtype": "video" if use_videos else "image",
            "shape": tuple(image.shape),
            "names": ["height", "width", "channels"],
        }
    return features


def inspect_hdf5(args: argparse.Namespace) -> dict[str, Any]:
    if not args.input.is_file():
        raise FileNotFoundError(f"Input HDF5 file does not exist: {args.input}")

    with h5py.File(args.input, "r") as h5_file:
        groups = selected_episode_groups(h5_file, args)
        if not groups:
            raise ValueError("No episodes selected for conversion.")
        first_name, first_episode = groups[0]
        sample_index = args.skip_first_frames
        action_dataset = get_nested_dataset(first_episode, args.action_key)
        state_sample = np.asarray(first_episode["observation/state"][sample_index], dtype=np.float32)
        action_sample = np.asarray(action_dataset[sample_index], dtype=np.float32)
        camera_keys = read_camera_keys(h5_file, args, first_episode)
        missing_camera_keys = [
            key for key in camera_keys if f"observation/images/{key}" not in first_episode
        ]
        if missing_camera_keys:
            raise KeyError(f"Selected camera stream is missing from HDF5: {missing_camera_keys}")
        camera_samples = {
            key: np.asarray(first_episode[f"observation/images/{key}"][sample_index])
            for key in camera_keys
        }
        joint_names = read_joint_names(h5_file, state_sample.shape[0])
        metadata = h5_file.get("metadata")
        metadata_attrs = metadata.attrs if metadata is not None else {}
        fps = args.fps or int(metadata_attrs.get("fps", 30))
        robot_type = args.robot_type or str(metadata_attrs.get("robot_type", "so101_follower"))
        features = build_features(
            state_sample=state_sample,
            action_sample=action_sample,
            camera_samples=camera_samples,
            joint_names=joint_names,
            use_videos=(args.image_format == "video"),
        )
        episode_summaries = [
            {
                "name": name,
                "success": bool(group.attrs.get("success", False)),
                "valid": bool(group.attrs.get("valid", True)),
                "num_samples": int(group.attrs.get("num_samples", group["action"].shape[0])),
                "converted_frames": int(group.attrs.get("num_samples", group["action"].shape[0]))
                - args.skip_first_frames,
            }
            for name, group in groups
        ]
        return {
            "input": str(args.input),
            "first_episode": first_name,
            "repo_id": args.repo_id,
            "output_dir": str(args.output_dir) if args.output_dir is not None else None,
            "fps": fps,
            "robot_type": robot_type,
            "task_description": args.task_description,
            "camera_keys": camera_keys,
            "action_key": args.action_key,
            "skip_first_frames": args.skip_first_frames,
            "image_format": args.image_format,
            "features": features,
            "episodes": episode_summaries,
        }


def load_lerobot_dataset_class():
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as exc:
        raise RuntimeError(
            "LeRobot is not importable. Run this script in the LeRobot environment, for example "
            "`conda activate lerobot05`, or install LeRobot 0.5.x first."
        ) from exc
    return LeRobotDataset


def convert(args: argparse.Namespace, info: dict[str, Any]) -> dict[str, Any]:
    LeRobotDataset = load_lerobot_dataset_class()
    if args.output_dir is not None and args.output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(f"LeRobot output_dir already exists: {args.output_dir}. Use --overwrite.")
        shutil.rmtree(args.output_dir)

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=int(info["fps"]),
        features=info["features"],
        root=args.output_dir,
        robot_type=str(info["robot_type"]),
        use_videos=(args.image_format == "video"),
        image_writer_threads=args.image_writer_threads,
    )

    converted_episodes = 0
    converted_frames = 0
    try:
        with h5py.File(args.input, "r") as h5_file:
            groups = selected_episode_groups(h5_file, args)
            for name, group in groups:
                num_samples = int(group.attrs.get("num_samples", group["action"].shape[0]))
                action_dataset = get_nested_dataset(group, args.action_key)
                for source_index in range(args.skip_first_frames, num_samples):
                    frame = {
                        "observation.state": np.asarray(
                            group["observation/state"][source_index],
                            dtype=np.float32,
                        ),
                        "action": np.asarray(action_dataset[source_index], dtype=np.float32),
                        "task": args.task_description,
                    }
                    for camera_key in info["camera_keys"]:
                        frame[f"observation.images.{camera_key}"] = np.asarray(
                            group[f"observation/images/{camera_key}"][source_index]
                        )
                    dataset.add_frame(frame)
                    converted_frames += 1
                dataset.save_episode()
                converted_episodes += 1
                print(
                    f"LWH_LEROBOT_EPISODE_SAVED source={name} frames={num_samples - args.skip_first_frames}",
                    flush=True,
                )
    finally:
        dataset.finalize()

    return {
        "status": "converted",
        "repo_id": args.repo_id,
        "root": str(dataset.root),
        "episodes": converted_episodes,
        "frames": converted_frames,
        "features": info["features"],
    }


def main() -> None:
    args = parse_args()
    info = inspect_hdf5(args)
    if args.dry_run:
        print(json.dumps({"status": "dry_run", **info}, indent=2, ensure_ascii=False), flush=True)
        return
    result = convert(args, info)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"LWH_LEROBOT_CONVERT_FAILED: {exc}", file=sys.stderr, flush=True)
        raise
