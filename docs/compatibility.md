# 版本兼容记录

检查日期：2026-08-08。

## 仿真环境

| 组件 | 版本或提交 |
| --- | --- |
| Isaac Sim | 4.5.0-rc.36, build `f59b3005` |
| IsaacLab | v2.1.1, `90b79bb2d44feb8d833f260f2bf37da3487180ba` |
| IsaacLab Python package | 0.41.3 |
| IsaacLab Tasks | 0.10.36 |
| LeIsaac | 0.4.0, `24d3bcd3f1e4585740fc79921782c41617237812` |
| LeRobot local source | 0.5.1, `/home/a/lerobot_05`, `2ea20910` |
| Python | 3.10.20 |
| PyTorch | 2.5.1+cu124 |
| Gymnasium | 1.2.0 |
| NumPy | 1.26.4 |
| GPU | NVIDIA GeForce RTX 3060 Laptop, 6 GiB |
| NVIDIA driver | 535.247.01 |

LeIsaac 官方兼容矩阵将 Isaac Sim 4.5 与 IsaacLab v2.1.1、Python 3.10、
PyTorch 2.5.1 配套。本项目按该组合锁定。LeIsaac 只作为源码参考和 SO101 USD
资产来源，项目运行时不导入 `leisaac` Python 包。

本机 LeRobot 源码 `/home/a/lerobot_05` 的 `pyproject.toml` 标记版本为 `0.5.1`，
并要求 Python `>=3.12`。Isaac Sim 4.5 / IsaacLab 当前运行环境是 Python `3.10.20`，
因此 stage2_3 不把 LeRobot 0.5.1 直接导入 Isaac 进程；真实 SO101 Leader
读取逻辑按 LeRobot/LeIsaac 源码格式用 `scservo_sdk` 重写最小串口 reader。

## Python-only 运行入口

所有项目入口先调用 `scripts/isaac_runtime.py`。该模块使用纯 Python 完成以下工作：

- 从系统 `python3` 自动重新执行到 `lwh_isaac` Python 3.10。
- 配置 Isaac Sim 的应用、扩展、Python 和动态库路径。
- 校验 SO101 USD 已完整下载。
- 从继承环境中移除 ROS 和 `soarm_ros` 路径，防止仿真入口加载真实机器人环境。
- 监督验证子进程，保留可靠的成功/失败退出码。

项目不再包含 shell 运行入口，后续 teleop、record、replay 和 policy client/server
也应直接使用这一 Python bootstrap。

### LeIsaac 源码参考范围

本项目已经移除 LeIsaac Python 运行时依赖：`pyproject.toml` 不再声明 `leisaac`，
`scripts/isaac_runtime.py` 不再把 `dependencies/leisaac/source/leisaac` 放入
`PYTHONPATH`，`lwh_isaaclab_tasks` 包初始化也不再导入 `leisaac`。因此 LeIsaac
0.4.0 的 `TerminationManager` 临时补丁不会进入本项目进程。

仍然保留的 LeIsaac 关联只有两类：第一，读取本地源码作为任务组织和键盘映射参考；
第二，默认从 `/home/a/.local/share/ov/pkg/leisaac/assets` 读取
`robots/so101_follower.usd`，因为 IsaacLab 官方资产库不包含 SO101 Follower。

官方参考：

- https://lightwheelai.github.io/leisaac/docs/getting_started/installation/
- https://github.com/LightwheelAI/leisaac/blob/main/source/leisaac/leisaac/tasks/template/single_arm_env_cfg.py
- https://isaac-sim.github.io/IsaacLab/main/source/tutorials/03_envs/create_manager_rl_env.html

## SO101 契约

仿真关节顺序与 `/home/a/lwh_code/soarm_ros` 和 LeIsaac SO101 配置一致：

```text
shoulder_pan
shoulder_lift
elbow_flex
wrist_flex
wrist_roll
gripper
```

仿真使用本机资产目录中的 `so101_follower.usd` 作为模型和关节限位真值。
ROS 工程只用于名称交叉检查；本项目不导入 ROS，不控制真实 follower。
stage2_3 只有在 `--teleop_device so101leader` 时打开 leader 串口读取位置。
