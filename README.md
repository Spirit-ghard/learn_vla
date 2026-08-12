# HZ Robot Learning

## 六阶段

```text
1. 搭建整体框架和场景，可通过 --task 切换任务。
2. 建立遥操作功能，可选键盘或 leader arm 控制仿真。
3. 采集数据，默认输出 HDF5，并转换为 LeRobotDataset。
4. 轨迹可以在 sim 中回放。
5. 搭建服务器训练环境，完成模型训练。
6. 服务器推理，本地仿真执行。
```

## 使用方式

进入项目目录：

```bash
cd /home/a/lwh_code/lwh_robot_learning
```

常用启动方式：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
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

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作建议保持 1。 |
| `--camera_mode` | `front` | `front` 只启用前视相机；`dual` 启用 front+wrist。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--teleop_render_interval` | `2` | 每多少个 physics step 渲染一次。 |
| `--teleop_antialiasing_mode` | 未设置 | 可选覆盖抗锯齿模式；不传则使用当前默认渲染设置。 |
| `--teleop_rendering_mode` | 未设置 | 可选覆盖 IsaacLab 渲染 preset：`performance`、`balanced`、`quality`。 |
| `--quality` | `False` | 画质检查开关，会使用更重的渲染 preset。 |

## 数据契约

```text
front camera: 640 x 480, 30 FPS
wrist camera: 可选，640 x 480, 30 FPS
keyboard action: 8D delta IK + relative pan/gripper
```
