# 第二阶段验收记录

验收日期：2026-08-08。

## 源码依据

实现前核对了当前本地依赖源码，而不是按历史 API 推断：

- LeIsaac `24d3bcd3f1e4585740fc79921782c41617237812`
  - `leisaac/devices/device_base.py`：使用 `carb.input.acquire_input_interface()` 和
    `subscribe_to_keyboard_events()`；`B` 开始，`R/N` 重置。
  - `leisaac/devices/keyboard/so101_keyboard.py`：`SO101Keyboard` 的 8 维键盘增量映射。
  - `scripts/environments/teleoperation/teleop_se3_agent.py`：同进程执行
    `teleop.advance()`、`env.step(action)`，无动作时持续渲染。
  - `tasks/template/single_arm_env_cfg.py`：两路相机为 640 x 480 RGB、30 FPS，
    `use_teleop_device("keyboard")` 初始化键盘动作配置。
- IsaacLab v2.1.1 `90b79bb2d44feb8d833f260f2bf37da3487180ba`
  - 使用 `AppLauncher`、`parse_env_cfg()` 和 `gym.make(...).unwrapped` 创建已注册的
    `ManagerBasedRLEnv`。
- Isaac Sim 自带 `omni.kit.ui_test.input`
  - 官方 UI 测试通过 `carb.input.InputProvider.buffer_keyboard_key_event()` 注入键盘事件。

完整版本组合见 `compatibility.md`。

## 已实现行为

通用入口：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

- 常用参数为 `--task` 和 `--num_envs`；另保留 `--teleop_render_interval`、
  `--teleop_antialiasing_mode` 和 `--teleop_rendering_mode` 用于调画质/帧率。
- 使用本项目内基于 Isaac Sim Carb 输入事件重写的 `SO101Keyboard`，运行时不导入
  `leisaac` Python 包。
- `B` 开始；`W/S/A/D/Q/E/J/L/K/I/U/O` 控制机械臂和夹爪。
- `R` 以失败结果重置，`N` 以成功结果重置。
- 开始前 `action is None` 时调用 `env.sim.render()`，窗口事件不会阻塞。
- 正常入口没有 `--steps`，会持续运行到关闭窗口或按 `Ctrl+C`。
- 禁用自动超时，episode 只由 `R/N` 显式结束。
- 默认仿真动作/物理步长为 60 Hz；两路 30 FPS 相机每两个物理步渲染一次。
- 默认使用 IsaacLab `quality` 渲染预设，并把抗锯齿固定为 `FXAA`；
  相机仍保持 30 FPS，避免 DLSS 上采样带来的发虚感。

## 自动验证

执行命令：

```bash
python3 scripts/validate_teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
```

验证器与正常入口运行同一套代码，只额外设置测试环境变量。事件通过 Kit 官方
`InputProvider.buffer_keyboard_key_event()` 进入 Carb 事件队列，再由
`SO101Keyboard` 的真实订阅回调处理；没有直接调用其私有回调或修改内部动作状态。

事件序列为：`B`、`D`、`R`、`B`、`U`、`N`，包含按下和释放。最终结果：

| 检查项 | 实测结果 |
| --- | --- |
| 验证进程退出码 | `0` |
| `B` 开始次数 | `2` |
| 控制步数 | `140` |
| `R/N` 生命周期 | `failure`、`success`，顺序正确 |
| 仿真机器人最大关节位移 | `1.919874 rad` |
| 仿真控制频率 | `60 Hz` |
| 相机渲染频率 | `30 Hz` |
| 首个连续控制段墙钟频率 | `12.48 Hz`（相机和着色器预热） |
| 第二个连续控制段墙钟频率 | `13.53 Hz` |
| 完整序列墙钟吞吐 | `11.55 Hz` |
| 前视图像 | `1 x 480 x 640 x 3 uint8`，像素标准差 `52.07` |
| 腕部图像 | `1 x 480 x 640 x 3 uint8`，像素标准差 `20.81` |

报告位于 `artifacts/stage2/report.json`。墙钟吞吐包含开始前等待、两次 reset 和双 RTX
相机读取；限速器目标及仿真时间步为 60 Hz，但 RTX 3060 Laptop 在该完整 GUI
负载下不能保证墙钟 60 Hz。IsaacLab 的 `PARTIAL_RENDERING` 会隐藏主视口，关闭 RTX
渲染则会停止相机更新，因此这里保留窗口和相机数据完整性，没有通过关闭功能虚报
实时性能。

## 真实机器人隔离

遥操作和验证入口只创建仿真环境与本项目 `SO101Keyboard`。代码不导入 LeRobot motor bus、
串口、ROS、`leisaac` Python 包或 SO101 Leader，未访问 `/dev/tty*`。Python bootstrap 还会从子进程环境中
移除 `/opt/ros` 和 `soarm_ros` 路径。本次所有验证均只驱动 Isaac Sim 中的 SO101。
