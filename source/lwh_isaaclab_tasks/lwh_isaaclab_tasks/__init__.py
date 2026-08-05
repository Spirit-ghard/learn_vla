"""LWH IsaacLab task package."""

from importlib.metadata import version

from isaaclab.managers import TerminationManager


# LeIsaac 0.4.0 会在导入时安装面向新版 IsaacLab 的临时补丁。先保留 v2.1.1
# 官方实现，待 LeIsaac 任务组件加载完成后按版本恢复，避免修改第三方源码。
_ISAACLAB_TERMINATION_COMPUTE = TerminationManager.compute

# 先触发 LeIsaac 的一次性包初始化，确保后续配置类按字符串加载时不会再次打补丁。
import leisaac as _leisaac  # noqa: F401,E402

# 导入任务模块时完成 Gym 环境注册，运行入口只需导入本包一次。
from .tasks import *  # noqa: E402,F401,F403

if version("isaaclab") == "0.41.3" and TerminationManager.compute is not _ISAACLAB_TERMINATION_COMPUTE:
    TerminationManager.compute = _ISAACLAB_TERMINATION_COMPUTE
