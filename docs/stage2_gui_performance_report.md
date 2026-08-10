# Stage 2 GUI Camera Performance Report

测试时间：2026-08-09

测试目标：对比 LeIsaac 单相机、本项目单相机、本项目双相机在 GUI 可视化遥操作链路下的实际吞吐，并找出本项目低于 LeIsaac 的原因。

## 测试口径

- 窗口模式：GUI，可视化窗口创建成功。
- 设备：`cuda`，日志识别为 NVIDIA GeForce RTX 3060 Laptop GPU 6GB。
- 控制目标：`60 Hz` 控制循环。
- 相机目标：每路 `640 x 480 @ 30 FPS`。
- 渲染：Isaac/Kit 默认，实际为 `DLSS balanced`，`render_interval=1`。
- 输入：通过 Carb keyboard event 注入同一组 `B/D/R/U/N` 事件。
- 循环：180 次 GUI loop，期间等待时调用 `env.sim.render()`。
- 本性能测试不连接真实设备，不访问串口。

## 对比结果

| Case | Camera | Ground | Wall loop Hz | Control segment Hz | Camera target |
| --- | --- | --- | ---: | --- | --- |
| LeIsaac `LeIsaac-SO101-LiftCube-v0` | front | 无额外 ground | 30.45 | 27.09 / 32.04 | front 30Hz |
| LWH 原配置 | front | on | 25.72 | 23.46 / 26.78 | front 30Hz |
| LWH 原配置 | front + wrist | on | 20.56 | 19.05 / 21.12 | front+wrist 30Hz |
| LWH 优化后 | front | off | 32.16 | 28.51 / 34.38 | front 30Hz |
| LWH 优化后 | front + wrist | off | 25.68 | 23.47 / 26.81 | front+wrist 30Hz |

## 消融结论

- 只把本项目 front 相机改成 LeIsaac 的位姿和镜头参数，吞吐仍约 `25.26 Hz`，没有解决问题。
- 使用 LeIsaac front 相机参数并移除 ground 后，吞吐约 `30.39 Hz`，与 LeIsaac 的 `30.45 Hz` 基本一致。
- 保留本项目 front 位姿、只移除 ground 后，吞吐约 `32.16 Hz`，说明主要瓶颈是额外大地面，不是相机位姿。
- 双相机比单相机明显更重；移除 ground 后从约 `20.56 Hz` 提升到约 `25.68 Hz`，但仍低于单相机。

## 当前处理

`scripts/teleop.py` 新增：

```bash
--ground_mode off|on
```

默认值为 `off`，用于对齐 LeIsaac 桌面任务的 GUI 性能。任务配置类仍保留 ground；如果需要完整地面，使用：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front --ground_mode on
```

推荐正式遥操作基线：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

双相机评估：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

## 判断

本项目单相机在 `ground_mode=off` 后已经达到 LeIsaac 单相机 GUI 性能水平。双相机由于多一路 TiledCamera，当前机器上不应期望达到 LeIsaac 单相机同等吞吐；如果后续录制必须双相机，应优先评估操作手感和数据质量，而不是强行追 30Hz GUI loop。
