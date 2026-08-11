# Stage 4 Validation

日期：2026-08-11

## 目标

- 检查当前 HDF5 是否已经录制成功。
- 将当前 HDF5 转换为 LeRobotDataset v3。
- 验证 HDF5 可在 IsaacLab 仿真中回放。
- 验证 GUI 回放入口可启动、加载 episode 并注册按键。
- 检查当前 SO101 Leader 标定文件来源。

## 当前录制文件

```text
datasets/hdf5/lwh_so101_table_leader.hdf5
```

检查结果：

| 字段 | 值 |
| --- | --- |
| episode 数量 | 1 |
| episode 名称 | `demo_0` |
| task | `Lwh-SO101-Table-v0` |
| teleop_device | `so101leader` |
| fps | 30 |
| action shape | `(1184, 6)` |
| state shape | `(1184, 6)` |
| camera keys | `front` |
| image shape | `(1184, 480, 640, 3)` |
| success | `False` |
| outcome | `interrupted` |

结论：

- 已经录到一条有效 leader episode。
- 该 episode 是中断结束，不是 `N` 标记成功结束，所以 `success=False`。
- 如果用于调试转换，需要使用 `--episodes all`；正式训练数据建议用 `N` 正常结束成功 episode。

## LeRobot 转换

转换命令：

```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py \
  --input datasets/hdf5/lwh_so101_table_leader.hdf5 \
  --repo_id lwh/so101_table_leader \
  --output_dir datasets/lerobot/so101_table_leader \
  --episodes all \
  --overwrite
```

转换结果：

| 字段 | 值 |
| --- | --- |
| output_dir | `datasets/lerobot/so101_table_leader` |
| episodes | 1 |
| frames | 1179 |
| observation.state | `(6,)` |
| action | `(6,)` |
| observation.images.front | `(3, 480, 640)` |
| image format | image |

说明：

- 转换脚本默认跳过 episode 前 5 帧，所以 HDF5 `1184` 帧转换为 LeRobot `1179` 帧。
- `tasks.parquet` 当前以 task 文本作为索引，`task_index=0`。

## HDF5 回放验证

headless 回放验证：

```bash
python3 scripts/validate_replay_hdf5.py --headless --device cuda
```

结果：

| 项 | 值 |
| --- | --- |
| replay frames | 90 |
| max joint error | `0.0` |
| max cube position error | `0.0` |
| min camera std | `21.08960723876953` |
| result | passed |

GUI 短回放验证：

```bash
python3 scripts/replay_hdf5.py \
  --dataset_file datasets/hdf5/lwh_so101_table_leader.hdf5 \
  --device cuda \
  --autoplay \
  --max_frames 5 \
  --verify
```

结果：

| 项 | 值 |
| --- | --- |
| replay frames | 5 |
| max joint error | `0.0` |
| max cube position error | `0.0` |
| min camera std | `22.29784393310547` |
| GUI window | created |
| replay keyboard controls | registered |

## SO101 Leader 标定检查

检查命令：

```bash
python3 scripts/calibrate_so101_leader.py --inspect
```

当前解析到：

```text
configs/so101_leader_calibration.json
```

来源确认：

```text
cmp configs/so101_leader_calibration.json \
  /home/a/.local/share/ov/pkg/leisaac/source/leisaac/leisaac/devices/lerobot/.cache/so101_leader.json
```

结果为一致。当前 LeRobot cache 下的：

```text
/home/a/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/my_awesome_leader_arm.json
```

与项目内置标定不一致。正式运行优先使用项目 `configs` 文件。
