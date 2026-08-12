# LWH Robot Learning

当前分支是 `stage_4`：在 Stage 3 录制和转换基础上，新增 HDF5 轨迹回放和 SO101 Leader 标定检查/导入/重标定入口。

项目只运行 IsaacLab 仿真，不控制真实 follower，不启动 ROS。`--teleop_device so101leader` 只读取真实 SO101 Leader 作为仿真输入。

## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_4
```

常用流程：录制 HDF5，转换 LeRobotDataset，在 IsaacSim 中回放 HDF5 检查轨迹。

```bash
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --output datasets/hdf5/lwh_so101_table.hdf5
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
python3 scripts/replay_hdf5.py --task Lwh-SO101-Table-v0 --dataset_file datasets/hdf5/lwh_so101_table.hdf5
```

遥操作/录制按键：

```text
B 开始控制或开始当前 episode 录制
W/S 前后
A/D 左右
Q/E 上下
I/K/J/L 旋转
U/O 夹爪
R 结束当前 episode，标记 failure，然后 reset
N 结束当前 episode，标记 success，然后 reset
Ctrl+C 或关闭窗口退出
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

## 遥操作和录制参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作和录制建议保持 1。 |
| `--teleop_device` | `keyboard` | `keyboard` 使用键盘；`so101leader` 只读取真实 leader 并驱动仿真 follower。 |
| `--camera_mode` | `front` | `front` 只启用前视相机；`dual` 启用 front+wrist。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--teleop_render_interval` | `2` | 每多少个 physics step 渲染一次。 |
| `--quality` | `False` | 画质检查开关，会使用更重的渲染 preset。 |
| `--output` | 录制脚本默认值 | HDF5 输出路径，仅 `record_hdf5.py` 使用。 |
| `--overwrite` | `False` | 输出文件已存在时先删除，仅 `record_hdf5.py` 使用。 |
| `--append` | `False` | 向已有 HDF5 追加 episode，仅 `record_hdf5.py` 使用。 |
| `--leader_port` | `/dev/ttyACM0` | SO101 Leader 串口，只在 `so101leader` 模式使用。 |
| `--leader_calibration` | 未设置 | 显式 leader 标定 JSON；不传时优先使用项目 `configs`。 |
| `--leader_start_immediately` | `False` | Leader 模式启动后不等待 `B`，直接跟随 leader。 |

## 转换参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--input` | 必填 | 输入 HDF5 文件。 |
| `--repo_id` | `lwh/so101_table` | LeRobotDataset repo id。 |
| `--output_dir` | LeRobot 默认 cache | 本地 LeRobotDataset 输出目录。 |
| `--episodes` | `successful` | 默认只转换 `N` 标记成功的 episode；调试中断数据可用 `all`。 |
| `--image_format` | `image` | `image` 兼容性最好；`video` 更省空间但依赖视频解码链路。 |
| `--skip_first_frames` | `5` | 转换时跳过 episode 起始帧数。 |
| `--action_key` | `action` | 用作 LeRobot action 的 HDF5 dataset 路径。 |

## 回放参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--dataset_file` | `datasets/hdf5/lwh_so101_table_leader.hdf5` | 要回放的 HDF5 文件。 |
| `--episode` | `0` | 启动后先加载的 episode index。 |
| `--select_episodes` | 全部 | 限定 GUI 中可切换的 episode 列表。 |
| `--autoplay` | `False` | 启动后立即播放；不传则进入暂停状态。 |
| `--loop` | `False` | 播完后继续循环选中的 episode。 |
| `--speed` | `1.0` | 回放速度倍率，`1.0` 按原始 timestamp。 |
| `--verify` | `False` | 回放时检查关节、方块和相机是否有效。 |
| `--teleop_device` | `auto` | 自动按 HDF5 metadata/action 维度选择动作空间。 |
| `--camera_mode` | `auto` | 自动按 HDF5 camera keys 选择 front 或 dual。 |

## 标定

查看当前 SO101 Leader 标定来源：

```bash
python3 scripts/calibrate_so101_leader.py --inspect
```

当前默认标定文件：

```text
configs/so101_leader_calibration.json
```

如需重新标定 leader，只在 LeRobot 环境中运行：

```bash
conda activate lerobot05
python3 scripts/calibrate_so101_leader.py --calibrate --port /dev/ttyACM0 --output configs/so101_leader_calibration.json
```

这个标定入口只连接 SO101 Leader 输入臂，不连接也不控制真实 follower。

## 数据契约

```text
front camera: 640 x 480, 30 FPS
wrist camera: 可选，640 x 480, 30 FPS
keyboard action: 8D delta IK + relative pan/gripper
so101leader action: 6D joint position
hdf5 schema root: /data/demo_N and /episodes/000000
lerobot conversion: 默认只转换 success episode，默认跳过 episode 前 5 帧
```
