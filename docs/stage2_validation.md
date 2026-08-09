# 第二阶段记录

`stage_2_1` 是双相机实验分支。它基于 `stage_2` 的 LeIsaac 风格遥操作配置，只把
`wrist` 相机加回，用于评估当前机器是否能在双相机下保持可接受的遥操作流畅度。

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

## 与 `stage_2` 不同的部分

| 项 | `stage_2` | `stage_2_1` |
| --- | --- | --- |
| 相机数量 | 1 路 `front` | 2 路 `front + wrist` |
| front 位姿 | LeIsaac LiftCube front | 本项目原 front |
| wrist 位姿 | disabled | 本项目原 wrist |
| 图像规格 | `640 x 480 @ 30 FPS` | 每路 `640 x 480 @ 30 FPS` |

正式使用：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

如果默认画面不够清楚：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --quality
```
