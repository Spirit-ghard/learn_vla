"""Pure-Python bootstrap for the pinned Isaac Sim runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISAAC_PYTHON = Path("/home/a/anaconda3/envs/lwh_isaac/bin/python")
DEFAULT_ASSETS_ROOT = Path("/home/a/.local/share/ov/pkg/leisaac/assets")
RUNTIME_MARKER = "LWH_ISAAC_RUNTIME_READY"


def _without_robot_paths(value: str | None) -> list[str]:
    """移除宿主 shell 注入的 ROS/真实机器人路径，保持仿真进程隔离。"""
    if not value:
        return []
    return [
        entry
        for entry in value.split(os.pathsep)
        if entry and "soarm_ros" not in entry and not entry.startswith("/opt/ros/")
    ]


def _existing_paths(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.exists()]


def _build_runtime_environment() -> tuple[Path, dict[str, str]]:
    isaac_link = PROJECT_ROOT / "dependencies/IsaacLab/_isaac_sim"
    if not isaac_link.exists():
        raise RuntimeError(f"Isaac Sim link does not exist: {isaac_link}")
    isaac_root = isaac_link.resolve()

    target_python = Path(os.environ.get("LWH_ISAAC_PYTHON", str(DEFAULT_ISAAC_PYTHON))).resolve()
    if not target_python.is_file():
        raise RuntimeError(f"Isaac Python interpreter does not exist: {target_python}")

    python_paths = [
        PROJECT_ROOT / "source/lwh_isaaclab_tasks",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab_tasks",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab_assets",
        PROJECT_ROOT / "dependencies/leisaac/source/leisaac",
        isaac_root / "python_packages",
        isaac_root / "exts/isaacsim.simulation_app",
        isaac_root / "extsDeprecated/omni.isaac.kit",
        isaac_root / "kit/kernel/py",
        isaac_root / "kit/plugins/bindings-python",
        isaac_root / "exts/isaacsim.robot_motion.lula/pip_prebundle",
        isaac_root / "exts/isaacsim.asset.exporter.urdf/pip_prebundle",
        isaac_root / "exts/omni.isaac.core_archive/pip_prebundle",
        isaac_root / "exts/omni.isaac.ml_archive/pip_prebundle",
        isaac_root / "exts/omni.pip.compute/pip_prebundle",
        isaac_root / "exts/omni.pip.cloud/pip_prebundle",
    ]
    python_paths.extend(sorted(isaac_root.glob("extscache/omni.kit.pip_archive-*/pip_prebundle")))

    library_paths = [
        isaac_root,
        isaac_root / "exts/omni.usd.schema.isaac/plugins/IsaacSensorSchema/lib",
        isaac_root / "exts/omni.usd.schema.isaac/plugins/RangeSensorSchema/lib",
        isaac_root / "exts/isaacsim.robot_motion.lula/pip_prebundle",
        isaac_root / "exts/isaacsim.asset.exporter.urdf/pip_prebundle",
        isaac_root / "kit",
        isaac_root / "kit/kernel/plugins",
        isaac_root / "kit/libs/iray",
        isaac_root / "kit/plugins",
        isaac_root / "kit/plugins/bindings-python",
        isaac_root / "kit/plugins/carb_gfx",
        isaac_root / "kit/plugins/rtx",
        isaac_root / "kit/plugins/gpu.foundation",
    ]

    env = os.environ.copy()
    env["CARB_APP_PATH"] = str(isaac_root / "kit")
    env["EXP_PATH"] = str(isaac_root / "apps")
    env["ISAAC_PATH"] = str(isaac_root)
    env["PYTHONPATH"] = os.pathsep.join(
        _existing_paths(python_paths) + _without_robot_paths(os.environ.get("PYTHONPATH"))
    )
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        _existing_paths(library_paths) + _without_robot_paths(os.environ.get("LD_LIBRARY_PATH"))
    )
    env["PATH"] = os.pathsep.join([str(target_python.parent), os.environ.get("PATH", "")])
    env["CONDA_PREFIX"] = str(target_python.parent.parent)
    env["CONDA_DEFAULT_ENV"] = target_python.parent.parent.name
    env["LEISAAC_ASSETS_ROOT"] = os.environ.get("LEISAAC_ASSETS_ROOT", str(DEFAULT_ASSETS_ROOT))
    env[RUNTIME_MARKER] = "1"
    env.pop("LWH_VALIDATION_STATUS_FILE", None)
    return target_python, env


def _validate_assets(env: dict[str, str]) -> None:
    assets_root = Path(env["LEISAAC_ASSETS_ROOT"])
    robot_asset = assets_root / "robots/so101_follower.usd"
    scene_asset = assets_root / "scenes/table_with_cube/scene.usd"
    if not robot_asset.is_file() or not scene_asset.is_file():
        raise RuntimeError(f"LeIsaac assets are missing under {assets_root}")
    if robot_asset.stat().st_size < 1_000_000:
        raise RuntimeError(f"SO101 asset is a Git LFS pointer instead of a downloaded USD: {robot_asset}")


def ensure_isaac_runtime(*, supervise_validation: bool = False) -> None:
    """配置运行环境并用固定解释器重新执行当前 Python 入口。"""
    target_python, env = _build_runtime_environment()
    _validate_assets(env)

    runtime_is_ready = (
        os.environ.get(RUNTIME_MARKER) == "1" and Path(sys.executable).resolve() == target_python
    )
    if runtime_is_ready:
        return

    script_path = Path(sys.argv[0]).resolve()
    command = [str(target_python), str(script_path), *sys.argv[1:]]
    if not supervise_validation:
        os.execve(target_python, command, env)

    status_fd, status_name = tempfile.mkstemp(prefix="lwh-validation-", suffix=".status")
    os.close(status_fd)
    status_path = Path(status_name)
    env["LWH_VALIDATION_STATUS_FILE"] = str(status_path)
    try:
        completed = subprocess.run(command, env=env, check=False)
        status = status_path.read_text(encoding="utf-8").strip()
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)
        if status != "passed":
            print("Stage-1 validation did not produce a passed status.", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
    finally:
        status_path.unlink(missing_ok=True)
