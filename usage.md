# 使用方式

## 远程服务器推理（推荐）

终端一登录服务器并启动 Policy Server：

```bash
ssh -p 30724 root@183.147.142.40

cd /root/gpufree-data/lwh_policy_server
/root/lerobot/.venv/bin/python serve_lerobot_policy.py \
  --host 127.0.0.1 \
  --port 8080 \
  --fps 30
```

看到 `LWH_ASYNC_POLICY_SERVER_READY` 后保持终端运行。

终端二在本机建立 SSH 隧道：

```bash
ssh -N -p 30724 \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -L 18080:127.0.0.1:8080 \
  root@183.147.142.40
```

终端三在本机启动 Isaac Sim：

```bash
conda activate isaac
cd /home/a/lwh_code/lwh_robot_learning

python3 scripts/run_policy_client.py \
  --task Lwh-SO101-Table-v0 \
  --server_address 127.0.0.1:18080 \
  --policy_path /root/gpufree-data/lwh_lerobot_data/runs/act_video_b32_50k_20260823_184025/checkpoints/030000/pretrained_model \
  --policy_device cuda \
  --actions_per_chunk 60 \
  --chunk_size_threshold 0.65 \
  --camera_mode dual \
  --render_interval 2
```

`--policy_path` 是服务器上的路径。客户端会先等待首个 action chunk，再开始执行策略。
运行期间只控制 IsaacLab 仿真机器人，不访问真实 follower。

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
本地队列中已有的动作，不会像旧同步实现一样等待每一次模型推理。

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
| `--server_address` | `127.0.0.1:8080` | PolicyServer 地址，格式必须是 `HOST:PORT`，不能填写 `http://`。 |
| `--policy_path` | `checkpoints/act_so101_table_030000` | 服务端能够访问的 LeRobot checkpoint 路径。远程运行时必须填写服务器上的路径。 |
| `--policy_type` | `act` | LeRobot 策略类型，当前 checkpoint 使用 ACT。 |
| `--policy_device` | `cuda` | PolicyServer 加载模型的设备。使用服务器 GPU 时保持 `cuda`；本机显存不足时改为 `cpu`。 |
| `--actions_per_chunk` | `30` | 每次推理返回的动作数量。公网部署推荐显式设置为 60，当前 ACT checkpoint 最大支持 100。 |
| `--chunk_size_threshold` | `0.5` | action queue 的预取阈值。公网部署推荐显式设置为 0.65。 |
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
推荐使用 SSH 本地端口转发，再让客户端连接 `127.0.0.1:8080`。不要把使用 pickle
序列化的 gRPC 服务直接暴露到公网。

远程模式需要修改的主要参数只有：

```text
--policy_path      改为服务器上的 checkpoint 绝对路径
--policy_device    使用服务器 GPU 时设置为 cuda
```

无论本机还是远程模式，客户端只发送：

```text
observation.state
observation.images.front
observation.images.wrist
```

`overview` 只用于 Isaac Sim 窗口观察，不参与训练或策略推理。本流程只控制 IsaacLab
中的仿真 SO101，不会连接或控制真实 follower。
