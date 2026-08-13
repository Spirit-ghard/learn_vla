# HZ Robot Learning
## Phase 1 ：基于 IsaacLab 的 SO101 桌面仿真场景。
场景内容：

- SO101 Follower
- 桌面、几何篮子和黄色香蕉
- 地面和灯光
- 前视相机和腕部相机
- 关节状态、末端状态、相机图像和上一帧动作观测
- IsaacLab `ManagerBasedRLEnv` 任务注册：`Lwh-SO101-Table-v0`

本阶段只打开并持续运行仿真环境，不包含遥操作、录制、回放、训练或远程推理入口。
代码不连接真实机器人，不启动 ROS，不访问串口。

## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_1
```

启动场景：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

退出方式：关闭 Isaac Sim 窗口，或在终端按 `Ctrl+C`。

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 同时创建的仿真环境数量；当前场景调试建议保持 1。 |
| `--device` | IsaacLab 默认 | 仿真设备，例如 `cuda` 或 `cpu`。 |
| `--headless` | `False` | 无 GUI 运行，通常只用于内部验证。 |

运行入口会自动切换到 IsaacLab/Isaac Sim 运行环境，并清理继承自 ROS 或真实机器人工程的
Python/动态库路径，保证这里只运行仿真。

## 标定工具

本阶段默认不访问串口，但仓库从 stage_1 起提供 SO101 标定辅助脚本，方便后续 leader/follower
接入时使用同一套 LeRobot 标定文件格式。

```bash
python3 scripts/calibrate_so101.py --arm leader --inspect
python3 scripts/calibrate_so101.py --arm follower --inspect
```

如需重新标定，必须在 LeRobot 环境中显式运行 `--calibrate`；只有
`--arm follower --calibrate` 会连接真实 follower。
