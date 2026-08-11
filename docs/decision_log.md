# Decision Log

本文档记录关键技术决策、原因和后续影响。新对话接手时应先阅读。

## 2026-08-08：以 IsaacLab 为运行基础，不直接依赖 LeIsaac

决策：

- 项目运行时不直接 import `leisaac`。
- LeIsaac 只作为源码参考；SO101 USD 已复制到项目包目录。

原因：

- 用户明确要求以 IsaacLab 为基础，不能直接从 LeIsaac 库引用任务、设备、模板。
- 直接依赖 LeIsaac 会把 LeIsaac 的 monkey patch、增强 recorder、任务模板等运行时行为引入本项目，影响边界清晰度。

影响：

- 自行实现 `SO101Keyboard`、SO101 task cfg、MDP 函数和动作预处理。
- `scripts/isaac_runtime.py` 不把 `dependencies/leisaac/source/leisaac` 加入 `PYTHONPATH`。
- 默认 SO101 USD 来源改为项目内置资产。

## 2026-08-08：所有入口使用 Python bootstrap，不使用 shell 脚本

决策：

- 所有正式入口都是 Python 脚本。
- 不新增 `.sh` 启动脚本。

原因：

- 用户要求“现在以及后续都改为 python 脚本”。
- Isaac Sim/IsaacLab 环境变量复杂，统一放在 `scripts/isaac_runtime.py` 中可减少手动 source 依赖。

影响：

- 入口先调用 `ensure_isaac_runtime()`。
- 默认使用当前已激活 Python；如果当前 Python 低于 3.10，会尝试常见的 `lwh_isaac` conda 环境；需要跨环境重执行时通过 `LWH_ISAAC_PYTHON` 显式指定。
- 验证脚本可通过 supervisor 模式得到可靠退出码。

## 2026-08-08：不控制真实 follower

决策：

- 本项目只做仿真，不控制真实 SO101 follower。
- Stage 2.3 允许显式读取真实 SO101 Leader 作为输入设备，但动作只发送给 IsaacLab 仿真环境。

原因：

- 用户说明真实机器人已连接，但要求不要控制真实机器人。
- 当前目标是 IsaacLab 仿真学习流程，真实机器人不在范围内。

影响：

- 不启动 ROS。
- 默认键盘仿真不访问 `/dev/tty*`。
- `--teleop_device so101leader` 只读取 leader 串口位置，不控制真实 follower。
- 不使用 LeRobot real robot API 控制真实机器人。
- 外部 ROS/真实机器人工程只作为名称和历史信息参考，不进入运行时。

## 2026-08-08：Stage 1 使用 ManagerBasedRLEnvCfg 组合任务

决策：

- 自定义 `LwhSO101TableEnvCfg` 继承 `ManagerBasedRLEnvCfg`。
- 通过 scene/action/observation/event/termination cfg 组合环境。
- 通过 `gym.register()` 注册 `Lwh-SO101-Table-v0`。

原因：

- IsaacLab 官方推荐通过配置类组合 manager-based RL environment。
- 任务文件应独立于通用入口。

影响：

- 不修改 IsaacLab 环境基类。
- 后续新增任务只新增任务模块，不修改 teleop/record/replay 通用入口。

## 2026-08-08：相机数据底线为 640x480 @ 30Hz

决策：

- 当前 `front` 和 `wrist` 相机默认 `640 x 480 @ 30 FPS`。

原因：

- LeRobot/LeIsaac SO101 教程中的常见相机配置为 `640x480/640x360` 量级和 `30 FPS`。
- VLA/ACT 类模型更依赖可辨识物体、夹爪和目标区域，不应过早牺牲清晰度。

影响：

- 不默认降到 320x240。
- 性能调优优先减少不必要渲染负载、相机数量、窗口刷新，而不是先降低图像质量。

## 2026-08-09：Stage 2 默认对齐 LeIsaac 渲染路径

决策：

- 默认不强制 `quality + FXAA`。
- 默认使用 Isaac/Kit 渲染设置，实测为 `DLSS balanced`。
- 保留 `--quality` 作为画质检查选项。

原因：

- LeIsaac `LiftCube` 默认不启用 `--quality`。
- 强制更重的 quality preset 会降低遥操作流畅度。

影响：

- `scripts/teleop.py` 默认保持 LeIsaac 风格轻量路径。
- 需要画质检查时再显式 `--quality`。

## 2026-08-09：Stage 2 支持单/双相机可选

决策：

- `scripts/teleop.py` 新增 `--camera_mode front|dual`。
- 默认值为 `front`，`dual` 作为显式可选项。

原因：

- 用户需要可选单相机或双相机，以评估质量和流畅度平衡。
- LeIsaac `LiftCube` 实际只启用 `front`，本项目需要保留未来双相机数据能力。

影响：

- `front` 模式运行时删除 `wrist` scene asset 和 observation term。
- `dual` 模式保留 `front + wrist`，但当前机器 GUI 吞吐低于单相机。

## 2026-08-10：Stage 2.3 新增真实 SO101 Leader 输入

决策：

- 新增 `SO101LeaderArm` 和最小 `SO101LeaderBus`，通过 Feetech/STS3215 串口读取真实 leader 位置。
- `--teleop_device so101leader` 时，任务动作空间切换为 6D `JointPositionActionCfg`。
- Leader 归一化读数映射到仿真 SO101 follower 的关节角范围。
- 运行时不 import `leisaac`，也不 import LeRobot。

原因：

- 用户已经跑通 LeIsaac 的真实 leader 控制仿真流程，希望本项目按 IsaacLab 基础重写。
- LeIsaac 可作为源码参考，但用户明确要求不能直接从 LeIsaac 库引用。
- 本机 LeRobot 源码为 `0.5.1`，要求 Python `>=3.12`；Isaac Sim 4.5 / IsaacLab 当前环境是 Python `3.10.20`，不能直接把 LeRobot 0.5.1 导入 Isaac 进程。

影响：

- Leader 串口读取使用 `scservo_sdk` 的 `GroupSyncRead(Present_Position)`。
- 默认校准路径查找顺序：`--leader_calibration`、`LWH_SO101_LEADER_CALIBRATION`、项目 `configs/so101_leader_calibration.json`、LeRobot cache、LeIsaac cache。
- 默认连接时关闭 leader 扭矩，让 leader 作为被动输入设备；可用 `--leader_keep_torque` 禁止该写入。
- 该模式仍不控制真实 follower，不启动 ROS，不访问外部 ROS 工程。

## 2026-08-11：Stage 1/2 资产内置到项目目录

决策：

- 将 `so101_follower.usd` 复制到 `source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/robots/`。
- `LWH_SIM_ASSETS_ROOT` 未设置时，默认使用项目内置资产目录。
- `scripts/isaac_runtime.py` 不再默认绑定本机 Isaac Python 绝对路径，而是使用当前启动脚本的 Python。
- Isaac Sim 根目录优先读取 `LWH_ISAAC_SIM_ROOT` 或 `ISAAC_PATH`。

原因：

- 用户要求仓库文件夹可以搬到另一台已装好环境的机器直接使用。
- 之前 Stage 1 资产默认来自 LeIsaac 安装目录，移动仓库后会丢失。

影响：

- Stage 1 场景不再依赖 LeIsaac 资产目录。
- 如果目标机器 Isaac Sim 不在常见位置，需要设置 `LWH_ISAAC_SIM_ROOT` 或 `ISAAC_PATH`。
- 如果目标机器当前 `python3` 不是 Isaac 环境，需要设置 `LWH_ISAAC_PYTHON`。

## 2026-08-09：Stage 2 teleop 默认关闭额外 ground plane

决策：

- `scripts/teleop.py` 新增 `--ground_mode off|on`。
- 默认 `off`。
- task 配置本身仍保留 ground。

原因：

- LeIsaac `LeIsaac-SO101-LiftCube-v0` 桌面任务没有本项目额外 20m ground plane。
- GUI 性能消融显示，ground 是本项目低于 LeIsaac 的主要原因。

实测：

| Case | Ground | Wall loop Hz |
| --- | --- | ---: |
| LeIsaac 单相机 | 无额外 ground | 30.45 |
| LWH 原单相机 | on | 25.72 |
| LWH 单相机优化后 | off | 32.16 |
| LWH 原双相机 | on | 20.56 |
| LWH 双相机优化后 | off | 25.68 |

影响：

- 正式遥操作默认使用 `ground_mode=off`，对齐 LeIsaac GUI 性能。
- 如果需要完整地面，可以显式 `--ground_mode on`。
- Stage 1 任务配置仍可验证 ground 存在；Stage 2 入口按性能需要运行时移除。

## 2026-08-10：Stage 2 teleop 默认改为 `render_interval=2`

决策：

- 默认 `render_interval=2`，即 60 Hz 控制目标配 30 Hz 图像/渲染更新。
- 主动控制时，限速等待阶段不再额外调用完整 `env.sim.render()`；等待 B 开始或 reset 后仍渲染，以保证窗口和键盘事件可用。

原因：

- 实测表明 Stage 1 纯环境 headless 单相机可超过 60 Hz，瓶颈主要来自 GUI/viewport/相机同步。
- 旧循环在 `RateLimiter.sleep()` 中额外渲染，会抵消 `render_interval=2` 的收益。
- VLA/ACT 数据更需要清晰稳定的 30 FPS 图像、可靠 timestamp 和动作对齐，而不是 60 FPS 图像。

影响：

- 单相机遥操作成为默认高频采集基线，目标是接近 60 Hz 控制、30 Hz 图像。
- 双相机 GUI 遥操作仍明显更重，不承诺 60 Hz 控制；需要双相机时应记录真实 timestamp，并在 LeRobot 转换阶段统一重采样。

## 2026-08-09：Stage 3 优先 HDF5，再转 LeRobotDataset

决策：

- Stage 3 使用独立 Isaac 入口 `scripts/record_hdf5.py` 录制 HDF5。
- Stage 3 使用独立 LeRobot 入口 `scripts/convert_hdf5_to_lerobot.py` 转换 LeRobotDataset v3。
- 暂不在 IsaacLab 仿真环境内直接依赖 LeRobot。

原因：

- 减少 IsaacLab 环境和 LeRobot 训练环境的依赖耦合。
- LeIsaac 官方流程也支持先录 HDF5，再转换。
- 本机 LeRobot 0.5.1 要求 Python `>=3.12`，IsaacSim/IsaacLab 运行环境是 Python `3.10.20`。

影响：

- Isaac 进程只 import IsaacLab/h5py，不 import LeRobot。
- 转换脚本只 import h5py/LeRobot，不启动 IsaacSim。
- HDF5 主结构采用 `/data/demo_N`，同时提供 `/episodes/000000` 硬链接。
- 每帧写入 `observation/state`、`observation/images/*`、`action`、`timestamp`、`episode_index`、`frame_index`、`task`。
- episode 按 `B` 开始录制，`R` 标记失败结束，`N` 标记成功结束。
- LeRobot 转换默认只转换成功 episode，并跳过前 5 帧。

## 2026-08-11：LeRobot 转换默认使用 image 格式

决策：

- `scripts/convert_hdf5_to_lerobot.py` 默认 `--image_format image`。
- 保留 `--image_format video` 作为显式选项。

原因：

- 本机 LeRobot 0.5.1 环境可以成功写出 video dataset，但默认加载路径会走 `torchcodec`。
- 当前 `torchcodec` 与 FFmpeg 动态库链路不完整，直接 `LeRobotDataset(...)` 读取 video 会失败。
- 显式 `video_backend="pyav"` 可以读取已写出的 video dataset。
- image 格式占用空间更大，但当前本机可直接加载，更适合作为第一版稳定转换默认值。

影响：

- 后续训练可以先使用 image 格式数据集，避免 video decoder 阻塞训练验证。
- 需要节省磁盘时可显式转换 `--image_format video`，并在 LeRobot 加载/训练配置中指定 `pyav` 或修复 torchcodec/FFmpeg。

## 术语说明：Wall loop Hz 和 Control segment Hz

`Wall loop Hz`：

- 按真实墙钟时间计算，主循环每秒实际完成多少轮。
- 包含键盘处理、env.step、env.sim.render、窗口刷新、相机读取、Python 调度和等待。

`Control segment Hz`：

- 只统计实际有 action 时的 `env.step(action)` 段。
- 更接近遥操作动作实际刷新频率。

配置值和实测值不同：

```text
control_hz = 60      配置目标
camera_hz = 30       相机目标
Wall loop Hz         GUI 主循环实际吞吐
Control segment Hz   有动作时实际 step 频率
```

当前判断：

- 单相机 `ground_mode=off` 已达到 LeIsaac 单相机 GUI 水平。
- 双相机由于多一路 TiledCamera，不应期望达到 LeIsaac 单相机同等吞吐。
