# Codex Project Instructions

本文件是给后续 Codex/助手接手本仓库时优先阅读的项目约束。开始任何开发前，先阅读：

- `AGENTS.md`
- `docs/project_context.md`
- `docs/stage_status.md`
- `docs/decision_log.md`
- `docs/handoff.md`
- `docs/compatibility.md`

## 硬性边界

- 本项目当前只面向 IsaacLab 仿真，不控制真实机器人。
- 即使本机连接了真实 SO101 或 ROS 工程，也不得打开串口、启动 ROS 控制节点、发送真实机器人动作。
- `/home/a/lwh_code/soarm_ros` 只能作为关节命名、硬件信息和历史实现参考。
- 运行入口必须是 Python 脚本，不新增 shell 启动脚本。
- 任务定义和运行入口必须分离：任务模块注册 gym task，入口通过 `--task` 选择任务。
- 项目以 IsaacLab 为基础实现，不直接从 `leisaac` Python 包 import 任务、设备、环境模板或运行逻辑。
- LeIsaac 只作为源码参考和 SO101 USD 资产来源；允许阅读 `dependencies/leisaac` 或 `/home/a/.local/share/ov/pkg/leisaac`。
- 关键代码注释使用中文，说明为什么这么做，而不是重复代码字面含义。
- 修改前必须先看 `git status --short`，不要覆盖用户未提交改动。

## 当前架构原则

- IsaacLab 任务端：用 `ManagerBasedRLEnvCfg` 组合 scene、action、observation、event、termination。
- task id 使用 `gym.register()` 注册，当前主任务是 `Lwh-SO101-Table-v0`。
- 通用入口负责创建 AppLauncher、parse_env_cfg、gym.make、teleop.advance、env.step。
- 键盘遥操作与仿真在同一进程内运行，使用 Carb/Omniverse 键盘事件回调。
- 当前阶段不使用 ROS、UDP、ZMQ；远程推理阶段再引入 client/server。

## 当前已完成阶段

- Stage 1：SO101 桌面方块任务环境。
- Stage 2：键盘遥操作，支持单/双相机和 GUI 性能配置。
- Stage 3 及以后尚未重做到当前代码基线上。

## 验证要求

- 变更后要实际启动 IsaacLab/Isaac Sim 验证，不只做语法检查。
- 内部验证可以使用 `scripts/validate_env.py` 和 `scripts/validate_teleop.py`。
- 不把临时验证产物作为正式用户入口；完成后清理 `artifacts/` 和 `__pycache__`。
- 如果添加正式功能，更新对应 docs 并提交。

## 常用正式入口

Stage 1 场景运行：

```bash
python3 scripts/run_env.py --task Lwh-SO101-Table-v0 --num_envs 1
```

Stage 2 单相机遥操作基线：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front
```

Stage 2 双相机遥操作：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode dual
```

恢复完整 ground：

```bash
python3 scripts/teleop.py --task Lwh-SO101-Table-v0 --num_envs 1 --camera_mode front --ground_mode on
```

## 分支策略

- `stage_1`：一阶段最小场景。
- `stage_2`：二阶段单相机 LeIsaac 风格基线。
- `stage_2_1`：二阶段过程版本。
- `stage_2_2`：二阶段当前最新版本，支持单/双相机和 `ground_mode`。
- `main` 当前指向 `stage_2_2` 最新提交。

后续进入 Stage 3 时，建议从 `stage_2_2` 创建新分支：

```bash
git checkout stage_2_2
git checkout -b stage_3
```
