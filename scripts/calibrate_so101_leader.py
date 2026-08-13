#!/usr/bin/env python3
"""Compatibility entry for SO101 leader calibration."""

from __future__ import annotations

import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> None:
    calibrate_script = SCRIPT_DIR / "calibrate_so101.py"
    os.execv(sys.executable, [sys.executable, str(calibrate_script), "--arm", "leader", *sys.argv[1:]])


if __name__ == "__main__":
    main()
