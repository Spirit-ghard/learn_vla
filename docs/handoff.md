# Handoff

更新时间：2026-08-10

## 当前交接状态

当前项目：

```text
/home/a/lwh_code/lwh_robot_learning
```

当前分支：

```text
stage_2_2
```

最新提交：

```text
665a38e stage 2.2: align teleop ground profile with LeIsaac
```

当前主线：

```text
main -> 665a38e
stage_2_2 -> 665a38e
```

当前远端：

```text
origin git@github.com:Spirit-ghard/learn_vla.git
```

## 已完成

- Stage 1：`Lwh-SO101-Table-v0` SO101 桌面方块任务。
- Stage 2：键盘遥操作。
- Stage 2.2：单/双相机可选，teleop 默认关闭额外 ground，并使用 30 Hz 渲染口径提升遥操作控制频率。

## 当前可用命令

场景运行：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

推荐单相机遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

双相机遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

完整 ground：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front --ground_mode on
```

## 当前性能结论

- LeIsaac 单相机 GUI：约 `30.45 Hz` wall loop。
- 本项目单相机 `ground_mode=off`：约 `32.16 Hz` wall loop。
- 本项目双相机 `ground_mode=off`：约 `25.68 Hz` wall loop。
- 本项目低于 LeIsaac 的主要原因曾是额外 20m ground plane，不是相机位姿。
- 进一步改为默认 `render_interval=2` 后，单相机验证控制段最高约 `59.15 Hz`，图像/渲染为 `30 Hz`。
- 双相机 GUI 仍只有三十多 Hz 控制段，不建议作为第一版默认录制配置。

详细报告：

```text
docs/stage2_gui_performance_report.md
```

## 下一步建议

下一步应进入 Stage 3 数据录制。

建议创建分支：

```bash
git checkout stage_2_2
git checkout -b stage_3
```

Stage 3 最小目标：

- 新增独立 Python 入口，例如 `scripts/record_hdf5.py`。
- 复用 `SO101Keyboard` 和 `teleop.py` 的任务创建/相机/ground 配置逻辑。
- 写 HDF5，不直接依赖 LeRobot。
- 记录 state、front image、可选 wrist image、action、timestamp、episode_index、frame_index、task。
- 明确 episode 生命周期：`B` 开始，`R` 失败结束，`N` 成功结束，reset 下一集。
- 录制后新增最小读取校验。

## 注意事项

- 不要直接从 LeIsaac import 任务、模板或设备。
- 不要启动 ROS 或串口。
- 不要新增 shell 启动脚本。
- 每次实现一个阶段，完成验证后再进入下一阶段。
- 内部验证产物不要保留在仓库里。
