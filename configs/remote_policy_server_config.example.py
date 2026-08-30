"""
远程策略服务器配置示例。

服务器实例变化时必须检查：host、port、password。
模型或服务器目录变化时才修改：policy_path、server_python、server_script。
通常不需要修改：user、local_port、remote_port、policy_device、server_fps。

启动顺序：
1. 本机终端一运行 python3 scripts/start_remote_policy_server.py。
2. 本机终端二运行 python3 scripts/run_policy_client.py。
"""

# 是否默认启用远程推理
enabled = False

# 服务器 IP 地址
host = "服务器IP"

# 云平台映射的 SSH 端口
port = 22

# SSH 登录用户
user = "root"

# SSH 登录密码
password = "服务器密码"

# 本机 SSH 隧道端口
local_port = 18080

# 服务器上的策略服务端口
remote_port = 8080

# 服务器上的模型 checkpoint 路径
policy_path = "/path/to/pretrained_model"

# 服务器推理设备
policy_device = "cuda"

# 服务器上的 LeRobot Python 路径
server_python = "/path/to/lerobot/python"

# 服务器上的策略服务脚本路径
server_script = "/path/to/serve_lerobot_policy.py"

# 策略服务动作频率
server_fps = 30
