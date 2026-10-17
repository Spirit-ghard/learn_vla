"""项目包入口；导入 tasks 会执行 gym.register，让脚本可以按 task id 创建环境。"""

# 导入任务模块时完成 Gym 环境注册，运行入口只需导入本包一次。
from .tasks import *  # noqa: F401,F403
