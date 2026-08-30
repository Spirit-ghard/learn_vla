# LeRobot 异步推理

本项目采用 LeRobot 官方 async inference 的工作方式：

```text
IsaacLab client                         LeRobot PolicyServer
采集 state + front + wrist   --gRPC-->  根据最新 observation 推理 action chunk
本地 action queue             <--gRPC--  返回带 timestep 的多步 action
30 Hz 取 action，60 Hz env.step
```

实现基于 Hugging Face LeRobot `v0.5.1` 官方源码：

- `lerobot.async_inference.policy_server.PolicyServer`
- `lerobot.async_inference.robot_client.RobotClient`
- `lerobot.transport.services.proto`

服务端直接复用官方 `PolicyServer`。Isaac Sim 4.5 使用 Python 3.10，LeRobot 0.5.1
要求 Python 3.12，因此 IsaacLab 进程不直接 import LeRobot；项目只适配官方 gRPC
消息、action queue、阈值触发和重叠 chunk 聚合。该适配不会连接或控制真实 follower。

## 安装依赖

LeRobot 环境安装官方 async 额外依赖：

```bash
conda activate lerobot05
python3 -m pip install -e "/home/a/lerobot_05[async]"
```

Isaac 环境需要 `grpcio`。当前环境已经安装；新机器可检查：

```bash
conda activate isaac
python3 -c "import grpc; print(grpc.__version__)"
```

## 本机运行

终端一在 LeRobot 环境启动空的 PolicyServer。模型由客户端首次握手时加载：

```bash
conda activate lerobot05
cd /home/a/lwh_code/lwh_robot_learning
python3 scripts/serve_lerobot_policy.py --host 127.0.0.1 --port 8080 --fps 30
```

终端二在 Isaac 环境启动仿真客户端：

```bash
conda activate isaac
cd /home/a/lwh_code/lwh_robot_learning
python3 scripts/run_policy_client.py \
  --task Lwh-SO101-Table-v0 \
  --server_address 127.0.0.1:8080 \
  --policy_path /home/a/lwh_code/lwh_robot_learning/checkpoints/act_so101_table_030000 \
  --policy_type act \
  --policy_device cuda \
  --actions_per_chunk 30 \
  --chunk_size_threshold 0.5
```

## 远程运行

PolicyServer 在服务器的 LeRobot 环境运行，IsaacLab client 留在本机。推荐通过 SSH
端口转发连接，不直接把使用 pickle 的官方 gRPC 服务暴露到公网。客户端的
`--policy_path` 必须填写服务器进程能够访问的 checkpoint 路径。

连接建立后，客户端仍使用 `--server_address 127.0.0.1:8080` 访问本地转发端口。
网络中断或 action queue 暂时为空时，仿真保持上一关节目标，不会访问真实机器人。

## 关键参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--actions_per_chunk` | `30` | 每次推理返回的动作数；ACT checkpoint 最大为 `100`。 |
| `--chunk_size_threshold` | `0.5` | 队列剩余比例低于该值时发送新观测。 |
| `--aggregate_fn_name` | `weighted_average` | 按官方规则融合重叠 timestep 的动作。 |
| `--policy_hz` | `30` | 本地 action queue 的消费频率，需与训练数据 FPS 一致。 |
| `--render_interval` | `2` | 60 Hz physics 下每两步更新一次相机，即约 30 Hz。 |
| `--timeout_s` | `5` | gRPC 请求超时。 |

当前数据和 ACT checkpoint 都是 `30 FPS`。建议先使用
`actions_per_chunk=30, chunk_size_threshold=0.5`；这代表约 1 秒动作范围，并在队列
剩余约 0.5 秒时请求下一段。`overview` 只用于人工观察，策略始终只发送
`observation.state + front + wrist`。
