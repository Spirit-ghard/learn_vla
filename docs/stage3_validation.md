# Stage 3 Validation

验证日期：2026-08-11。

## 环境

```text
Isaac Sim: 4.5.0
IsaacLab: v2.1.1 / package 0.41.3
Isaac Python: 3.10.20
LeRobot: 0.5.1
LeRobot Python: 3.12.13
GPU: NVIDIA GeForce RTX 3060 Laptop, 6 GiB
```

## 验证命令

HDF5 单相机录制：

```bash
conda run -n isaac python scripts/validate_record_hdf5.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode front \
  --ground_mode off \
  --device cuda
```

HDF5 双相机录制：

```bash
conda run -n isaac python scripts/validate_record_hdf5.py \
  --task Lwh-SO101-Table-v0 \
  --num_envs 1 \
  --camera_mode dual \
  --ground_mode off \
  --device cuda \
  --output artifacts/stage3/record_validation_dual.hdf5
```

LeRobot image 转换和加载：

```bash
conda run -n lerobot05 python scripts/convert_hdf5_to_lerobot.py \
  --input artifacts/stage3/record_validation.hdf5 \
  --repo_id lwh/stage3_validation \
  --output_dir artifacts/stage3/lerobot_validation \
  --image_format image \
  --overwrite
```

LeRobot 双相机 image 转换和加载：

```bash
conda run -n lerobot05 python scripts/convert_hdf5_to_lerobot.py \
  --input artifacts/stage3/record_validation_dual.hdf5 \
  --repo_id lwh/stage3_validation_dual \
  --output_dir artifacts/stage3/lerobot_validation_dual \
  --image_format image \
  --overwrite
```

LeRobot video 转换：

```bash
conda run -n lerobot05 python scripts/convert_hdf5_to_lerobot.py \
  --input artifacts/stage3/record_validation.hdf5 \
  --repo_id lwh/stage3_validation_video \
  --output_dir artifacts/stage3/lerobot_validation_video \
  --image_format video \
  --overwrite
```

## 结果

- 单相机 HDF5 写入 2 个 episode：第 0 集 success，第 1 集 failure。
- 双相机 HDF5 写入 2 个 episode：第 0 集 success，第 1 集 failure。
- HDF5 路径存在 `/data/demo_N` 和 `/episodes/000000`。
- `observation/state` shape 为 `(frames, 6)`。
- `action` 在键盘验证中 shape 为 `(frames, 8)`。
- 单相机 `front` shape 为 `(frames, 480, 640, 3)`。
- 双相机 `front/wrist` shape 均为 `(frames, 480, 640, 3)`。
- `initial_state/articulation/robot/root_pose` shape 为 `(1, 7)`。
- `initial_state/rigid_object/cube/root_pose` shape 为 `(1, 7)`。
- LeRobot image 单相机转换成功，加载后 `num_episodes=1`、`num_frames=67`。
- LeRobot image 双相机转换成功，加载后同时存在 `observation.images.front` 和 `observation.images.wrist`。
- LeRobot video 转换可写出 AV1 mp4；默认 torchcodec 读取因本机 FFmpeg 动态库链路失败，显式 `video_backend="pyav"` 可读取。

## 结论

Stage 3 达到可用状态：Isaac 端可录制 HDF5，训练端可在 LeRobot 0.5.1 环境中转换为 LeRobotDataset v3。

当前正式默认建议：

```text
录制：HDF5
转换：LeRobot image 格式
默认采集：单相机 front
需要双相机时：显式 --camera_mode dual
需要关节策略训练时：优先用 --teleop_device so101leader 采集 6D action
```
