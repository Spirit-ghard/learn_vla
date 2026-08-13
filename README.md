# HZ Robot Learning

## 当前分支是 `stage_2_3`：键盘+双相机+键盘/leader控制


## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_2_3
```

启动遥操作：

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

Leader 模式按键：

```text
B 开始跟随真实 leader
R 失败并重置
N 成功并重置
Ctrl+C 或关闭窗口退出
```

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；遥操作建议保持 1。 |
| `--teleop_device` | `keyboard` | `keyboard` 使用键盘；`so101leader` 只读取真实 leader 并驱动仿真 follower。 |
| `--camera_mode` | `front` | `front` 只启用前视相机；`dual` 启用 front+wrist。 |
| `--ground_mode` | `off` | `off` 移除额外 ground；`on` 保留完整 ground。 |
| `--teleop_render_interval` | `2` | 每多少个 physics step 渲染一次。 |
| `--teleop_antialiasing_mode` | 未设置 | 可选覆盖抗锯齿模式；不传则使用当前默认渲染设置。 |
| `--teleop_rendering_mode` | 未设置 | 可选覆盖 IsaacLab 渲染 preset：`performance`、`balanced`、`quality`。 |
| `--quality` | `False` | 画质检查开关，会使用更重的渲染 preset。 |
| `--leader_port` | `/dev/ttyACM0` | SO101 Leader 串口，只在 `so101leader` 模式使用。 |
| `--leader_calibration` | 未设置 | 显式 leader 标定 JSON；不传时走项目默认解析顺序。 |
| `--leader_id` | 未设置 | 用于查找 LeRobot cache 下的标定文件。 |
| `--leader_start_immediately` | `False` | Leader 模式启动后不等待 `B`，直接跟随 leader。 |
| `--leader_keep_torque` | `False` | 不在连接时关闭 leader 扭矩。 |
| `--leader_skip_handshake` | `False` | 跳过电机 ping 检查。 |

## 标定工具

Leader 模式会读取 leader 标定文件；普通键盘遥操作不访问串口，也不会控制真实 follower。

常用检查命令：

```bash
python3 scripts/calibrate_so101.py --arm leader --inspect
python3 scripts/calibrate_so101.py --arm follower --inspect
```

重新标定必须显式添加 `--calibrate` 并在 LeRobot 环境中运行。`--arm leader --calibrate` 只处理 leader 输入臂；只有 `--arm follower --calibrate` 会连接真实 follower，仿真遥操作入口不会自动调用它。

## 数据契约

```text
front camera: 640 x 480, 30 FPS
wrist camera: 可选，640 x 480, 30 FPS
keyboard action: 8D delta IK + relative pan/gripper
so101leader action: 6D joint position
```
