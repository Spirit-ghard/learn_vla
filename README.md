# LWH Robot Learning

当前分支是 `stage_3`：在 Stage 2.3 遥操作基础上，新增 HDF5 数据录制和 HDF5 到 LeRobotDataset v3 的转换脚本。

项目只运行 IsaacLab 仿真，不控制真实 follower，不启动 ROS。`--teleop_device so101leader` 只读取真实 SO101 Leader 作为仿真输入。

## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_3
```

常用采集流程：先遥操作确认手感，再录制 HDF5，最后在 LeRobot 环境中转换数据。

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --output datasets/hdf5/lwh_so101_table.hdf5
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
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
Ctrl+C 或关闭窗口退出
```

录制 episode 生命周期：

```text
B 开始当前 episode 的操作和录制
R 结束当前 episode，标记 failure，然后 reset
N 结束当前 episode，标记 success，然后 reset
Ctrl+C 安全关闭文件；未完成 episode 会标记 interrupted/failure
```

## 遥操作参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作和录制建议保持 1。 |
| `--teleop_device` | `keyboard` | `keyboard` 使用键盘；`so101leader` 只读取真实 leader 并驱动仿真 follower。 |
| `--camera_mode` | `front` | `front` 只启用前视相机；`dual` 启用 front+wrist。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--teleop_render_interval` | `2` | 每多少个 physics step 渲染一次。 |
| `--quality` | `False` | 画质检查开关，会使用更重的渲染 preset。 |
| `--leader_port` | `/dev/ttyACM0` | SO101 Leader 串口，只在 `so101leader` 模式使用。 |
| `--leader_calibration` | 未设置 | 显式 leader 标定 JSON；不传时走项目默认解析顺序。 |
| `--leader_start_immediately` | `False` | Leader 模式启动后不等待 `B`，直接跟随 leader。 |

## 录制参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--output` | 必填/默认脚本值 | HDF5 输出路径。 |
| `--overwrite` | `False` | 输出文件已存在时先删除。 |
| `--append` | `False` | 向已有 HDF5 追加 episode。 |
| `--camera_mode` | `front` | 录制前视或双相机。 |
| `--teleop_device` | `keyboard` | 录制键盘 8D IK action 或 leader 6D joint position action。 |
| `--chunk_size` | `32` | 非图像 dataset 的 HDF5 chunk 长度。 |
| `--min_frames` | `1` | episode 保存所需最少帧数。 |

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

HDF5 关键字段：

```text
observation/state
observation/images/front
observation/images/wrist
action
timestamp
episode_index
frame_index
task
success
initial_state
```
