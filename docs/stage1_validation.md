# 第一阶段记录

当前场景为 SO101 桌面方块任务，并支持单/双相机观测切换。

## 场景内容

- SO101 Follower
- 地面
- 桌子
- 红色方块
- DomeLight
- 前视相机 `front`
- 可选腕部相机 `wrist`
- 关节状态、末端状态、相机图像和上一帧动作观测

## 关键配置

| 项 | 当前值 |
| --- | --- |
| task id | `Lwh-SO101-Table-v0` |
| env type | `isaaclab.envs:ManagerBasedRLEnv` |
| control Hz | `60` |
| front camera | `640 x 480 @ 30 FPS` |
| wrist camera | 可选，`640 x 480 @ 30 FPS` |
| render interval | `1` |

相机位姿使用本项目早期自定义配置；运行入口可通过 `--camera_mode front` 禁用 wrist。
渲染默认值保持 LeIsaac 风格，不默认强制 `quality + FXAA`。
