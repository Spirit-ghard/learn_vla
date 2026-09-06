# HZ Robot Learning

当前分支是 `stage_5`：HDF5 录制/回放、网页数据查看、SO101 leader/follower 标定工具、LeRobot 训练和本地 Isaac Sim + 服务器异步推理。

项目只运行 IsaacLab 仿真，不控制真实 follower。`--teleop_device so101leader` 只读取真实 SO101 Leader 作为仿真输入。

场景物体当前使用黄色胶囊棍子，并在桌面上加入低矮放置托盘。每次 reset 会在桌面 XY 方向对可抓取物体做约 `±3cm` 的轻微随机化，用于提升数据覆盖，但不会把目标随机到操作区域外或撞到托盘。

## 项目演示

服务器运行 LeRobot 策略、本地 Isaac Sim 运行异步推理客户端的演示。GitHub 页面使用动图预览，点击预览可打开完整视频：

[![服务器 + 本地异步推理演示](./待阅读/服务器%2B本地%2B异步推理.gif)](./待阅读/服务器%2B本地%2B异步推理.mp4)

[打开 MP4 视频](./待阅读/服务器%2B本地%2B异步推理.mp4) · [下载原始 MKV 视频](./待阅读/服务器%2B本地%2B异步推理.mkv)

## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_5
```
## 参数修改:
#### robot，相机等位置在so101_table_env_cfg.py的顶部
## 常用流程：

#### 0.场景
```bash
python3 scripts/run_env.py
```
#### 0.遥操
```bash
cd /home/a/lwh_code/lwh_robot_learning
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --camera_mode dual
```

#### 1.启动录制
```bash 
conda activate isaac
python3 scripts/teleop.py --record --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual --output datasets/hdf5/lwh_so101_table_leader.hdf5
```
```bash
B 开始当前 episode 的操作和录制
R 结束当前 episode，标记 failure，然后 reset
N 结束当前 episode，标记 success，然后 reset
Ctrl+C 安全关闭文件；未用 R/N 结束的当前 episode 会被废弃
```

#### 2.web可视化数据
```bash
conda activate lerobot05
python3 scripts/view_hdf5_web.py --file datasets/hdf5/lwh_so101_table_leader.hdf5
```
#### 3.数据转换
```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
```
可按训练需求选择使用哪些数据：

```bash
# 默认转换 successful episode，并使用 HDF5 里的 training_camera_keys，通常是 front,wrist
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite

# 只使用 front 单相机训练
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table_front --output_dir datasets/lerobot/so101_table_front --camera_keys front --overwrite

# 使用 front+wrist 双相机训练
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table_dual --output_dir datasets/lerobot/so101_table_dual --camera_keys front,wrist --overwrite

# 转换所有 episode；默认只转换 success
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table_all --output_dir datasets/lerobot/so101_table_all --episodes all --overwrite
```

## 关键参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作、录制、回放建议保持 1。 |
| `--teleop_device` | `keyboard` / 回放 `auto` | `keyboard` 使用键盘；`so101leader` 只读取真实 leader；回放可自动按 HDF5 action 维度选择。 |
| `--camera_mode` | 遥操作/录制 `dual`，回放 `dual` | `front` 只启用前视；`dual` 启用 front+wrist；`triple` 额外启用 overview。录制网页三窗口数据时用 `triple`。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--record` | `False` | 加在 `scripts/teleop.py` 上后进入 HDF5 录制流程。 |
| `--output` | 脚本默认值 | HDF5 输出路径，录制使用。 |
| `--overwrite` | `False` | 输出文件已存在时先删除。 |
| `--append` | `False` | 向已有 HDF5 追加 episode。 |
| `--dataset_file` | `datasets/hdf5/lwh_so101_table_leader.hdf5` | 要回放的 HDF5 文件。 |
| `--episode` | `0` | 回放启动后先加载的 episode index。 |
| `--autoplay` | `False` | 回放启动后立即播放；不传则暂停等待。 |
| `--viewer_layout` | `tri` | IsaacSim 回放 GUI：上排 front+wrist，占约 40%；下排主视角。`isaac` 只保留 Isaac 默认 viewport。 |
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

## 画面参数

```text
front camera: 640 x 480, 30 FPS
wrist camera: 可选，640 x 480, 30 FPS
overview camera: 可选，640 x 480, 30 FPS，仅用于 HDF5/Web 可视化
keyboard action: 8D delta IK + relative pan/gripper
so101leader action: 6D joint position
hdf5 schema root: /data/demo_N and /episodes/000000
metadata/camera_keys: HDF5 中实际录制的相机，例如 front,wrist,overview
metadata/training_camera_keys: 默认进入 LeRobot 的相机，通常只有 front,wrist
lerobot conversion: 默认只转换 success episode，默认跳过 episode 前 5 帧，默认不转换 overview
```

## 异步策略推理

终端一使用 LeRobot 环境启动官方 PolicyServer：

```bash
conda activate lerobot05
python3 scripts/serve_lerobot_policy.py --host 127.0.0.1 --port 8080 --fps 30
```

终端二使用 Isaac 环境启动仿真客户端：

```bash
conda activate isaac
python3 scripts/run_policy_client.py --task Lwh-SO101-Table-v0 --server_address 127.0.0.1:8080 --policy_path checkpoints/act_so101_table_030000 --policy_device cuda --actions_per_chunk 30 --chunk_size_threshold 0.5
```

客户端以 30 Hz 消费本地 action queue，IsaacLab 继续以 60 Hz step；模型推理不会阻塞
仿真主循环。`--policy_path` 是服务端可见的 checkpoint 路径，远程部署时应填写服务器
路径。完整参数见 `docs/async_inference.md`。
