# Project Context

本文档记录项目总目标、当前代码结构、运行环境和后续开发入口，用于在新对话或上下文压缩后快速恢复信息。

## 总目标

基于 IsaacLab 搭建一套只面向仿真的机器人学习流程，参考 LeIsaac 的任务组织方式，并使用 LeRobot 完成数据训练。当前不部署或控制真实机器人；Stage 2.3/3 只允许读取真实 SO101 Leader 作为仿真输入设备。

最终目标流程：

```text
IsaacLab 仿真端
任务创建 -> 遥操作 -> 数据录制 -> 数据回放 -> 策略评估客户端

LeRobot 训练端
数据转换 -> 模型训练 -> Policy Server -> 远程推理
```

## 当前状态

当前本机工作树：

```text
<repo>
```

当前主任务：

```text
Lwh-SO101-Table-v0
```

当前最新分支：

```text
stage_3
```

当前最新提交：

```text
stage 3: add hdf5 recording and lerobot conversion
```

`main` 暂未更新到本地最新阶段分支。

当前远端：

```text
origin git@github.com:Spirit-ghard/learn_vla.git
```

## 重要限制

- 不控制真实 follower。
- 不启动 ROS。
- 默认键盘仿真不访问串口；只有 `--teleop_device so101leader` 显式读取真实 leader 串口。
- 不把外部 ROS/真实机器人工程注入运行时。
- 不直接 import `leisaac` Python 包。
- 不直接 import LeRobot 到 Isaac 进程。
- 不新增 shell 启动脚本。

## 代码结构

```text
scripts/
  isaac_runtime.py
  run_env.py
  teleop.py
  record_hdf5.py
  convert_hdf5_to_lerobot.py
  validate_env.py
  validate_teleop.py
  validate_record_hdf5.py

source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/
  __init__.py
  assets/
    robots/
      so101_follower.usd
    so101_constants.py
    so101.py
  devices/
    so101_keyboard.py
    so101_leader.py
  tasks/
    __init__.py
    so101_table/
      __init__.py
      mdp.py
      so101_table_env_cfg.py

docs/
  compatibility.md
  portability.md
  stage1_validation.md
  stage2_validation.md
  stage2_gui_performance_report.md
  stage3_validation.md
  project_context.md
  stage_status.md
  decision_log.md
  handoff.md
```

## 运行时设计

所有正式入口都先调用：

```python
from isaac_runtime import ensure_isaac_runtime
ensure_isaac_runtime()
```

`scripts/isaac_runtime.py` 负责：

- 默认使用当前已激活 Python；如果当前 Python 低于 3.10，会尝试常见的 `lwh_isaac` conda 环境；需要跨环境重执行时可用 `LWH_ISAAC_PYTHON` 指定。
- 配置 Isaac Sim、IsaacLab、Python path、动态库路径。
- 移除 ROS 和 `soarm_ros` 路径。
- 校验项目内置 SO101 USD 资产存在且不是 Git LFS pointer。
- 验证脚本可以通过 supervisor 模式得到可靠退出码。

默认资产根目录：

```text
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/assets
```

可选环境变量：

```text
LWH_ISAAC_SIM_ROOT  指向 Isaac Sim 安装根目录
ISAAC_PATH          Isaac Sim 官方/现有环境变量，也可作为根目录来源
LWH_ISAAC_PYTHON    需要跨环境重执行时指定 Python
LWH_SIM_ASSETS_ROOT 临时覆盖仿真资产根目录
```

## 依赖和版本

详细记录见 `docs/compatibility.md`。关键版本：

| 组件 | 版本或提交 |
| --- | --- |
| Isaac Sim | 4.5.0-rc.36 |
| IsaacLab | v2.1.1 |
| IsaacLab Python package | 0.41.3 |
| IsaacLab Tasks | 0.10.36 |
| LeIsaac | 0.4.0 / `24d3bcd3f1e4585740fc79921782c41617237812` |
| Isaac Python | 3.10.20 |
| LeRobot Python | 3.12.13 |
| LeRobot | 0.5.1 / `2ea20910` |
| PyTorch | 2.5.1+cu124 |
| GPU | NVIDIA GeForce RTX 3060 Laptop, 6 GiB |

## IsaacLab 任务实现

任务注册位置：

```text
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/tasks/so101_table/__init__.py
```

环境配置位置：

```text
source/lwh_isaaclab_tasks/lwh_isaaclab_tasks/tasks/so101_table/so101_table_env_cfg.py
```

当前环境基类：

```text
isaaclab.envs:ManagerBasedRLEnv
```

当前任务内容：

- SO101 Follower
- ground plane，任务配置中保留；teleop 默认运行时移除
- 桌子
- 红色可操作方块
- DomeLight
- 前视相机 `front`
- 腕部相机 `wrist`
- 关节状态观测
- 相机 RGB 图像观测
- 末端 frame 状态观测
- 上一帧 action 观测
- 默认 reset event

## SO101 关节契约

关节顺序：

```text
shoulder_pan
shoulder_lift
elbow_flex
wrist_flex
wrist_roll
gripper
```

键盘动作维度：`8`

键盘遥操作下动作含义：

```text
0: dx
1: dy
2: dz
3: droll
4: dpitch
5: dyaw
6: d_shoulder_pan
7: d_gripper
```

`use_teleop_device("keyboard")` 会配置：

- `DifferentialInverseKinematicsActionCfg` 控制 `shoulder_lift/elbow_flex/wrist_flex/wrist_roll`
- `RelativeJointPositionActionCfg` 控制 `shoulder_pan/gripper`
- 禁用机器人刚体重力，减少 IK 键盘模式下的抖动

`use_teleop_device("so101leader")` 会配置：

- `JointPositionActionCfg` 控制 `shoulder_pan/shoulder_lift/elbow_flex/wrist_flex/wrist_roll`
- `JointPositionActionCfg` 控制 `gripper`
- 动作维度为 `6`
- 真实 leader 位置按 LeRobot/LeIsaac 校准格式归一化，再映射到仿真 follower 关节角范围

## Stage 3 数据录制

Isaac 端录制入口：

```text
scripts/record_hdf5.py
```

LeRobot 转换入口：

```text
scripts/convert_hdf5_to_lerobot.py
```

HDF5 主结构：

```text
/data/demo_N
/episodes/000000
/metadata
```

`/episodes/000000` 是指向 `/data/demo_0` 的硬链接，便于同时兼容 LeIsaac/IsaacLab
风格和本项目前面定义的 episode 路径。

每帧关键字段：

```text
observation/state
observation/images/front
observation/images/wrist
action
timestamp
episode_index
frame_index
task
```

每个 episode 还写入：

```text
success
valid
num_samples
initial_state
```

episode 生命周期：

```text
B 开始录制
R 结束并标记 failure
N 结束并标记 success
Ctrl+C 安全关闭；活动 episode 标记 interrupted/failure
```

转换规则：

```text
默认只转换 success=True episode
默认跳过前 5 帧
默认输出 LeRobot image 格式
--image_format video 可输出 video 格式
```

当前本机 LeRobot 0.5.1 可写出 video dataset，但默认 torchcodec 读取因 FFmpeg 动态库链路失败；
显式 `video_backend="pyav"` 可读。第一版正式转换默认使用 image 格式，保证训练端直接可加载。

## 相机配置

当前 `front`：

```text
prim_path: {ENV_REGEX_NS}/Robot/base/front_camera
position: (0.0, -0.5, 0.6)
rotation: (0.1650476, -0.9862856, 0.0, 0.0)
convention: ros
resolution: 640 x 480
update_period: 1 / 30
focal_length: 28.7
horizontal_aperture: 38.11
```

当前 `wrist`：

```text
prim_path: {ENV_REGEX_NS}/Robot/gripper/wrist_camera
position: (-0.001, 0.1, -0.04)
rotation: (-0.704022, -0.065999, 0.646586, -0.286221)
convention: ros
resolution: 640 x 480
update_period: 1 / 30
focal_length: 36.5
horizontal_aperture: 36.83
```

LeIsaac `LiftCube` 对照 front：

```text
position: (-0.6, -0.75, 0.38)
rotation: (0.77337, 0.55078, -0.2374, -0.20537)
convention: opengl
resolution: 640 x 480
update_period: 1 / 30
focal_length: 40.6
horizontal_aperture: 38.11
```

消融测试显示，本项目吞吐瓶颈不是 front 位姿或镜头参数，而是额外 ground plane。

## 正式入口

Stage 1 场景运行：

```bash
cd <repo>
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

Stage 2 单相机遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

Stage 2 双相机遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

Stage 2.3 真实 SO101 Leader 控制仿真：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0
```

启动后立即跟随 leader：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --teleop_device so101leader --leader_port /dev/ttyACM0 --leader_start_immediately
```

恢复完整 ground：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front --ground_mode on
```

## Stage 2 遥操作按键

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

Leader 模式：

```text
B 开始跟随真实 leader
R 失败并重置
N 成功并重置
Ctrl+C 或关闭窗口退出
```

## 内部验证入口

这些是开发验证用，不作为正式使用方式输出给最终用户。

Stage 1 环境验证：

```bash
python3 scripts/validate_env.py --headless --steps 60 --camera_mode front --output_dir artifacts/stage1/front
python3 scripts/validate_env.py --headless --steps 60 --camera_mode dual --output_dir artifacts/stage1/dual
```

Stage 2 遥操作验证：

```bash
python3 scripts/validate_teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
python3 scripts/validate_teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
python3 scripts/validate_teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front --ground_mode on
```

验证后清理：

```bash
python3 - <<'PY'
from pathlib import Path
import shutil
root = Path.cwd()
shutil.rmtree(root / 'artifacts', ignore_errors=True)
for path in root.rglob('__pycache__'):
    if '.git' not in path.parts:
        shutil.rmtree(path, ignore_errors=True)
PY
```

## 后续阶段目标摘要

Stage 3 数据录制：

- 新增独立录制入口，不把录制逻辑写进任务文件。
- 初期采用 IsaacLab/LeIsaac 风格 HDF5。
- 每帧至少记录 `observation.state`、`observation.images.front`、可选 `observation.images.wrist`、`action`、`timestamp`、`episode_index`、`frame_index`、`task`。
- episode 生命周期：`B` 开始；`R` 结束失败；`N` 结束成功；reset 进入下一 episode。

Stage 4 回放：

- 读取 HDF5 指定 episode。
- 尽量重置到录制初始状态。
- 按原始频率逐帧应用 action。
- 支持 episode 选择、暂停、继续、退出。

Stage 5 LeRobot 转换与训练：

- HDF5 转 LeRobotDataset v3。
- 校验关节顺序、单位、图像尺寸、FPS。
- 加载可视化，再训练 ACT/Diffusion Policy/SmolVLA 等。

Stage 6 远程推理：

- IsaacLab Policy Client 发送 observation，接收 action，执行 env.step。
- LeRobot Policy Server 加载 checkpoint，进行远程推理。
- 定义 observation/action schema、图像编码、超时、action horizon、timestamp、reset 协议和断连安全行为。
