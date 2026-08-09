# 第二阶段记录

`stage_2_2` 是可选相机实验分支。它基于 `stage_2` 的 LeIsaac 风格遥操作配置，支持
`--camera_mode front` 和 `--camera_mode dual`，用于评估当前机器在单/双相机下的遥操作流畅度。

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
| `render_interval` | `1` |
| 默认渲染 preset | IsaacLab 默认 |
| 默认抗锯齿 | IsaacLab 默认 |
| 质量开关 | `--quality` 时启用 `FXAA + quality` |

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
3. 双相机卡顿时先尝试 `--teleop_render_interval 2`。
4. `--quality` 只用于画质确认，不作为默认录制配置。
