"""Simulation asset configs used by LWH IsaacLab tasks.

常量可以在不启动 Isaac/Carb 的普通 Python 进程中导入；仿真资产配置按需加载。
"""

__all__ = [
    "banana_cfg",
    "banana_usd_path",
    "SO101_FOLLOWER_CFG",
    "SO101_FOLLOWER_JOINT_LIMITS_DEG",
    "SO101_JOINT_NAMES",
    "SO101_LEADER_MOTOR_LIMITS",
    "SO101_SIM_ASSET_PATH",
]


def __getattr__(name: str):
    if name in ("SO101_FOLLOWER_JOINT_LIMITS_DEG", "SO101_JOINT_NAMES", "SO101_LEADER_MOTOR_LIMITS"):
        from .so101_constants import SO101_FOLLOWER_JOINT_LIMITS_DEG, SO101_JOINT_NAMES, SO101_LEADER_MOTOR_LIMITS

        return {
            "SO101_FOLLOWER_JOINT_LIMITS_DEG": SO101_FOLLOWER_JOINT_LIMITS_DEG,
            "SO101_JOINT_NAMES": SO101_JOINT_NAMES,
            "SO101_LEADER_MOTOR_LIMITS": SO101_LEADER_MOTOR_LIMITS,
        }[name]
    if name in ("SO101_FOLLOWER_CFG", "SO101_SIM_ASSET_PATH"):
        from .so101 import SO101_FOLLOWER_CFG, SO101_SIM_ASSET_PATH

        return {"SO101_FOLLOWER_CFG": SO101_FOLLOWER_CFG, "SO101_SIM_ASSET_PATH": SO101_SIM_ASSET_PATH}[name]
    if name in ("banana_cfg", "banana_usd_path"):
        from .banana import banana_cfg, banana_usd_path

        return {"banana_cfg": banana_cfg, "banana_usd_path": banana_usd_path}[name]
    raise AttributeError(name)
