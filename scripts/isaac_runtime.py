"""Pure-Python bootstrap for the pinned Isaac Sim runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS_ROOT = PROJECT_ROOT / "source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets"
RUNTIME_MARKER = "LWH_ISAAC_RUNTIME_READY"
SIM_ASSETS_ENV = "LWH_SIM_ASSETS_ROOT"
LEGACY_ASSETS_ENV = "LEISAAC_ASSETS_ROOT"
ISAAC_PYTHON_ENV = "LWH_ISAAC_PYTHON"
ISAAC_SIM_ROOT_ENV = "LWH_ISAAC_SIM_ROOT"


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


def _resolve_target_python() -> Path:
    """优先使用当前已激活 Python；旧系统 Python 下尝试常见 Isaac conda 环境。"""
    configured_python = os.environ.get(ISAAC_PYTHON_ENV)
    if configured_python:
        return Path(configured_python).expanduser().resolve()
    if sys.version_info >= (3, 10):
        return Path(sys.executable).resolve()

    candidates = [
        Path.home() / "anaconda3/envs/lwh_isaac/bin/python",
        Path.home() / "miniconda3/envs/lwh_isaac/bin/python",
    ]
    python310 = shutil.which("python3.10")
    if python310:
        candidates.append(Path(python310))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return Path(sys.executable).resolve()


def _resolve_isaac_root() -> Path:
    """按可搬迁优先级查找 Isaac Sim 根目录。"""
    candidates: list[Path] = []
    for env_name in (ISAAC_SIM_ROOT_ENV, "ISAAC_PATH"):
        configured = os.environ.get(env_name)
        if configured:
            candidates.append(Path(configured).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT / "dependencies/IsaacLab/_isaac_sim",
            Path.home() / ".local/share/ov/pkg/isaac-sim-4.5.0",
            Path.home() / ".local/share/ov/pkg/isaac-sim",
        ]
    )

    for candidate in candidates:
        root = candidate.resolve()
        if (root / "kit").exists() and (root / "apps").exists():
            return root

    searched = "\n".join(f"- {candidate}" for candidate in candidates)
    raise RuntimeError(
        "Isaac Sim root was not found. Set LWH_ISAAC_SIM_ROOT or ISAAC_PATH to the Isaac Sim install path.\n"
        f"Searched:\n{searched}"
    )


def _build_runtime_environment() -> tuple[Path, dict[str, str]]:
    isaac_root = _resolve_isaac_root()

    target_python = _resolve_target_python()
    if not target_python.is_file():
        raise RuntimeError(f"Isaac Python interpreter does not exist: {target_python}")

    python_paths = [
        PROJECT_ROOT / "source/lwh_isaaclab_tasks",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab_tasks",
        PROJECT_ROOT / "dependencies/IsaacLab/source/isaaclab_assets",
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
    env[SIM_ASSETS_ENV] = os.environ.get(
        SIM_ASSETS_ENV,
        os.environ.get(LEGACY_ASSETS_ENV, str(DEFAULT_ASSETS_ROOT)),
    )
    env[RUNTIME_MARKER] = "1"
    env.pop("LWH_VALIDATION_STATUS_FILE", None)
    return target_python, env


def _validate_assets(env: dict[str, str]) -> None:
    assets_root = Path(env[SIM_ASSETS_ENV])
    robot_asset = assets_root / "robots/so101_follower.usd"
    if not robot_asset.is_file():
        raise RuntimeError(f"SO101 simulation asset is missing under {assets_root}")
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
            print("Isaac validation did not produce a passed status.", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
    finally:
        status_path.unlink(missing_ok=True)
