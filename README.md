# LWH Robot Learning

当前分支是 `stage_2_3`：在第二阶段键盘遥操作基础上，新增真实 SO101 Leader 作为仿真遥操作输入。

## 使用方式

进入项目目录：

```bash
cd <repo>
git checkout stage_2_3
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
