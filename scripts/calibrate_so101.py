#!/usr/bin/env python3
"""Inspect, import, or calibrate SO101 leader/follower arms with LeRobot-compatible calibration files."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEADER_OUTPUT = PROJECT_ROOT / "configs/so101_leader_calibration.json"
DEFAULT_FOLLOWER_OUTPUT = PROJECT_ROOT / "configs/so101_follower_calibration.json"
DEFAULT_LEISAAC_LEADER_CACHE = (
    Path.home() / ".local/share/ov/pkg/leisaac/source/leisaac/leisaac/devices/lerobot/.cache/so101_leader.json"
)
LEROBOT_CACHE_ROOT = Path.home() / ".cache/huggingface/lerobot/calibration"
SO101_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SO101 calibration helper based on LeRobot's official calibration flow."
    )
    parser.add_argument(
        "--arm",
        choices=["leader", "follower"],
        default="leader",
        help="Arm to inspect/import/calibrate.",
    )
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial port used by --calibrate.")
    parser.add_argument(
        "--id",
        default=None,
        help="LeRobot calibration id. Defaults to so101_leader or so101_follower.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Project calibration JSON to inspect or write.",
    )
    parser.add_argument(
        "--calibration",
        default=None,
        help="Explicit calibration path to inspect/import from. Overrides resolver order for --inspect.",
    )
    parser.add_argument("--inspect", action="store_true", help="Print resolved calibration source and summary.")
    parser.add_argument("--calibrate", action="store_true", help="Run LeRobot calibration and save to --output.")
    parser.add_argument(
        "--import_from",
        type=Path,
        default=None,
        help="Copy an existing calibration JSON into --output after schema validation.",
    )
    args = parser.parse_args()
    args.output = (args.output or default_output(args.arm)).expanduser().resolve()
    if args.import_from is not None:
        args.import_from = args.import_from.expanduser().resolve()
    if not (args.inspect or args.calibrate or args.import_from):
        args.inspect = True
    return args


def default_output(arm: str) -> Path:
    return DEFAULT_LEADER_OUTPUT if arm == "leader" else DEFAULT_FOLLOWER_OUTPUT


def default_id(arm: str) -> str:
    return f"so101_{arm}"


def lerobot_cache_roots(arm: str) -> tuple[Path, ...]:
    if arm == "leader":
        return (
            LEROBOT_CACHE_ROOT / "teleoperators/so_leader",
            LEROBOT_CACHE_ROOT / "teleoperators/so101_leader",
        )
    return (
        LEROBOT_CACHE_ROOT / "robots/so_follower",
        LEROBOT_CACHE_ROOT / "robots/so101_follower",
    )


def load_calibration(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Calibration file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = set(SO101_JOINT_NAMES).difference(data)
    extra = set(data).difference(SO101_JOINT_NAMES)
    if missing or extra:
        raise ValueError(f"Calibration joint keys mismatch. missing={sorted(missing)} extra={sorted(extra)}")
    for joint_name in SO101_JOINT_NAMES:
        entry = data[joint_name]
        for field in ("id", "drive_mode", "homing_offset", "range_min", "range_max"):
            if field not in entry:
                raise ValueError(f"Calibration entry {joint_name} misses '{field}'.")
            int(entry[field])
        if int(entry["range_min"]) == int(entry["range_max"]):
            raise ValueError(f"Calibration range is empty for {joint_name}.")
    return data


def summarize_calibration(path: Path, data: dict[str, Any], *, arm: str) -> None:
    print(f"LWH_SO101_CALIBRATION_FILE arm={arm} path={path}", flush=True)
    for joint_name in SO101_JOINT_NAMES:
        entry = data[joint_name]
        print(
            "  "
            f"{joint_name}: id={entry['id']} drive_mode={entry['drive_mode']} "
            f"homing_offset={entry['homing_offset']} range=[{entry['range_min']}, {entry['range_max']}]",
            flush=True,
        )


def resolve_calibration_path(arm: str, path: str | None, calibration_id: str | None, output: Path) -> Path:
    """按项目运行时约定解析标定文件；不导入 IsaacLab 或 LeRobot。"""
    if path:
        return Path(path).expanduser()
    env_var = "LWH_SO101_LEADER_CALIBRATION" if arm == "leader" else "LWH_SO101_FOLLOWER_CALIBRATION"
    env_path = os.environ.get(env_var)
    if env_path:
        return Path(env_path).expanduser()
    if output.is_file():
        return output
    for root in lerobot_cache_roots(arm):
        candidate = root / f"{calibration_id or default_id(arm)}.json"
        if candidate.is_file():
            return candidate
    if arm == "leader" and DEFAULT_LEISAAC_LEADER_CACHE.is_file():
        return DEFAULT_LEISAAC_LEADER_CACHE
    return lerobot_cache_roots(arm)[0] / f"{calibration_id or default_id(arm)}.json"


def print_resolution(args: argparse.Namespace) -> None:
    resolved = resolve_calibration_path(args.arm, args.calibration, args.id, args.output)
    env_var = "LWH_SO101_LEADER_CALIBRATION" if args.arm == "leader" else "LWH_SO101_FOLLOWER_CALIBRATION"
    print(f"LWH_SO101_CALIBRATION_RESOLVED arm={args.arm} path={resolved}", flush=True)
    print("LWH_SO101_CALIBRATION_SEARCH_ORDER", flush=True)
    print("  1. --calibration", flush=True)
    print(f"  2. {env_var}", flush=True)
    print(f"  3. project configs: {args.output}", flush=True)
    for index, root in enumerate(lerobot_cache_roots(args.arm), start=4):
        print(f"  {index}. LeRobot cache: {root / ((args.id or default_id(args.arm)) + '.json')}", flush=True)
    if args.arm == "leader":
        print(f"  {4 + len(lerobot_cache_roots(args.arm))}. LeIsaac cache: {DEFAULT_LEISAAC_LEADER_CACHE}", flush=True)
    if not resolved.is_file():
        print(
            f"LWH_SO101_CALIBRATION_MISSING arm={args.arm} path={resolved} "
            "Run --calibrate in the LeRobot environment or --import_from an existing JSON.",
            flush=True,
        )
        return
    data = load_calibration(resolved)
    summarize_calibration(resolved, data, arm=args.arm)


def import_calibration(source: Path, output: Path, *, arm: str) -> None:
    data = load_calibration(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    print(f"LWH_SO101_CALIBRATION_IMPORTED arm={arm} source={source} output={output}", flush=True)


def make_lerobot_device(args: argparse.Namespace):
    try:
        if args.arm == "leader":
            from lerobot.teleoperators.so_leader import SO101LeaderConfig
            from lerobot.teleoperators.utils import make_teleoperator_from_config

            cfg = SO101LeaderConfig(
                port=args.port,
                id=args.id or default_id(args.arm),
                calibration_dir=args.output.parent,
            )
            return make_teleoperator_from_config(cfg)

        from lerobot.robots.so_follower import SO101FollowerConfig
        from lerobot.robots.utils import make_robot_from_config

        cfg = SO101FollowerConfig(
            port=args.port,
            id=args.id or default_id(args.arm),
            calibration_dir=args.output.parent,
            cameras={},
        )
        return make_robot_from_config(cfg)
    except ImportError as exc:
        raise RuntimeError(
            "LeRobot is not importable. Run calibration in the LeRobot environment, for example "
            "`conda activate lerobot05`."
        ) from exc


def run_lerobot_calibration(args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    device = make_lerobot_device(args)
    print(
        f"LWH_SO101_CALIBRATION_START arm={args.arm} port={args.port} "
        f"id={args.id or default_id(args.arm)} output={args.output}",
        flush=True,
    )
    if args.arm == "follower":
        print(
            "注意：follower 标定会连接真实 follower 手臂并写入电机标定。仿真遥操作/录制默认不会调用它。",
            flush=True,
        )
    else:
        print("Leader 标定只连接真实 leader 输入臂，不控制真实 follower。", flush=True)
    device.connect(calibrate=False)
    try:
        device.calibrate()
    finally:
        device.disconnect()

    saved = args.output.parent / f"{args.id or default_id(args.arm)}.json"
    if saved != args.output:
        shutil.copy2(saved, args.output)
    data = load_calibration(args.output)
    summarize_calibration(args.output, data, arm=args.arm)
    print(f"LWH_SO101_CALIBRATION_DONE arm={args.arm} output={args.output}", flush=True)


def main() -> None:
    args = parse_args()
    if args.inspect:
        print_resolution(args)
    if args.import_from is not None:
        import_calibration(args.import_from, args.output, arm=args.arm)
    if args.calibrate:
        run_lerobot_calibration(args)


if __name__ == "__main__":
    main()
