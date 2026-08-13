#!/usr/bin/env python3
"""Launch the Stage-3 HDF5 recorder validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts/stage3/record_validation.hdf5"


def main() -> None:
    # 该验证只向 Isaac GUI 注入 Carb 键盘事件，不访问真实 leader/follower 设备。
    os.environ["LWH_RECORD_HDF5_VALIDATION"] = "1"
    teleop_script = SCRIPT_DIR / "teleop.py"
    args = [
        sys.executable,
        str(teleop_script),
        "--record",
        "--output",
        str(DEFAULT_OUTPUT),
        "--overwrite",
        *sys.argv[1:],
    ]
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
