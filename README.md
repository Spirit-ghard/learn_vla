# LWH Robot Learning

本项目当前只实现第一阶段：IsaacLab 中的 SO101 桌面仿真任务。
项目不会连接或控制真实机器人，也不依赖 ROS。

## 环境

```bash
conda activate lwh_isaac
cd /home/a/lwh_code/lwh_robot_learning
```

## 运行阶段一验证

Headless 验证：

```bash
./scripts/run_stage1_validation.sh \
    --headless \
    --steps 600 \
    --output_dir artifacts/stage1/headless
```

GUI 验证：

```bash
./scripts/run_stage1_validation.sh \
    --steps 600 \
    --output_dir artifacts/stage1/gui
```

验证脚本会创建 `Lwh-SO101-Table-v0`，检查关节顺序、方块物理状态、
默认重置和两路相机，并保存 JSON 报告与相机图像。

版本组合和已知兼容处理见 [docs/compatibility.md](docs/compatibility.md)，本机实测结果见
[docs/stage1_validation.md](docs/stage1_validation.md)。
