# HZ Robot Learning

当前分支是 `stage_4`：HDF5 轨迹回放、三画面回放视图、SO101 leader/follower 标定工具。

项目只运行 IsaacLab 仿真，不控制真实 follower。`--teleop_device so101leader` 只读取真实 SO101 Leader 作为仿真输入。

## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_4
```

常用流程：

```bash
python3 scripts/teleop.py --record --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --output datasets/hdf5/lwh_so101_table_leader.hdf5 --overwrite
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
python3 scripts/replay_hdf5.py --task Lwh-SO101-Table-v0 --dataset_file datasets/hdf5/lwh_so101_table_leader.hdf5
```

录制 episode 生命周期：

```text
B 开始当前 episode 的操作和录制
R 结束当前 episode，标记 failure，然后 reset
N 结束当前 episode，标记 success，然后 reset
Ctrl+C 安全关闭文件；未用 R/N 结束的当前 episode 会被废弃
```

HDF5 回放按键：

```text
B / Space 暂停或继续
N / Right 切到下一个 episode
P / Left 切到上一个 episode
R 重新加载当前 episode
S 暂停时单步回放
Q / Esc 退出
```

## 关键参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作、录制、回放建议保持 1。 |
| `--teleop_device` | `keyboard` / 回放 `auto` | `keyboard` 使用键盘；`so101leader` 只读取真实 leader；回放可自动按 HDF5 action 维度选择。 |
| `--camera_mode` | 遥操作/录制 `front`，回放 `dual` | `front` 只启用前视；`dual` 启用 front+wrist。回放默认双相机便于检查。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--record` | `False` | 加在 `scripts/teleop.py` 上后进入 HDF5 录制流程。 |
| `--output` | 脚本默认值 | HDF5 输出路径，录制使用。 |
| `--overwrite` | `False` | 输出文件已存在时先删除。 |
| `--append` | `False` | 向已有 HDF5 追加 episode。 |
| `--dataset_file` | `datasets/hdf5/lwh_so101_table_leader.hdf5` | 要回放的 HDF5 文件。 |
| `--episode` | `0` | 回放启动后先加载的 episode index。 |
| `--autoplay` | `False` | 回放启动后立即播放；不传则暂停等待。 |
| `--viewer_layout` | `tri` | 回放 GUI：上排 front+wrist，占约 40%；下排主视角。`isaac` 只保留 Isaac 默认 viewport。 |
| `--verify` | `False` | 回放时检查关节、方块和相机是否有效。 |
| `--leader_port` | `/dev/ttyACM0` | SO101 Leader 串口，只在 `so101leader` 模式使用。 |
| `--leader_calibration` | 未设置 | 显式 leader 标定 JSON；不传时优先使用项目 `configs`。 |

## 标定

查看当前 leader 标定：

```bash
python3 scripts/calibrate_so101.py --arm leader --inspect
```

查看或重新标定 follower：

```bash
python3 scripts/calibrate_so101.py --arm follower --inspect
conda activate lerobot05
python3 scripts/calibrate_so101.py --arm follower --calibrate --port /dev/ttyACM1 --output configs/so101_follower_calibration.json
```

旧入口仍可用：

```bash
python3 scripts/calibrate_so101_leader.py --inspect
```

## 数据契约

```text
front camera: 640 x 480, 30 FPS
wrist camera: 可选，640 x 480, 30 FPS
keyboard action: 8D delta IK + relative pan/gripper
so101leader action: 6D joint position
hdf5 schema root: /data/demo_N and /episodes/000000
lerobot conversion: 默认只转换 success episode，默认跳过 episode 前 5 帧
```
