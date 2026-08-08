# 第一阶段验收记录

验收日期：2026-08-08。

## 验收对象

- 自定义 Gym task id：`Lwh-SO101-Table-v0`
- 环境类型：`isaaclab.envs:ManagerBasedRLEnv`
- 场景：SO101 Follower、桌面、红色方块、地面、穹顶灯
- 观测：6 关节位置/速度、前视 RGB、腕部 RGB、末端状态和上一帧动作
- 动作：本项目按 IsaacLab `DifferentialInverseKinematicsActionCfg` 重写的 keyboard 仿真配置，8 维，不创建键盘设备
- 控制周期：`1/60 s`
- 相机：前视和腕部均为 `640 x 480 RGB`、30 FPS

依赖版本和 LeIsaac 参考范围见 `compatibility.md`。

## 实际运行

Headless 长时间步进：

```bash
python3 scripts/validate_env.py \
    --headless \
    --steps 600 \
    --output_dir artifacts/stage1/headless-isaaclab-only-600
```

结果：通过。600 个控制步等效 10 秒仿真，报告位于
`artifacts/stage1/headless-isaaclab-only-600/report.json`。

GUI 渲染路径：

```bash
python3 scripts/validate_env.py \
    --steps 120 \
    --output_dir artifacts/stage1/gui-120
```

结果：通过。Isaac Sim 日志确认创建窗口，报告位于
`artifacts/stage1/gui-120/report.json`。

GUI 持续运行入口：

```bash
python3 scripts/run_env.py
```

结果：通过。入口不设置步数上限，实测保持运行直至发送 `Ctrl+C`，随后正常清理并以
退出码 `0` 结束。

上述命令均从未激活 Conda 且包含 ROS 环境变量的普通 shell 中执行。Python bootstrap
成功切换到固定的 Python 3.10 环境并移除 ROS/`soarm_ros` 搜索路径。

## 验收结果

| 检查项 | 结果 |
| --- | --- |
| Gym 注册和配置解析 | 通过 |
| SO101 六关节名称及顺序 | 通过 |
| 600 步观测 NaN/Inf 检查 | 通过 |
| 机械臂零动作最大漂移 | `7.87e-7 rad` |
| 方块稳定停留在桌面 | 通过，中心 `z=0.06000 m` |
| 方块移位后默认 reset | 通过，恢复至初始位置 |
| 前视相机 | 通过，目标和机械臂均清晰可见 |
| 腕部相机 | 通过，红色方块位于操作视野中央 |
| 腕部光轴/方块方向余弦 | `0.9961`，要求不低于 `0.98` |
| GUI 窗口渲染 | 通过 |
| 无步数持续运行及 `Ctrl+C` 清理 | 通过 |
| 验证器失败/成功退出码 | 通过，故意失败返回 `1`，正常运行返回 `0` |

前视和腕部末帧已经人工查看，不仅执行了尺寸和像素方差检查。

## 真实机器人隔离

验收入口只调用 `env_cfg.use_teleop_device("keyboard")` 来生成仿真动作配置，未实例化
真实机器人设备、SO101 Leader/Follower 或 LeRobot motor bus。运行期间未访问
`/dev/tty*`、串口、ROS 节点或真实机器人控制接口。
