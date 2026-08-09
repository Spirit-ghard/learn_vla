# LWH Robot Learning

当前分支包含第一阶段场景和第二阶段键盘遥操作。第二阶段先对齐 LeIsaac
`LeIsaac-SO101-LiftCube-v0` 的轻量运行方式：单前视相机、`640x480`、`30 FPS`、
`60 Hz` 控制循环。

项目只运行 IsaacLab 仿真，不连接真实机器人，不启动 ROS，不访问串口。

## 使用方式

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
```

打开场景持续运行：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

启动键盘遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

按键：

```text
B 开始控制
W/S 前后
A/D 左右
Q/E 上下
I/K/J/L 旋转
U/O 夹爪
R 失败并重置
N 成功并重置
Ctrl+C 或关闭窗口退出
```

## LeIsaac 对齐配置

默认配置：

```text
front camera: 640 x 480, 30 FPS
wrist camera: disabled
control loop: 60 Hz
sim dt: 1 / 60 s
render_interval: 1
render preset: IsaacLab default
anti-aliasing: IsaacLab default
```

如果默认画面不够清楚，再启用 LeIsaac 同款质量开关：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --quality
```

如果要手动试参数：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --teleop_render_interval 1 \
  --teleop_antialiasing_mode FXAA \
  --teleop_rendering_mode quality
```

先以默认配置为准。默认模式和 LeIsaac LiftCube 更接近，负载比之前双相机模式低。
