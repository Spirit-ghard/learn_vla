# LWH Robot Learning

当前分支是 `stage_2_2`：在第二阶段键盘遥操作基础上，提供单相机/双相机可选运行。

策略：

- 渲染和运行参数继续对齐 LeIsaac `LeIsaac-SO101-LiftCube-v0`。
- `front` 和 `wrist` 相机位置使用本项目之前自定义的位姿。
- 默认不强制 `quality + FXAA`，先使用 IsaacLab/LeIsaac 默认渲染路径。

项目只运行 IsaacLab 仿真，不连接真实机器人，不启动 ROS，不访问串口。

## 使用方式

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_2_2
```

启动键盘遥操作，默认双相机：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

只启用前视相机：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode front
```

显式启用双相机：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode dual
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

## 当前配置

```text
front camera: 640 x 480, 30 FPS, 本项目原 front 位姿
wrist camera: 可选，640 x 480, 30 FPS, 本项目原 wrist 位姿
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
  --camera_mode dual \
  --quality
```

如果双相机默认配置开始卡顿，先用 `--camera_mode front` 确认遥操作手感，再决定录制阶段
是否需要双相机。

## 调参顺序

优先从最接近 LeIsaac 的配置开始：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

如果单相机流畅，再切回双相机：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

如果双相机仍卡顿，但你需要保留双相机数据，可以先降低窗口刷新压力：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode dual \
  --teleop_render_interval 2
```

`--quality` 只用于确认画质问题，不建议作为默认录制配置；它会切到更重的渲染 preset。
当前阶段建议数据底线是每路相机 `640 x 480 @ 30 FPS`、动作控制 `60 Hz`、只记录 RGB 图像和关节状态。
