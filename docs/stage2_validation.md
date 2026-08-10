# 第二阶段记录

## 待办：频率现状和后续判断

### 现状梳理

当前配置上有三个“频率”需要分开看：

| 名称 | 含义 | 当前口径 |
| --- | --- | --- |
| `control_hz` | IsaacLab 环境配置的仿真步进目标 | `60 Hz`, 即 `env.step_dt = 1 / 60` |
| `camera_hz` | 每路相机传感器目标采样率 | `30 Hz`, `640 x 480 RGB` |
| `wall loop Hz` | GUI 主循环按真实墙钟时间实际跑了多少轮 | 受 viewport、相机同步、render、CPU/GPU 调度影响 |

目前已经观察到：

- IsaacSim 窗口左下角显示的 `FPS` 更接近 GUI/渲染帧率，不等同于控制频率。
- `env.step_dt = 1/60` 说明环境目标控制步长是 60Hz；但如果 GUI、相机或同步读回拖慢主循环，实际 `env.step(action)` 可能达不到 60 次/秒。
- GPU 占用率只有 60% 不代表没有瓶颈。同步相机、RTX/Hydra viewport、Vulkan 内存分配、CPU 侧调度、Python 主循环等待都可能让 GPU 没有满载但主循环仍变慢。
- 单相机默认配置已经明显优于最初版本；双相机 GUI 仍明显更重。

已有测试过程：

| Case | 关键配置 | 结果 |
| --- | --- | --- |
| LeIsaac 单相机 | front, 无额外 ground, `render_interval=1` | `wall loop` 约 `30.45 Hz`, control segment 约 `27.09 / 32.04 Hz` |
| LWH 原单相机 | front, ground on | `wall loop` 约 `25.72 Hz` |
| LWH 原双相机 | front+wrist, ground on | `wall loop` 约 `20.56 Hz` |
| LWH 单相机移除 ground | front, ground off | `wall loop` 约 `32.16 Hz`，基本追平 LeIsaac |
| LWH 双相机移除 ground | front+wrist, ground off | `wall loop` 约 `25.68 Hz` |
| LWH 高频默认路径 | front, ground off, `render_interval=2` | `wall loop` 约 `45-46 Hz`, control segment 可到 `57-58 Hz` |
| LWH 双相机高频路径 | front+wrist, ground off, `render_interval=2` | `wall loop` 约 `33-34 Hz` |

结论过程：

1. 最早卡顿不是单纯 GPU 算力不够，主要是 GUI 渲染链路、同步相机和额外 ground 带来的主循环吞吐下降。
2. 只改相机位姿或镜头参数不能解决频率问题；移除额外 ground 后，单相机已经能达到 LeIsaac 同级表现。
3. `render_interval=2` 后，目标变成 `60 Hz` 仿真控制 + `30 Hz` 渲染/相机更新，更符合采集数据的需求。
4. 双相机在 GUI 下不应预期稳定 60Hz 控制；它需要在 Stage 3 录制时依赖真实 timestamp，并在 LeRobot 转换阶段按训练 FPS 重采样。

### 用户疑问

- 既然 GPU 没满，为什么控制频率还上不去？
- IsaacSim 画面上显示约 32 FPS，是不是环境本身只有 32Hz？
- 渲染 FPS 和控制频率到底是不是一回事？
- 如果主循环不到 60Hz，遥操作动作是否会变差，训练数据是否还有效？
- 真实 leader 模式是否也会受同样的 GUI/相机链路影响？

### 当前判断

- 对第一版 VLA/ACT 数据采集，`640 x 480 @ 30 FPS` 的清晰 RGB 图像是合理底线；图像清晰度比盲目追 60FPS 图像更重要。
- 训练数据不一定要求图像和 action 都是 60Hz。常见做法是记录真实 timestamp，再按 `30 FPS` 或训练配置重采样 observation/action。
- 单相机 `front` 当前基本满足第一版遥操作和录制基线：图像 `640 x 480 @ 30Hz`，控制段可接近 60Hz，但不保证每一秒都严格 60Hz。
- 双相机 GUI 当前不满足“严格 60Hz 控制 + 双路 30Hz 同步显示”的要求；如果必须双相机，Stage 3 应优先保证 timestamp、帧完整性和动作对齐，而不是强行要求 GUI 主循环 60Hz。
- 真实 leader 模式已经验证能控制仿真，但还需要补一个专门的频率统计入口，区分串口读取耗时、`env.step` 耗时和渲染/相机耗时。

### 后续待办

1. 新增或扩展一个 Python benchmark 入口，只记录统计结果，不作为正式使用流程。
2. 同一套统计口径分别测：
   - GUI 纯环境 step，不接 teleop。
   - GUI keyboard + front。
   - GUI keyboard + front+wrist。
   - GUI so101leader + front。
   - GUI so101leader + front+wrist。
3. 每个 case 至少统计：
   - `env.step` 平均/最大耗时。
   - `teleop.advance` 平均/最大耗时。
   - 串口读取耗时，leader 模式专用。
   - `env.sim.render` 或相机同步耗时。
   - 实际 wall loop Hz。
   - 实际 action timestamp 间隔分布。
4. Stage 3 录制必须记录真实 `timestamp`，不要只用固定 FPS 推断时间。
5. Stage 5 转 LeRobotDataset 时按目标训练 FPS 重采样，并检查 action/state/image 对齐。
6. 如果单相机数据仍手感不稳，再考虑降低 GUI viewport 负担；如果图像不清楚，优先保持 `640 x 480`，再调 AA/render preset，不优先降分辨率。

`stage_2_2` 是键盘遥操作封存分支。它基于 `stage_2` 的 LeIsaac 风格遥操作配置，支持
`--camera_mode front` 和 `--camera_mode dual`，用于评估当前机器在单/双相机下的遥操作流畅度。

`stage_2_3` 在此基础上新增真实 SO101 Leader 输入。Leader 模式只读取真实 leader 串口位置，
动作仍只发送给 IsaacLab 仿真 follower。

## 与 LeIsaac 对齐的部分

本地 LeIsaac 源码：

```text
dependencies/leisaac
24d3bcd3f1e4585740fc79921782c41617237812
```

继续对齐的运行参数：

| 项 | 当前配置 |
| --- | --- |
| 控制频率 | `60 Hz` |
| `render_interval` | `2` |
| 默认渲染 preset | IsaacLab 默认 |
| 默认抗锯齿 | IsaacLab 默认 |
| 质量开关 | `--quality` 时启用 `FXAA + quality` |
| teleop ground | 默认 `--ground_mode off`，对齐 LeIsaac 桌面任务性能 |

LeIsaac 对照启动结果：

| 项 | 结果 |
| --- | --- |
| task registry | 包含 `LeIsaac-SO101-LiftCube-v0` |
| 官方 teleop 入口 | 可进入键盘遥操作 ready 状态 |
| LeIsaac 相机 | 1 路 `front`，`640 x 480 @ 30 FPS` |
| 实际默认渲染 | `DLSS balanced`，`render_interval=1` |

## 与 `stage_2` 不同的部分

| 项 | `stage_2` | `stage_2_2` |
| --- | --- | --- |
| 相机数量 | 1 路 `front` | 可选 `front` 或 `front + wrist` |
| front 位姿 | LeIsaac LiftCube front | 本项目原 front |
| wrist 位姿 | disabled | `dual` 模式使用本项目原 wrist |
| 图像规格 | `640 x 480 @ 30 FPS` | 每路 `640 x 480 @ 30 FPS` |
| teleop ground | 保持 task 配置 | 运行入口默认移除额外 ground，可用 `--ground_mode on` 恢复 |

## `stage_2_3` 新增内容

| 项 | 当前配置 |
| --- | --- |
| 新增输入设备 | `--teleop_device so101leader` |
| 串口默认值 | `/dev/ttyACM0` |
| 动作空间 | 6D joint position |
| 默认相机 | `front`, `640 x 480 @ 30 FPS` |
| 校准文件查找 | 参数、环境变量、LeRobot cache、LeIsaac cache |
| 真实设备边界 | 读取 leader 位置，不控制真实 follower，不启动 ROS |

正式使用：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

只启用前视相机：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

显式启用双相机：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

如果默认画面不够清楚：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --quality
```

性能调试顺序：

1. 先用 `--camera_mode front` 对齐 LeIsaac 单相机基线。
2. 单相机流畅后再用 `--camera_mode dual` 评估双相机。
3. 如需完整地面，再显式加 `--ground_mode on`。
4. 双相机卡顿时先尝试 `--teleop_render_interval 2`。
5. `--quality` 只用于画质确认，不作为默认录制配置。

GUI 性能对比见 `docs/stage2_gui_performance_report.md`。

## `stage_2_3` 验证结果

验证日期：2026-08-10。

已完成：

- `compileall` 通过。
- `scripts/teleop.py --help` 可显示 `--teleop_device so101leader` 和 leader 参数。
- `/dev/ttyACM0` 可握手真实 SO101 Leader 的 6 个电机。
- 校准文件使用 LeIsaac cache：`so101_leader.json`。
- 可读取 raw position 和归一化 position。
- 键盘验证路径仍通过，`LWH_STAGE2_VALIDATION_OK`。
- leader 完整入口可创建 IsaacLab GUI 环境，动作管理器为 6D joint position。
- leader 入口输出 `LWH_SO101_LEADER_CONNECTED`、`LWH_TELEOP_STARTED`、`LWH_TELEOP_ACTION_ACTIVE`。
- leader 入口运行后仿真机器人最大关节变化约 `1.609383 rad`，正常 Ctrl+C 退出。

Leader 正式启动：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0
```

Leader 启动后立即控制：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --leader_start_immediately
```
