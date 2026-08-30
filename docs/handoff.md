# Handoff

更新时间：2026-08-30

## 当前交接状态

当前分支：

```text
stage_4
```

当前远端：

```text
origin git@github.com:Spirit-ghard/learn_vla.git
```

## 已完成

- Stage 1：`Lwh-SO101-Table-v0` SO101 桌面方块任务。
- Stage 2：键盘遥操作、单/双相机可选、真实 SO101 Leader 输入只驱动仿真。
- Stage 3：`teleop.py --record` HDF5 录制、Ctrl+C 废弃未结束 episode、HDF5 转 LeRobotDataset v3。
- Stage 4：HDF5 回放入口，支持 episode 切换、暂停、继续、单步和退出。
- Stage 4：回放 GUI 默认 `--viewer_layout tri`，上排显示 front+wrist，占约 40%；下排显示主视角。
- 标定工具：`scripts/calibrate_so101.py` 支持 `--arm leader|follower` 的检查、导入和 LeRobot 标定；旧 `calibrate_so101_leader.py` 作为兼容入口保留。
- Stage 6：LeRobot 官方风格异步 PolicyServer、action chunk、本地 action queue 和 IsaacLab 仿真客户端已完成本机端到端验证。

## 当前可用命令

场景运行：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0
```

录制 HDF5：

```bash
python3 scripts/teleop.py --record --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --output datasets/hdf5/lwh_so101_table_leader.hdf5
```

转换 LeRobotDataset v3：

```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table_leader.hdf5 --repo_id lwh/so101_table_leader --output_dir datasets/lerobot/so101_table_leader --overwrite
```

回放 HDF5：

```bash
python3 scripts/replay_hdf5.py --task Lwh-SO101-Table-v0 --dataset_file datasets/hdf5/lwh_so101_table_leader.hdf5
```

只保留 Isaac 默认 viewport：

```bash
python3 scripts/replay_hdf5.py --task Lwh-SO101-Table-v0 --dataset_file datasets/hdf5/lwh_so101_table_leader.hdf5 --viewer_layout isaac
```

标定检查：

```bash
python3 scripts/calibrate_so101.py --arm leader --inspect
python3 scripts/calibrate_so101.py --arm follower --inspect
```

LeRobot 环境中重新标定：

```bash
conda activate lerobot05
python3 scripts/calibrate_so101.py --arm leader --calibrate --port /dev/ttyACM0 --output configs/so101_leader_calibration.json
python3 scripts/calibrate_so101.py --arm follower --calibrate --port /dev/ttyACM1 --output configs/so101_follower_calibration.json
```

异步策略服务端：

```bash
conda activate lerobot05
python3 scripts/serve_lerobot_policy.py --host 127.0.0.1 --port 8080 --fps 30
```

异步仿真客户端：

```bash
conda activate isaac
python3 scripts/run_policy_client.py --task Lwh-SO101-Table-v0 --server_address 127.0.0.1:8080 --policy_path checkpoints/act_so101_table_030000 --policy_device cuda --actions_per_chunk 30 --chunk_size_threshold 0.5
```

## 注意事项

- 不要直接从 LeIsaac import 任务、模板或设备。
- 不要启动 ROS。
- 仿真流程不得控制真实 follower；follower 标定脚本只有用户明确运行 `--arm follower --calibrate` 时才会连接真实 follower。
- 不要新增 shell 启动脚本。
- 内部验证产物不要保留在仓库里。
- Stage 3 HDF5 使用 `/data/demo_N` 和 `/episodes/000000` 两套入口；`/episodes` 是硬链接。
- 转换脚本默认只转换成功 episode、跳过前 5 帧、输出 LeRobot image 格式。
- 当前项目默认 leader 标定文件为 `configs/so101_leader_calibration.json`，来源是本机 LeIsaac cache，已内置到仓库。

## 下一步建议

下一步进入 Stage 5 LeRobot 训练：

- 在 LeRobot 环境中加载转换后的 dataset。
- 确认 joint 顺序、单位、图像尺寸和 FPS。
- 先用小数据跑通 ACT 训练配置。
- 保存 checkpoint 和归一化统计。
- 暂不引入 IsaacLab 远程推理，Stage 6 再做 policy client/server。
