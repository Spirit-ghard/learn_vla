# 使用方式

## 远程服务器推理（推荐）

终端一在本机运行远程服务启动器。它会读取配置中的 SSH 密码，在服务器上启动 Policy
Server，并把服务器日志显示在当前终端：

```bash
cd /home/a/lwh_code/lwh_robot_learning
python3 scripts/start_remote_policy_server.py
```

看到 `[策略服务端] 已启动` 后保持终端运行。

远程连接配置保存在本机文件：

```text
configs/remote_policy_server_config.py
```

该文件已经填写当前服务器的 IP、SSH 端口、密码、PolicyServer 路径和 checkpoint 路径。
服务器实例发生变化时直接修改其中的 `host`、`port` 和 `password`。配置文件权限会自动
设为 `600`，并已加入 `.gitignore`，不会推送到远端仓库。

终端二在本机启动 Isaac Sim。客户端会读取配置并自动认证、建立和回收 SSH 隧道：

```bash
conda activate isaac
cd /home/a/lwh_code/lwh_robot_learning

python3 scripts/run_policy_client.py
```

出现 `[策略客户端] 已就绪，等待按 B 开始` 后操作 Isaac Sim 窗口：

```text
B：发送当前观测，收到首个 action chunk 后开始执行策略
R：停止当前策略并重置场景，标记为失败
N：停止当前策略并重置场景，标记为成功
Ctrl+C：退出客户端，同时关闭其创建的 SSH 隧道
```

R/N 后不会自动继续推理，需要再次按 B。`--policy_path` 是服务器上的路径。运行期间只
控制 IsaacLab 仿真机器人，不访问真实 follower。

## 本机推理

终端一启动 LeRobot 异步策略服务端：

```bash
conda activate lerobot05
cd /home/a/lwh_code/lwh_robot_learning

python3 scripts/serve_lerobot_policy.py \
  --host 127.0.0.1 \
  --port 8080 \
  --fps 30
```

终端二启动 IsaacLab 仿真客户端：

```bash
conda activate isaac
cd /home/a/lwh_code/lwh_robot_learning

python3 scripts/run_policy_client.py \
  --local_policy_server \
  --task Lwh-SO101-Table-v0 \
  --server_address 127.0.0.1:8080 \
  --policy_path checkpoints/act_so101_table_030000 \
  --policy_type act \
  --policy_device cpu \
  --actions_per_chunk 30 \
  --chunk_size_threshold 0.5
```

上面的本机命令默认使用 CPU 推理，避免 Isaac Sim 和 ACT 争用 6GB 显存。确认显存充足时可改为：

```bash
--policy_device cuda
```

## 运行流程

`serve_lerobot_policy.py` 运行在 LeRobot Python 3.12 环境中，负责加载 checkpoint
并执行模型推理。服务端启动时不会立即加载模型，IsaacLab 客户端连接后会通过首次
握手把策略类型、checkpoint 路径、推理设备和 action chunk 大小发送给服务端。

`run_policy_client.py` 运行在 Isaac Python 3.10 环境中，负责：

1. 创建 `Lwh-SO101-Table-v0` 仿真环境。
2. 读取 6D 关节状态和 `front+wrist` 两路相机图像。
3. 将 observation 发送给 LeRobot PolicyServer。
4. 异步接收一段 action chunk 并放入本地队列。
5. 以 30 Hz 从队列取动作，同时保持 IsaacLab 物理环境持续 step。

策略推理和动作执行相互解耦。PolicyServer 计算下一段动作时，IsaacLab 会继续执行
本地队列中已有的动作，不会像旧同步实现一样等待每一次模型推理。客户端完成连接和
模型加载后停在等待状态，只有按 B 才发送观测并开始执行动作。

## 服务端参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 服务监听地址。本机使用保持不变；远程服务器可使用 `0.0.0.0`，但推荐通过 SSH 隧道连接。 |
| `--port` | `8080` | gRPC 服务端口，必须与客户端 `--server_address` 一致。 |
| `--fps` | `30` | action chunk 的时间基准，应与数据集和策略执行频率一致。 |
| `--inference_latency` | `0` | 强制设置的最小推理周期。正常使用保持 `0`，由真实推理耗时决定。 |
| `--obs_queue_timeout` | `2` | 服务端等待新 observation 的超时时间，单位为秒。 |

服务端不需要填写 checkpoint。checkpoint 由客户端握手时通过 `--policy_path` 指定。

## 客户端参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--task` | `Lwh-SO101-Table-v0` | 要运行的 IsaacLab Gym task id。 |
| `--remote_config` | `configs/remote_policy_server_config.py` | 远程服务器、密码和 checkpoint 配置文件。 |
| `--local_policy_server` | 关闭 | 忽略远程配置，直接连接 `--server_address`。 |
| `--server_address` | `127.0.0.1:8080` | PolicyServer 地址，格式必须是 `HOST:PORT`，不能填写 `http://`。 |
| `--ssh_host` | 未设置 | SSH 服务器 IP；设置后由客户端自动建立隧道，并忽略 `--server_address`。 |
| `--ssh_port` | `22` | SSH 映射端口；云平台重建实例后通常只需修改这一项。 |
| `--ssh_user` | `root` | SSH 登录用户。 |
| `--ssh_local_port` | `18080` | 客户端内部使用的本地转发端口；被占用时可换一个。 |
| `--ssh_remote_port` | `8080` | 服务器回环地址上的 PolicyServer 端口。 |
| `--policy_path` | `checkpoints/act_so101_table_030000` | 服务端能够访问的 LeRobot checkpoint 路径。远程运行时必须填写服务器上的路径。 |
| `--policy_type` | `act` | LeRobot 策略类型，当前 checkpoint 使用 ACT。 |
| `--policy_device` | `cuda` | PolicyServer 加载模型的设备。使用服务器 GPU 时保持 `cuda`；本机显存不足时改为 `cpu`。 |
| `--actions_per_chunk` | `60` | 每次推理返回的动作数量，即当前配置下约 2 秒动作。 |
| `--chunk_size_threshold` | `0.65` | action queue 剩余比例低于该值时预取下一段。 |
| `--aggregate_fn_name` | `weighted_average` | 融合新旧 action chunk 中相同 timestep 的动作。默认更偏向新动作。 |
| `--policy_hz` | `30` | 本地 action queue 的消费频率，应与训练数据 FPS 保持一致。 |
| `--camera_mode` | `dual` | `dual` 使用 front+wrist；`triple` 额外保留 overview 供观察，但 overview 不发送给模型。 |
| `--render_interval` | `2` | 60 Hz physics 下每两步更新一次渲染和相机，即约 30 Hz。 |
| `--max_action_delta` | `0.05` | 每次策略动作允许的最大关节目标变化，单位为 rad；设为 `0` 可关闭限制。 |
| `--timeout_s` | `5` | gRPC 请求超时时间，单位为秒。远程网络较慢时可适当增大。 |
| `--max_steps` | `0` | 最大仿真步数。`0` 表示持续运行，直到关闭窗口或按 `Ctrl+C`。 |

## 推荐配置

当前数据集和 ACT checkpoint 使用 `30 FPS`，推荐先保持：

```text
policy_hz=30
actions_per_chunk=60
chunk_size_threshold=0.65
aggregate_fn_name=weighted_average
render_interval=2
```

这套远程配置表示客户端每秒执行 30 个策略动作，每次推理生成约 2 秒动作，并在队列
剩余约 1.3 秒时发送最新 observation。观测上传和 action 接收都不阻塞 IsaacLab 主循环，
同一时刻最多保留一条在途观测。

## 远程服务器

远程部署时，PolicyServer 放在服务器，IsaacLab 和相机 observation 留在本机。
客户端通过 SSH 本地端口转发访问服务器回环地址。隧道由 `run_policy_client.py` 自动
创建和回收，不要把使用 pickle 序列化的 gRPC 服务直接暴露到公网。

远程模式需要修改的内容都在 `configs/remote_policy_server_config.py`：

```text
host           服务器 IP
port           云平台当前映射的 SSH 端口
password       SSH 密码
policy_path    服务器上的 checkpoint 绝对路径
```

无论本机还是远程模式，客户端只发送：

```text
observation.state
observation.images.front
observation.images.wrist
```

`overview` 只用于 Isaac Sim 窗口观察，不参与训练或策略推理。本流程只控制 IsaacLab
中的仿真 SO101，不会连接或控制真实 follower。
