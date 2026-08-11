# Stage Status

本文档记录每个阶段的目标、当前实现、启动方式和验证状态。

## 分支现状

| 分支 | 作用 | 当前说明 |
| --- | --- | --- |
| `main` | 远端主线 | 暂未更新到本地最新阶段分支 |
| `stage_1` | 第一阶段最小场景 | 已完成 |
| `stage_2` | 第二阶段单相机 LeIsaac 风格基线 | 已完成，过程版本 |
| `stage_2_1` | 第二阶段过程版本 | 已完成，过程版本 |
| `stage_2_2` | 第二阶段键盘遥操作封存版 | 已完成，支持单/双相机和 ground 性能 profile |
| `stage_2_3` | 第二阶段真实 Leader 版 | 已完成，新增真实 SO101 Leader 输入控制仿真 |
| `stage_3` | 第三阶段数据录制 | 已完成，HDF5 录制和 HDF5 到 LeRobotDataset v3 转换 |

已删除本地历史分支：

```text
dev_1
dev_2
stage_4
stage_5
stage_6
```

注意：远端是否还保留这些历史分支需用 `git branch -r` 另行确认。

## Stage 1：任务环境

状态：已完成。

对应分支：

```text
stage_1
```

目标：

- 创建 IsaacLab ManagerBasedRLEnv 任务。
- 注册 `Lwh-SO101-Table-v0`。
- 包含 SO101 Follower、ground、桌子、方块、灯光、front camera、wrist camera。
- 提供关节状态、相机图像、末端状态、上一帧 action 观测。
- 提供默认 reset event。

关键文件：

```text
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/tasks/so101_table/__init__.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/tasks/so101_table/so101_table_env_cfg.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/tasks/so101_table/mdp.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/so101.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/robots/so101_follower.usd
scripts/run_env.py
```

正式启动：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

验证过的内容：

- task id 可由 gym registry 识别。
- 环境可创建、reset、step。
- cube reset 后回到初始位置。
- front/wrist 相机张量为 `640 x 480 x 3`，非空白。
- 关节顺序为 SO101 契约顺序。

记录：

```text
docs/stage1_validation.md
docs/compatibility.md
```

## Stage 2：遥操作

状态：已完成。

对应分支：

```text
stage_2_2: 键盘遥操作封存版
stage_2_3: 当前版本，新增真实 SO101 Leader 输入
```

目标：

- 创建通用键盘遥操作入口。
- 参数保留核心任务选择和环境数量，并支持性能调试项。
- 使用 `AppLauncher` 启动 Isaac Sim。
- 导入任务注册模块。
- `parse_env_cfg(task)` 后按 `--teleop_device` 调用 `env_cfg.use_teleop_device(...)`。
- `gym.make(task, cfg=env_cfg).unwrapped` 创建环境。
- `SO101Keyboard(env)` 使用 Carb/Omniverse 键盘事件回调。
- `SO101LeaderArm(env)` 读取真实 SO101 Leader 关节位置，只驱动仿真 follower。
- 主循环执行 `teleop.advance()`、`env.step(action)` 和等待时 `env.sim.render()`。

关键文件：

```text
scripts/teleop.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/devices/so101_keyboard.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/devices/so101_leader.py
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets/so101_constants.py
```

正式启动：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0
```

关键参数：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | Gym task id |
| `--num_envs` | `1` | 仿真环境数量，键盘遥操作建议 1 |
| `--teleop_device` | `keyboard` | `keyboard` 使用 Carb 键盘；`so101leader` 读取真实 leader 串口控制仿真 |
| `--camera_mode` | `front` | `front` 只保留前视并作为高频遥操作基线；`dual` 保留 front+wrist |
| `--ground_mode` | `off` | teleop 默认移除额外 ground，对齐 LeIsaac GUI 性能 |
| `--teleop_render_interval` | `2` | 每多少个 physics step 渲染一次；默认目标为 60 Hz 控制、30 Hz 图像/渲染 |
| `--teleop_antialiasing_mode` | unset | 可选覆盖 AA |
| `--teleop_rendering_mode` | unset | 可选覆盖 rendering preset |
| `--quality` | false | 对齐 LeIsaac `--quality`，启用 `FXAA + quality` |
| `--leader_port` | `/dev/ttyACM0` | SO101 Leader 串口，只在 `so101leader` 模式使用 |
| `--leader_calibration` | unset | 显式 leader 校准 JSON；不传时查环境变量、项目 configs、LeRobot cache、LeIsaac cache |
| `--leader_id` | unset | 用于查找 LeRobot cache 下的校准文件 |
| `--leader_start_immediately` | false | 不等待 B，启动后直接跟随 leader |
| `--leader_keep_torque` | false | 不在连接时关闭 leader 扭矩 |
| `--leader_skip_handshake` | false | 跳过电机 ping 检查 |

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

验证过的内容：

- GUI 可创建窗口并处理 Carb 键盘事件。
- `B` 可以开始控制。
- `D` 和 `U` 可以产生非零动作并移动机器人。
- `R` 触发失败 reset。
- `N` 触发成功 reset。
- 单相机和双相机模式均可创建、step、出图。
- `--ground_mode on` 可恢复完整 ground 并正常运行。
- 默认 `--ground_mode off` 与 `--teleop_render_interval 2` 用于提高单相机遥操作控制频率。
- `/dev/ttyACM0` 上真实 SO101 Leader 可握手 6 个 STS3215 电机并读取校准后位置。
- `--teleop_device so101leader` 可创建仿真环境，动作空间为 6D joint position，并持续驱动仿真 SO101 follower。
- Leader 模式只读取真实 leader 作为输入，不控制真实 follower，不启动 ROS。

性能数据：

| Case | Ground | Wall loop Hz | Control segment Hz |
| --- | --- | ---: | --- |
| LeIsaac 单相机 | 无额外 ground | 30.45 | 27.09 / 32.04 |
| LWH 原单相机 | on | 25.72 | 23.46 / 26.78 |
| LWH 原双相机 | on | 20.56 | 19.05 / 21.12 |
| LWH 优化后单相机 | off | 32.16 | 28.51 / 34.38 |
| LWH 优化后双相机 | off | 25.68 | 23.47 / 26.81 |

后续高频遥操作验证补充：

| Case | Camera | render_interval | Wall loop Hz | Control segment Hz |
| --- | --- | ---: | ---: | --- |
| LWH 高频遥操作默认路径 | front | 2 | 46.11 | 43.30 / 58.56 |
| LWH 高频遥操作 | front + wrist | 2 | 33.80 | 32.58 / 37.60 |

判断：单相机可以作为接近 60 Hz 控制、30 Hz 图像的默认采集基线；双相机 GUI
遥操作仍明显受两路 TiledCamera 和 viewport 同步影响，不作为第一版默认采集基线。

记录：

```text
docs/stage2_validation.md
docs/stage2_gui_performance_report.md
```

## Stage 3：数据录制

状态：已完成。

对应分支：

```text
stage_3
```

目标：

- 新增独立录制入口 `scripts/record_hdf5.py`。
- 不把录制逻辑写入任务配置文件。
- 初期优先写 HDF5，降低 IsaacLab 运行环境中的 LeRobot 依赖耦合。
- 参考 LeIsaac 的 HDF5 recorder/teleop 流程，但不直接 import LeIsaac。
- 新增独立转换入口 `scripts/convert_hdf5_to_lerobot.py`。
- 转换脚本在 LeRobot Python 3.12 环境运行，不在 IsaacSim Python 3.10 进程内 import LeRobot。

关键文件：

```text
scripts/record_hdf5.py
scripts/convert_hdf5_to_lerobot.py
scripts/validate_record_hdf5.py
```

正式录制：

```bash
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --output datasets/hdf5/lwh_so101_table.hdf5
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual --output datasets/hdf5/lwh_so101_table_dual.hdf5
python3 scripts/record_hdf5.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --output datasets/hdf5/lwh_so101_table_leader.hdf5
```

正式转换：

```bash
conda activate lerobot05
python3 scripts/convert_hdf5_to_lerobot.py --input datasets/hdf5/lwh_so101_table.hdf5 --repo_id lwh/so101_table --output_dir datasets/lerobot/so101_table --overwrite
```

HDF5 数据 schema：

```text
/data/demo_N
/episodes/{episode_index}/observation/state
/episodes/{episode_index}/observation/images/front
/episodes/{episode_index}/observation/images/wrist
/episodes/{episode_index}/action
/episodes/{episode_index}/timestamp
/episodes/{episode_index}/frame_index
/episodes/{episode_index}/task
/episodes/{episode_index}/success
/episodes/{episode_index}/initial_state
/metadata/task
/metadata/fps
/metadata/joint_names
/metadata/action_dim
/metadata/camera_keys
```

episode 生命周期：

```text
B: 开始操作和录制 episode
R: 结束当前 episode，标记失败，reset 进入下一 episode
N: 结束当前 episode，标记成功，reset 进入下一 episode
Ctrl+C: 安全关闭文件
```

转换规则：

```text
默认只转换 success=True episode
默认跳过 episode 前 5 帧
默认输出 LeRobot image 格式
可通过 --image_format video 输出 video 格式
可通过 --action_key observation/joint_pos_target 改变 action 来源
```

验证过的内容：

- 录制文件能被 `h5py` 打开。
- episode 数量、frame 数量、success 标记正确。
- 每帧 state/action/timestamp/image 对齐。
- 图像非空白，shape 符合 `640 x 480 x 3`。
- 不控制真实机器人；如需 leader 输入，只读取 leader 串口。
- 单相机 HDF5 录制通过。
- 双相机 HDF5 录制通过。
- 单相机 HDF5 可转换为 LeRobotDataset v3 image 格式并由 `LeRobotDataset` 加载。
- 双相机 HDF5 可转换为 LeRobotDataset v3 image 格式并由 `LeRobotDataset` 加载。
- video 格式可写出；本机默认 torchcodec 解码链路失败，显式 `video_backend="pyav"` 可加载。

记录：

```text
docs/stage3_validation.md
```

## Stage 4：数据回放

状态：未开始。

目标：

- 新增独立回放入口，例如 `scripts/replay_hdf5.py`。
- 读取指定 HDF5 episode。
- 尽量恢复录制初始状态。
- 按原始频率逐帧应用 action。
- 支持选择 episode、暂停、继续、退出。
- 用于验证数据正确性，不依赖模型。

需要验证：

- 机器人轨迹可重复。
- 方块状态合理。
- 相机画面随动作变化且不空白。
- pause/resume/quit 可用。

## Stage 5：LeRobot 转换与训练

状态：未开始。

目标：

- 在独立 LeRobot 环境中转换 HDF5 到 LeRobotDataset v3。
- 校验关节顺序、单位、图像尺寸和 FPS。
- 用 LeRobotDataset 加载并可视化。
- 训练 ACT、Diffusion Policy、SmolVLA 等模型。
- 保存 checkpoint 和完整归一化统计。

注意：

- Stage 5 需要重新检查当前 LeRobot Dataset v3 API，不凭记忆写。
- 训练环境与 IsaacLab 环境分离，避免依赖冲突。

## Stage 6：远程推理

状态：未开始。

目标：

- IsaacLab Policy Client：发送 observation，接收 action，执行 env.step。
- LeRobot Policy Server：加载 checkpoint，observation -> policy -> action。

需要定义：

- observation/action schema
- 图像编码方式
- timeout
- action horizon
- timestamp
- reset 协议
- server 断开时的安全行为

注意：

- 这一阶段才引入 client/server 通信。
- 不使用真实机器人。
