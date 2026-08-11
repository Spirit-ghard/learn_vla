# 可搬迁性检查

目标：仓库目录移动到另一台已经安装好 Isaac Sim / IsaacLab 环境的机器后，不再依赖本机
LeIsaac 安装目录中的项目资产。

## 已内置到项目的文件

| 文件 | 用途 |
| --- | --- |
| `source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/robots/so101_follower.usd` | Stage 1/2 SO101 Follower 仿真模型 |
| `configs/so101_leader_calibration.json` | 当前 SO101 Leader 校准默认文件，可用参数覆盖 |

## 运行时默认查找

- SO101 仿真资产默认从项目包目录读取。
- `LWH_SIM_ASSETS_ROOT` 仍可覆盖资产根目录，用于临时切换其它资产。
- `LEISAAC_ASSETS_ROOT` 只作为历史兼容环境变量，不再是默认来源。
- Isaac Sim 根目录按 `LWH_ISAAC_SIM_ROOT`、`ISAAC_PATH`、项目内 `dependencies/IsaacLab/_isaac_sim`、常见 Omniverse 安装目录依次查找。
- Python 默认使用当前启动脚本的解释器；如果当前 Python 低于 3.10，会尝试常见的 `lwh_isaac` conda 环境；需要跨环境重执行时设置 `LWH_ISAAC_PYTHON`。
- SO101 Leader 校准按 `--leader_calibration`、`LWH_SO101_LEADER_CALIBRATION`、项目 `configs/so101_leader_calibration.json`、LeRobot cache、LeIsaac cache 依次查找。

## 搬迁后的要求

目标机器需要已经安装：

- Isaac Sim 4.5 兼容环境。
- IsaacLab v2.1.1 兼容源码或 Python 包。
- 本项目 Python 依赖。
- 如果使用 `--teleop_device so101leader`，还需要 `scservo_sdk`、串口权限和对应 leader 校准。

如果 Isaac Sim 不在常见位置，运行前设置：

```text
LWH_ISAAC_SIM_ROOT=/path/to/isaac-sim
```

如果当前 `python3` 不是 Isaac 环境的 Python，运行前设置：

```text
LWH_ISAAC_PYTHON=/path/to/isaac/python
```

## 检查结论

- Stage 1 任务不再依赖 `/home/a/.local/share/ov/pkg/leisaac/assets`。
- Stage 2 键盘遥操作不访问串口、不依赖外部项目资产。
- Stage 2.3 leader 模式只在显式选择时访问串口，并且默认校准已放入项目 `configs/`。
- `dependencies/leisaac` 只作为源码参考，不进入运行时 `PYTHONPATH`。
