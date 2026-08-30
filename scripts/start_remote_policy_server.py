#!/usr/bin/env python3
"""读取本地配置，并通过 SSH 启动远程 LeRobot 策略服务。"""

from __future__ import annotations

import argparse
import os
import runpy
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
default_config_path = project_root / "configs/remote_policy_server_config.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动远程 LeRobot 策略服务。")
    parser.add_argument(
        "--config",
        default=str(default_config_path),
        help="远程服务器配置文件。",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict:
    try:
        config = runpy.run_path(str(path))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"无法读取远程服务器配置 {path}：{exc}") from exc
    required_fields = (
        "host",
        "port",
        "user",
        "password",
        "remote_port",
        "server_python",
        "server_script",
        "server_fps",
    )
    missing_fields = [name for name in required_fields if config.get(name) in (None, "")]
    if missing_fields:
        raise ValueError(f"远程服务器配置缺少字段：{', '.join(missing_fields)}")
    path.chmod(0o600)
    return config


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if shutil.which("ssh") is None or shutil.which("sshpass") is None:
        raise RuntimeError("启动远程服务需要系统提供 ssh 和 sshpass。")

    password_fd, password_path = tempfile.mkstemp(prefix="lwh_ssh_", text=True)
    os.fchmod(password_fd, 0o600)
    with os.fdopen(password_fd, "w", encoding="utf-8") as password_file:
        password_file.write(str(config["password"]))
        password_file.write("\n")

    command = [
        "sshpass",
        "-f",
        password_path,
        "ssh",
        "-tt",
        "-p",
        str(config["port"]),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        f"{config['user']}@{config['host']}",
        str(config["server_python"]),
        str(config["server_script"]),
        "--host",
        "127.0.0.1",
        "--port",
        str(config["remote_port"]),
        "--fps",
        str(config["server_fps"]),
    ]
    print(
        f"[远程服务] 正在连接服务器：{config['user']}@{config['host']}:{config['port']}",
        flush=True,
    )
    process = subprocess.Popen(command)
    try:
        # sshpass 在建立连接时立即读取密码，之后删除临时文件。
        time.sleep(1.0)
        Path(password_path).unlink(missing_ok=True)
        return process.wait()
    except KeyboardInterrupt:
        print("\n[远程服务] 收到停止请求", flush=True)
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.terminate()
        return 0
    finally:
        Path(password_path).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[远程服务] 启动失败：{exc}", flush=True)
        raise
