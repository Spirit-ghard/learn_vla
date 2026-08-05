# 版本兼容记录

检查日期：2026-08-05。

## 仿真环境

| 组件 | 版本或提交 |
| --- | --- |
| Isaac Sim | 4.5.0-rc.36, build `f59b3005` |
| IsaacLab | v2.1.1, `90b79bb2d44feb8d833f260f2bf37da3487180ba` |
| IsaacLab Python package | 0.41.3 |
| IsaacLab Tasks | 0.10.36 |
| LeIsaac | 0.4.0, `24d3bcd3f1e4585740fc79921782c41617237812` |
| Python | 3.10.20 |
| PyTorch | 2.5.1+cu124 |
| Gymnasium | 1.2.0 |
| NumPy | 1.26.4 |
| GPU | NVIDIA GeForce RTX 3060 Laptop, 6 GiB |
| NVIDIA driver | 535.247.01 |

LeIsaac 官方兼容矩阵将 Isaac Sim 4.5 与 IsaacLab v2.1.1、Python 3.10、
PyTorch 2.5.1 配套。本项目按该组合锁定，不使用现有被修改的 IsaacLab/LeIsaac
工作树。

### LeIsaac 0.4.0 终止管理器兼容处理

LeIsaac 提交 `d1859500b13c1cbc48762792a67908d1c9e15d87` 引入的临时补丁按二维
张量访问 `TerminationManager._term_dones`。IsaacLab v2.1.1 中该成员是按终止
项名称索引的字典，因此原样组合会在第一次 `env.step()` 时产生
`TypeError: unhashable type: 'slice'`。

本项目在包入口处保留并恢复 IsaacLab v2.1.1 的官方 `compute()`，且只对
`isaaclab==0.41.3` 生效。LeIsaac 源码和 IsaacLab 源码均不修改；升级依赖时应
删除或重新评估这一适配。

官方参考：

- https://lightwheelai.github.io/leisaac/docs/getting_started/installation/
- https://github.com/LightwheelAI/leisaac/blob/main/source/leisaac/leisaac/tasks/template/single_arm_env_cfg.py
- https://isaac-sim.github.io/IsaacLab/main/source/tutorials/03_envs/create_manager_rl_env.html

## SO101 契约

仿真关节顺序与 `/home/a/lwh_code/soarm_ros` 一致：

```text
shoulder_pan
shoulder_lift
elbow_flex
wrist_flex
wrist_roll
gripper
```

仿真使用 LeIsaac 的 `so101_follower.usd` 作为模型和关节限位真值。
ROS 工程只用于名称交叉检查；本项目不导入 ROS，不打开串口，不控制真实机器人。
