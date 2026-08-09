# LWH Robot Learning

当前分支只包含第一阶段：基于 IsaacLab 的 SO101 桌面仿真场景。

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

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
```

打开 Isaac Sim GUI 并持续运行场景：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

也可以省略参数，默认就是同一个任务和单环境：

```bash
python3 scripts/run_env.py
```

退出方式：

```text
关闭 Isaac Sim 窗口，或在终端按 Ctrl+C。
```

运行入口会自动切换到固定的 IsaacLab Python 环境，并清理继承自 ROS 或真实机器人工程的
Python/动态库路径，保证这里只运行仿真。
