# 第一阶段验收记录

验收日期：2026-08-05。

## 验收对象

- 自定义 Gym task id：`Lwh-SO101-Table-v0`
- 环境类型：`isaaclab.envs:ManagerBasedRLEnv`
- 场景：SO101 Follower、桌面、红色方块、地面、穹顶灯
- 观测：6 关节位置/速度、前视 RGB、腕部 RGB，以及 LeIsaac 单臂模板的其余观测
- 动作：LeIsaac keyboard 仿真配置，8 维，不创建键盘设备
- 控制周期：`1/60 s`
- 相机：前视和腕部均为 `640 x 480 RGB`、30 FPS

依赖版本和 LeIsaac 终止管理器兼容处理见 `compatibility.md`。

## 实际运行

Headless 长时间步进：

```bash
./scripts/run_stage1_validation.sh \
    --headless \
    --steps 600 \
    --output_dir artifacts/stage1/headless-600
```

结果：通过。600 个控制步等效 10 秒仿真，报告位于
`artifacts/stage1/headless-600/report.json`。

GUI 渲染路径：

```bash
./scripts/run_stage1_validation.sh \
    --steps 120 \
    --output_dir artifacts/stage1/gui-120
```

结果：通过。Isaac Sim 日志确认创建窗口，报告位于
`artifacts/stage1/gui-120/report.json`。

## 验收结果

| 检查项 | 结果 |
| --- | --- |
| Gym 注册和配置解析 | 通过 |
| SO101 六关节名称及顺序 | 通过 |
| 600 步观测 NaN/Inf 检查 | 通过 |
| 机械臂零动作最大漂移 | `7.87e-7 rad` |
| 方块稳定停留在桌面 | 通过，中心 `z=0.05599 m` |
| 方块移位后默认 reset | 通过，恢复至初始位置 |
| 前视相机 | 通过，目标和机械臂均清晰可见 |
| 腕部相机 | 通过，红色方块位于操作视野中央 |
| 腕部光轴/方块方向余弦 | `1.0000`，要求不低于 `0.98` |
| GUI 窗口渲染 | 通过 |
| 验证器失败/成功退出码 | 通过，故意失败返回 `1`，正常运行返回 `0` |

前视和腕部末帧已经人工查看，不仅执行了尺寸和像素方差检查。

## 真实机器人隔离

验收入口只调用 `env_cfg.use_teleop_device("keyboard")` 来生成仿真动作配置，未实例化
`SO101Keyboard`、SO101 Leader/Follower 或 LeRobot motor bus。运行期间未访问
`/dev/tty*`、串口、ROS 节点或真实机器人控制接口。
