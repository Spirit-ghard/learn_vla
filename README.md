# LWH Robot Learning

本项目当前只实现第一阶段：IsaacLab 中的 SO101 桌面仿真任务。
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

版本组合和已知兼容处理见 [docs/compatibility.md](docs/compatibility.md)，本机实测结果见
[docs/stage1_validation.md](docs/stage1_validation.md)。
