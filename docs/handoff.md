# Handoff

更新时间：2026-08-11

## 当前交接状态

当前项目：

```text
<repo>
```

当前分支：

```text
stage_3
```

最新提交：

```text
stage 3: add hdf5 recording and lerobot conversion
```

当前主线：

```text
main: 暂未更新到本地最新阶段分支
stage_2_2: 键盘遥操作封存版
stage_2_3: 当前最新，真实 SO101 Leader 输入
stage_3: HDF5 数据录制和 LeRobotDataset v3 转换
```

当前远端：

```text
origin git@github.com:Spirit-ghard/learn_vla.git
```

## 已完成

- Stage 1：`Lwh-SO101-Table-v0` SO101 桌面方块任务。
- Stage 2：键盘遥操作。
- Stage 2.2：单/双相机可选，teleop 默认关闭额外 ground，并使用 30 Hz 渲染口径提升遥操作控制频率。
- Stage 2.3：新增真实 SO101 Leader 串口输入，只控制 IsaacLab 仿真 follower。
- 可搬迁性：SO101 Follower USD 和当前 leader 校准已放入项目目录，默认不再依赖 LeIsaac 资产安装路径。
- Stage 3：新增 HDF5 录制入口和 HDF5 到 LeRobotDataset v3 转换入口。

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

真实 SO101 Leader 控制仿真：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0
```

键盘录制 HDF5：

```bash
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --output datasets/hdf5/lwh_so101_table.hdf5
```

双相机录制 HDF5：

```bash
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual --output datasets/hdf5/lwh_so101_table_dual.hdf5
```

真实 SO101 Leader 输入录制 HDF5：

```bash
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --output datasets/hdf5/lwh_so101_table_leader.hdf5
```

转换 LeRobotDataset v3：

```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
```

启动后立即跟随 leader：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --leader_start_immediately
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
docs/portability.md
```

## 下一步建议

下一步应进入 Stage 4 数据回放。

Stage 4 最小目标：

- 新增独立 Python 入口 `scripts/replay_hdf5.py`。
- 读取 Stage 3 HDF5 的指定 episode。
- 使用 `initial_state` 重置场景。
- 按原始频率逐帧应用 `action`。
- 支持选择 episode、暂停、继续和退出。
- 对比机器人轨迹、方块状态和相机画面。

## 注意事项

- 不要直接从 LeIsaac import 任务、模板或设备。
- 不要启动 ROS。
- 只有 `--teleop_device so101leader` 可以读取真实 leader 串口；不得控制真实 follower。
- 不要新增 shell 启动脚本。
- 每次实现一个阶段，完成验证后再进入下一阶段。
- 内部验证产物不要保留在仓库里。
- Stage 3 HDF5 使用 `/data/demo_N` 和 `/episodes/000000` 两套入口；`/episodes` 是硬链接。
- 转换脚本默认只转换成功 episode、跳过前 5 帧、输出 LeRobot image 格式。
