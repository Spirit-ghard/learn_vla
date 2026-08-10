# LWH Robot Learning

当前分支是 `stage_2_2`：在第二阶段键盘遥操作基础上，提供单相机高频默认遥操作和双相机可选运行。

## 后续开发上下文

如果后续对话上下文不足，先阅读这些文件再继续开发：

- [AGENTS.md](/home/a/lwh_code/lwh_robot_learning/AGENTS.md)：项目硬性边界和 Codex 接手规则。
- [project_context.md](/home/a/lwh_code/lwh_robot_learning/docs/project_context.md)：项目总目标、目录结构、运行环境、任务和相机配置。
- [stage_status.md](/home/a/lwh_code/lwh_robot_learning/docs/stage_status.md)：六个阶段的目标、完成状态、启动方式和下一步。
- [decision_log.md](/home/a/lwh_code/lwh_robot_learning/docs/decision_log.md)：已经做过的关键技术决策及原因。
- [handoff.md](/home/a/lwh_code/lwh_robot_learning/docs/handoff.md)：当前交接状态和新对话启动提示。
- [compatibility.md](/home/a/lwh_code/lwh_robot_learning/docs/compatibility.md)：Isaac Sim、IsaacLab、LeIsaac、Python、GPU 等版本记录。

策略：

- 渲染和运行参数继续对齐 LeIsaac `LeIsaac-SO101-LiftCube-v0`。
- `front` 和 `wrist` 相机位置使用本项目之前自定义的位姿。
- 默认不强制 `quality + FXAA`，先使用 IsaacLab/LeIsaac 默认渲染路径。
- 遥操作默认关闭额外 ground plane，对齐 LeIsaac 桌面任务的 GUI 性能；任务配置本身仍保留 ground。
- 遥操作默认使用 `render_interval=2`，目标是 60 Hz 控制和 30 Hz 图像/渲染更新。

项目只运行 IsaacLab 仿真，不连接真实机器人，不启动 ROS，不访问串口。

## 使用方式

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_2_2
```

启动键盘遥操作，默认单相机高频配置：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

显式只启用前视相机：

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
ground plane: teleop 默认关闭，可通过 --ground_mode on 恢复
control loop: 60 Hz
sim dt: 1 / 60 s
render_interval: 2
camera/render target: 30 Hz
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

如果需要查看完整地面：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode front \
  --ground_mode on
```

## 调参顺序

优先从最接近 LeIsaac 的配置开始：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

如果单相机流畅，再显式切回双相机：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

如果双相机仍卡顿，但你需要保留双相机数据，可以先明确使用默认的 30 Hz 渲染口径：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode dual \
  --teleop_render_interval 2
```

`--quality` 只用于确认画质问题，不建议作为默认录制配置；它会切到更重的渲染 preset。
当前阶段建议数据底线是每路相机 `640 x 480 @ 30 FPS`、单相机遥操作尽量接近 `60 Hz` 控制、只记录 RGB 图像和关节状态。双相机 GUI 遥操作会明显更重，第一版数据采集优先使用单相机。

GUI 性能对比记录见 [stage2_gui_performance_report.md](docs/stage2_gui_performance_report.md)。
