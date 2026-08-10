# 第二阶段记录

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
