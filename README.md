# HZ Robot Learning
```bash
  目标：
  现有 HDF5 只有 front / wrist 两路视角，网页回放工具需要三窗口布局：
  第一排 40% 高度，左右分别显示 front 和 wrist；
  第二排 60% 高度，显示全场景主视角 overview。
  由于网页回放不启动 IsaacSim，只能播放 HDF5 中已经录制的图像，因此 overview 必须在采集阶段写入 HDF5。

  实现要求：
  1. 在 SO101 table 任务 scene 中新增一个 overview / third-person TiledCamera。
  2. overview 需要能看到完整桌面、机器人、红色方块和夹爪运动区域。
  3. 分辨率建议保持 640x480 RGB，更新频率 30 FPS，和 front/wrist 对齐。
  4. HDF5 schema 中新增：
     /data/demo_N/observation/images/overview
  5. metadata 的 camera_keys 需要包含 overview。
  6. 新增或扩展 camera_mode：
     - front：只录 front
     - dual：录 front + wrist
     - triple：录 front + wrist + overview
  7. 网页 viewer 默认三窗口映射：
     - top-left: front
     - top-right: wrist
     - bottom: overview
  8. 如果旧数据没有 overview，viewer 需要显示“overview 未录制”，不能启动 IsaacSim 生成画面。

  验收标准：
  1. 使用 --camera_mode triple 录制 HDF5 后，h5py 能看到 observation/images/front、wrist、overview 三路图像。
  2. 三路图像 shape 都是 frames x 480 x 640 x 3。
  3. metadata/camera_keys 包含 ["front", "wrist", "overview"]。
  4. overview 画面能稳定看到完整桌面、机器人、方块和主要操作区域。
  5. timestamp/action/state 与三路图像帧数一致。
  6. 单相机和双相机旧模式不被破坏。
```
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
