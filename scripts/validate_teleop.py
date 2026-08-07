#!/usr/bin/env python3
"""Launch the Stage-2 Carb keyboard callback validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> None:
    # 该开关只启用仿真窗口内的 Carb 键盘事件序列，不连接任何真实设备。
    os.environ["LWH_TELEOP_INPUT_VALIDATION"] = "1"
    teleop_script = SCRIPT_DIR / "teleop.py"
    os.execv(sys.executable, [sys.executable, str(teleop_script), *sys.argv[1:]])


if __name__ == "__main__":
    main()
