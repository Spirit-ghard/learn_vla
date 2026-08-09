# LWH Robot Learning

当前分支是 `stage_2_1`：在第二阶段键盘遥操作基础上，尝试恢复双相机输入。

策略：

- 渲染和运行参数继续对齐 LeIsaac `LeIsaac-SO101-LiftCube-v0`。
- 相机位置使用本项目之前自定义的 `front` 和 `wrist` 位姿。
- 默认不强制 `quality + FXAA`，先使用 IsaacLab/LeIsaac 默认渲染路径。

项目只运行 IsaacLab 仿真，不连接真实机器人，不启动 ROS，不访问串口。

## 使用方式

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_2_1
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

## 当前配置

```text
front camera: 640 x 480, 30 FPS, 本项目原 front 位姿
wrist camera: 640 x 480, 30 FPS, 本项目原 wrist 位姿
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

如果双相机默认配置开始卡顿，先退回 `stage_2` 的单相机版本采集遥操作手感；`stage_2_1`
用于评估双相机是否能在当前机器上保持可接受延迟。
