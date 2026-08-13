# HZ Robot Learning

## 当前分支是 `stage_2_1`：键盘+单相机


## 使用方式

进入项目目录并切到本分支：

```bash
cd /home/a/lwh_code/lwh_robot_learning
git checkout stage_2_1
```

启动键盘遥操作：

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
R 重置
N 重置
Ctrl+C 或关闭窗口退出
```

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要启动的 Gym task id。 |
| `--num_envs` | `1` | 仿真环境数量；键盘遥操作建议保持 1。 |
| `--teleop_render_interval` | `1` | 每多少个 physics step 渲染一次。 |
| `--teleop_antialiasing_mode` | 未设置 | 可选覆盖抗锯齿模式。 |
| `--teleop_rendering_mode` | 未设置 | 可选覆盖 IsaacLab 渲染 preset：`performance`、`balanced`、`quality`。 |
| `--quality` | `False` | 画质检查开关，会使用更重的渲染 preset。 |

## 数据契约

```text
front camera: 640 x 480, 30 FPS
keyboard action: 8D delta IK + relative pan/gripper
```
