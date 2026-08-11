#!/usr/bin/env python3
"""Inspect or calibrate the SO101 Leader calibration used by this project."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "configs/so101_leader_calibration.json"
DEFAULT_LEISAAC_CACHE = (
    Path.home() / ".local/share/ov/pkg/leisaac/source/leisaac/leisaac/devices/lerobot/.cache/so101_leader.json"
)
DEFAULT_LEROBOT_CACHE_ROOTS = (
    Path.home() / ".cache/huggingface/lerobot/calibration/teleoperators/so_leader",
    Path.home() / ".cache/huggingface/lerobot/calibration/teleoperators/so101_leader",
)
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
        description=(
            "Inspect the currently resolved SO101 Leader calibration, import an existing calibration, "
            "or run LeRobot's official SO101 Leader calibration workflow."
        )
    )
    parser.add_argument("--port", default="/dev/ttyACM0", help="SO101 Leader serial port for --calibrate.")
    parser.add_argument(
        "--leader_id",
        default=None,
        help="LeRobot leader id used to resolve cache paths and as the calibration id when --calibrate is used.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Project calibration JSON to write or inspect.",
    )
    parser.add_argument(
        "--leader_calibration",
        default=None,
        help="Explicit calibration path to test with the same resolver used by teleop/record.",
    )
    parser.add_argument("--inspect", action="store_true", help="Print resolved calibration source and summary.")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run LeRobot SO101 Leader calibration and save the result to --output.",
    )
    parser.add_argument(
        "--import_from",
        type=Path,
        default=None,
        help="Copy an existing calibration JSON into --output after schema validation.",
    )
    args = parser.parse_args()
    args.output = args.output.expanduser().resolve()
    if args.import_from is not None:
        args.import_from = args.import_from.expanduser().resolve()
    if not (args.inspect or args.calibrate or args.import_from):
        args.inspect = True
    return args


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


def summarize_calibration(path: Path, data: dict[str, Any]) -> None:
    print(f"LWH_SO101_CALIBRATION_FILE {path}", flush=True)
    for joint_name in SO101_JOINT_NAMES:
        entry = data[joint_name]
        print(
            "  "
            f"{joint_name}: id={entry['id']} drive_mode={entry['drive_mode']} "
            f"homing_offset={entry['homing_offset']} range=[{entry['range_min']}, {entry['range_max']}]",
            flush=True,
        )


def print_resolution(args: argparse.Namespace) -> None:
    resolved = resolve_calibration_path(args.leader_calibration, args.leader_id)
    print(f"LWH_SO101_CALIBRATION_RESOLVED {resolved}", flush=True)
    print("LWH_SO101_CALIBRATION_SEARCH_ORDER", flush=True)
    print("  1. --leader_calibration", flush=True)
    print("  2. LWH_SO101_LEADER_CALIBRATION", flush=True)
    print(f"  3. project configs: {DEFAULT_OUTPUT}", flush=True)
    for index, root in enumerate(DEFAULT_LEROBOT_CACHE_ROOTS, start=4):
        print(f"  {index}. LeRobot cache: {root / ((args.leader_id or 'so101_leader') + '.json')}", flush=True)
    print(f"  {4 + len(DEFAULT_LEROBOT_CACHE_ROOTS)}. LeIsaac cache: {DEFAULT_LEISAAC_CACHE}", flush=True)
    data = load_calibration(resolved)
    summarize_calibration(resolved, data)


def resolve_calibration_path(path: str | None, leader_id: str | None = None) -> Path:
    """按仿真入口相同优先级查找 leader 标定文件，不导入 IsaacLab/LeRobot。"""
    if path:
        return Path(path).expanduser()
    env_path = os.environ.get("LWH_SO101_LEADER_CALIBRATION")
    if env_path:
        return Path(env_path).expanduser()
    if DEFAULT_OUTPUT.is_file():
        return DEFAULT_OUTPUT
    if leader_id:
        for root in DEFAULT_LEROBOT_CACHE_ROOTS:
            candidate = root / f"{leader_id}.json"
            if candidate.is_file():
                return candidate
    if DEFAULT_LEISAAC_CACHE.is_file():
        return DEFAULT_LEISAAC_CACHE
    return DEFAULT_LEROBOT_CACHE_ROOTS[0] / f"{leader_id or 'so101_leader'}.json"


def import_calibration(source: Path, output: Path) -> None:
    data = load_calibration(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    print(f"LWH_SO101_CALIBRATION_IMPORTED source={source} output={output}", flush=True)


def run_lerobot_calibration(args: argparse.Namespace) -> None:
    try:
        from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    except ImportError as exc:
        raise RuntimeError(
            "LeRobot is not importable. Run calibration in the LeRobot environment, for example "
            "`conda activate lerobot05`."
        ) from exc

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    calibration_id = args.leader_id or output.stem
    cfg = SO101LeaderConfig(port=args.port, id=calibration_id, calibration_dir=output.parent)
    device = SO101Leader(cfg)
    print(
        f"LWH_SO101_CALIBRATION_START port={args.port} id={calibration_id} output={output} "
        "target=leader_only",
        flush=True,
    )
    print(
        "This calibrates the SO101 Leader input arm only. It does not connect to or control a follower robot.",
        flush=True,
    )
    device.connect(calibrate=False)
    try:
        device.calibrate()
    finally:
        device.disconnect()

    saved = output.parent / f"{calibration_id}.json"
    if saved != output:
        shutil.copy2(saved, output)
    data = load_calibration(output)
    summarize_calibration(output, data)
    print(f"LWH_SO101_CALIBRATION_DONE output={output}", flush=True)


def main() -> None:
    args = parse_args()
    if args.inspect:
        print_resolution(args)
    if args.import_from is not None:
        import_calibration(args.import_from, args.output)
    if args.calibrate:
        run_lerobot_calibration(args)


if __name__ == "__main__":
    main()
