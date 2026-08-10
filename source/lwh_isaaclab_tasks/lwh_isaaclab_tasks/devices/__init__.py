"""Teleoperation devices implemented inside the LWH IsaacLab package.

设备类按需导入，避免只测试串口 leader 时提前加载 Isaac GUI 的 carb/omni 模块。
"""

__all__ = ["SO101Keyboard", "SO101LeaderArm", "resolve_leader_calibration_path"]


def __getattr__(name: str):
    if name == "SO101Keyboard":
        from .so101_keyboard import SO101Keyboard

        return SO101Keyboard
    if name in ("SO101LeaderArm", "resolve_leader_calibration_path"):
        from .so101_leader import SO101LeaderArm, resolve_leader_calibration_path

        return {"SO101LeaderArm": SO101LeaderArm, "resolve_leader_calibration_path": resolve_leader_calibration_path}[
            name
        ]
    raise AttributeError(name)
