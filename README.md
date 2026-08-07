# LWH Robot Learning

本项目当前实现第一阶段 SO101 桌面仿真任务和第二阶段键盘遥操作。
项目不会连接或控制真实机器人，也不依赖 ROS。

## 环境

```bash
cd /home/a/lwh_code/lwh_robot_learning
```

所有运行入口均为 Python 脚本，并会自动切换到固定的 `lwh_isaac` 解释器。项目现在及
后续阶段不提供 shell wrapper。

## 持续运行

打开 GUI 并持续运行，直到关闭 Isaac Sim 窗口或在终端按 `Ctrl+C`：

```bash
python3 scripts/run_env.py
```

可选择其他已注册任务或环境数量：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

该入口以约 60 Hz 持续执行零动作，只用于查看和运行仿真环境，不响应遥操作按键。

## 键盘遥操作

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

窗口打开后按 `B` 开始控制。运动键：`W/S` 前后、`Q/E` 上下、`A/D` 肩部左右、
`I/K/J/L` 旋转、`U/O` 打开或闭合夹爪。`R` 重置并标记失败，`N` 重置并标记成功；
关闭窗口或在终端按 `Ctrl+C` 退出。

键盘遥操作建议始终使用 `--num_envs 1`。该入口只实例化本项目内基于 Carb 事件重写的
`SO101Keyboard`，不会连接真实 SO101。正常遥操作没有步数上限，会持续运行到主动退出。

可以直接调这两个参数找平衡点：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_render_interval 2
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_render_interval 3
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_antialiasing_mode FXAA
```

建议底线：
- `640x480` 双相机不变。
- 控制/物理步长保持 `60 Hz`。
- 录数据时相机至少 `20 Hz`，`30 Hz` 更稳。
- 如果遥控明显卡顿，先把 `render_interval` 提到 `3`，也就是 `20 Hz`。
- 再不够就用 `4`，也就是 `15 Hz`，但不建议长期低于这个档。
- 画质优先用 `FXAA`；`DLSS` 更省，但更容易让图像发软。

阶段二自动验证会打开 GUI，通过 Isaac Sim 官方 Carb 输入缓冲接口模拟完整按键序列，
验证结束后自行退出：

```bash
python3 scripts/validate_teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

验证报告写入 `artifacts/stage2/report.json`。该脚本只向仿真窗口注入键盘事件，不访问
真实机器人。

## 运行阶段一验证

Headless 验证：

```bash
python3 scripts/validate_env.py \
    --headless \
    --steps 6000 \
    --output_dir artifacts/stage1/headless
```

GUI 验证：

```bash
python3 scripts/validate_env.py \
    --steps 6000 \
    --output_dir artifacts/stage1/gui
```

验证脚本会创建 `Lwh-SO101-Table-v0`，检查关节顺序、方块物理状态、
默认重置和两路相机，并保存 JSON 报告与相机图像。

版本组合和源码参考范围见 [docs/compatibility.md](docs/compatibility.md)，本机实测结果见
[docs/stage1_validation.md](docs/stage1_validation.md) 和
[docs/stage2_validation.md](docs/stage2_validation.md)。
