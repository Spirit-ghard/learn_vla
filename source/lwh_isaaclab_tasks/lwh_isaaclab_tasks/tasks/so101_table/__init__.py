"""Gym 注册点：把稳定 task id 绑定到环境和本任务配置类。"""

import gymnasium as gym


gym.register(
    id="Lwh-SO101-Table-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{__name__}.so101_table_env_cfg:LwhSO101TableEnvCfg",
    },
)

