# HZ Robot Learning

## 当前分支是 `stage_2`：建立遥操作功能

## 标定工具

本分支默认只运行仿真环境，不会自动控制真实 follower；标定脚本仅作为后续接入 SO101 leader/follower 时的辅助工具。

常用检查命令：

```bash
python3 scripts/calibrate_so101.py --arm leader --inspect
python3 scripts/calibrate_so101.py --arm follower --inspect
```

重新标定必须显式添加 `--calibrate` 并在 LeRobot 环境中运行。只有 `--arm follower --calibrate` 会连接真实 follower，普通遥操作和录制流程不会调用它。
