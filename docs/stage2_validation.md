# 第二阶段记录

本阶段实现键盘遥操作，并先对齐 LeIsaac `LeIsaac-SO101-LiftCube-v0` 的轻量运行配置。

## LeIsaac 参考

本地源码版本：

```text
dependencies/leisaac
24d3bcd3f1e4585740fc79921782c41617237812
```

核对的源码：

- `scripts/environments/teleoperation/teleop_se3_agent.py`
- `source/leisaac/leisaac/tasks/lift_cube/lift_cube_env_cfg.py`
- `source/leisaac/leisaac/tasks/template/single_arm_env_cfg.py`

关键对齐项：

| 项 | 当前配置 |
| --- | --- |
| 相机 | 只启用 `front` |
| 分辨率 | `640 x 480` |
| 相机 FPS | `30` |
| 控制频率 | `60 Hz` |
| `render_interval` | `1` |
| 默认渲染 preset | IsaacLab 默认 |
| 默认抗锯齿 | IsaacLab 默认 |
| 质量开关 | `--quality` 时启用 `FXAA + quality` |

运行时不导入 `leisaac` Python 包，只按其源码配置重写 IsaacLab 任务和入口。

## 正式使用

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

如果需要 LeIsaac 的质量模式：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --quality
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
```
