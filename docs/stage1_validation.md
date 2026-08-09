# 第一阶段记录

当前 Stage 2 分支中的第一阶段场景为 SO101 桌面方块任务，配置已按 LeIsaac LiftCube
的轻量视觉负载调整。

## 场景内容

- SO101 Follower
- 地面
- 桌子
- 红色方块
- DomeLight
- 前视相机 `front`
- 关节状态、末端状态、前视图像和上一帧动作观测

## 关键配置

| 项 | 当前值 |
| --- | --- |
| task id | `Lwh-SO101-Table-v0` |
| env type | `isaaclab.envs:ManagerBasedRLEnv` |
| control Hz | `60` |
| camera | `front` |
| image size | `640 x 480` |
| image FPS | `30` |
| wrist camera | disabled |

运行入口只创建仿真环境，不连接真实机器人、不启动 ROS、不访问串口。
