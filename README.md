# LWH Robot Learning

当前分支是 `stage_3`：在 Stage 2.3 遥操作基础上，新增 HDF5 数据录制和 HDF5 到 LeRobotDataset v3 的转换脚本。

## 后续开发上下文

如果后续对话上下文不足，先阅读这些文件再继续开发：

- [AGENTS.md](AGENTS.md)：项目硬性边界和 Codex 接手规则。
- [project_context.md](docs/project_context.md)：项目总目标、目录结构、运行环境、任务和相机配置。
- [stage_status.md](docs/stage_status.md)：六个阶段的目标、完成状态、启动方式和下一步。
- [decision_log.md](docs/decision_log.md)：已经做过的关键技术决策及原因。
- [handoff.md](docs/handoff.md)：当前交接状态和新对话启动提示。
- [compatibility.md](docs/compatibility.md)：Isaac Sim、IsaacLab、LeIsaac、Python、GPU 等版本记录。
- [portability.md](docs/portability.md)：项目搬迁、内置资产和外部环境变量说明。
- [stage3_validation.md](docs/stage3_validation.md)：Stage 3 录制和转换验证记录。

策略：

- 渲染和运行参数继续对齐 LeIsaac `LeIsaac-SO101-LiftCube-v0`。
- `front` 和 `wrist` 相机位置使用本项目之前自定义的位姿。
- 默认不强制 `quality + FXAA`，先使用 IsaacLab/LeIsaac 默认渲染路径。
- 遥操作默认关闭额外 ground plane，对齐 LeIsaac 桌面任务的 GUI 性能；任务配置本身仍保留 ground。
- 遥操作默认使用 `render_interval=2`，目标是 60 Hz 控制和 30 Hz 图像/渲染更新。
- `--teleop_device so101leader` 只读取真实 leader 串口位置并驱动仿真 follower，不控制真实 follower。
- SO101 Follower USD 已内置在项目目录：`source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/robots/so101_follower.usd`。
- Isaac 端只写 HDF5；LeRobotDataset 转换在单独的 LeRobot Python 环境运行。

项目只运行 IsaacLab 仿真，不启动 ROS，不控制真实机器人。Stage 2.3/3 允许在显式选择
`so101leader` 时访问真实 leader 串口作为输入设备。

## 使用方式

进入项目目录：

```bash
cd <repo>
git checkout stage_3
```

启动键盘遥操作，默认单相机高频配置：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

启动真实 SO101 Leader 控制仿真：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --teleop_device so101leader \
  --leader_port /dev/ttyACM0
```

Leader 模式默认按 `B` 后开始控制。如果希望启动后立即跟随 leader：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --teleop_device so101leader \
  --leader_port /dev/ttyACM0 \
  --leader_start_immediately
```

如果要指定校准文件：

```bash
python3 scripts/teleop.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --teleop_device so101leader \
  --leader_port /dev/ttyACM0 \
  --leader_calibration /path/to/so101_leader.json
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

录制键盘遥操作到 HDF5，默认单相机：

```bash
python3 scripts/record_hdf5.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --output datasets/hdf5/lwh_so101_table.hdf5
```

录制真实 SO101 Leader 控制仿真到 HDF5：

```bash
python3 scripts/record_hdf5.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --teleop_device so101leader \
  --leader_port /dev/ttyACM0 \
  --output datasets/hdf5/lwh_so101_table_leader.hdf5
```

录制双相机数据：

```bash
python3 scripts/record_hdf5.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode dual \
  --output datasets/hdf5/lwh_so101_table_dual.hdf5
```

转换为 LeRobotDataset v3。在 LeRobot 环境中运行，不在 IsaacSim 环境中运行：

```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py \
  --input datasets/hdf5/lwh_so101_table.hdf5 \
  --repo_id lwh/so101_table \
  --output_dir datasets/lerobot/so101_table \
  --overwrite
```

转换脚本默认输出 image 格式，当前本机训练环境可直接加载。如果确认 LeRobot 环境的
video 解码链路可用，也可以显式输出 video 格式以节省空间：

```bash
python3 scripts/convert_hdf5_to_lerobot.py \
  --input datasets/hdf5/lwh_so101_table.hdf5 \
  --repo_id lwh/so101_table \
  --output_dir datasets/lerobot/so101_table_video \
  --image_format video \
  --overwrite
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

Leader 模式按键：

```text
B 开始跟随真实 leader
R 失败并重置
N 成功并重置
Ctrl+C 或关闭窗口退出
```

录制 episode 生命周期：

```text
B 开始当前 episode 的操作和录制
R 结束当前 episode，标记 failure，然后 reset
N 结束当前 episode，标记 success，然后 reset
Ctrl+C 安全关闭文件；未完成 episode 会标记 interrupted/failure
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
keyboard action: 8D delta IK + relative pan/gripper
so101leader action: 6D joint position
hdf5 schema root: /data/demo_N and /episodes/000000
lerobot conversion: 默认只转换 success episode，默认跳过 episode 前 5 帧
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

录制文件已写入以下关键数据：

```text
observation/state
observation/images/front
observation/images/wrist
action
timestamp
episode_index
frame_index
task
success
initial_state
```

键盘模式记录的是 8D IK/相对关节动作；真实 leader 模式记录的是 6D joint position
动作，更适合后续 SO101 关节策略训练。

Leader 串口相关参数：

```text
--leader_port             leader 串口，默认 /dev/ttyACM0
--leader_calibration      显式校准 JSON；不传时优先环境变量、项目 configs、LeRobot cache、LeIsaac cache
--leader_id               用于查找 LeRobot cache 下的校准文件
--leader_start_immediately 启动后不等 B，直接跟随 leader
--leader_keep_torque      不在连接时关闭 leader 扭矩
--leader_skip_handshake   跳过电机 ping 检查
```

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
