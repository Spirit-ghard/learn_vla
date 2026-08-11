#!/usr/bin/env python3
"""Launch the Stage-4 HDF5 replay validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DATASET_FILE = PROJECT_ROOT / "datasets/hdf5/lwh_so101_table_leader.hdf5"


def main() -> None:
    # 该验证只回放 HDF5 到仿真环境，不访问真实 leader/follower 设备。
    os.environ["LWH_REPLAY_HDF5_VALIDATION"] = "1"
    replay_script = SCRIPT_DIR / "replay_hdf5.py"
    args = [
        sys.executable,
        str(replay_script),
        "--dataset_file",
        str(DEFAULT_DATASET_FILE),
        "--autoplay",
        "--max_frames",
        "90",
        "--verify",
        *sys.argv[1:],
    ]
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
