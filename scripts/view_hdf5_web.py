#!/usr/bin/env python3
"""Serve a lightweight browser viewer for LWH HDF5 teleoperation recordings.

已完成：
- 这是纯 HDF5 数据查看器，不启动 IsaacSim，不执行 env.step，不访问真实 leader/follower。
- 默认扫描 datasets/hdf5，也支持网页内 Choose HDF5 手动选择本地文件。
- 支持 file/episode 下拉、三窗口同步图像回放、播放/暂停/逐帧/timeline/速度控制。
- 页面布局固定为上 40% front+wrist，下 60% overview；旧数据缺 wrist/overview 时显示“未录制”。
- 读取并显示当前帧 timestamp、episode outcome、action/state 前 16 个值。
- 固定使用 --port 指定端口；端口被占用时会先清理旧进程，再绑定同一个端口。

后续要做：
- 录制端补齐 overview 第三路相机后，viewer 可直接显示，不需要改数据读取路径。
- 增加 action/state 曲线、timestamp 间隔检查、空白图像检查和异常 episode 标记。
- 增加导出质量报告 JSON，用于快速筛查采集数据问题。
- 如果 HDF5 文件很大，再改为帧缓存或 JPEG/PNG 编码缓存，降低逐帧读取开销。
"""

from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import signal
import struct
import sys
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    import h5py
    import numpy as np
except ImportError as exc:
    h5py = None
    np = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "datasets/hdf5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View LWH HDF5 recordings in a browser without IsaacSim.")
    parser.add_argument(
        "--data_dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory scanned recursively for .hdf5 and .h5 files.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        action="append",
        default=[],
        help="Additional HDF5 file to expose. Can be passed multiple times.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for the local web server.")
    parser.add_argument("--port", type=int, default=7860, help="Port for the local web server.")
    args = parser.parse_args()
    args.data_dir = args.data_dir.expanduser().resolve()
    args.file = [path.expanduser().resolve() for path in args.file]
    return args


class HDF5Catalog:
    """扫描允许的 HDF5 文件，并用稳定 id 暴露给前端。"""

    def __init__(self, data_dir: Path, explicit_files: list[Path]) -> None:
        self.data_dir = data_dir
        self.explicit_files = explicit_files
        self.upload_dir = Path(tempfile.mkdtemp(prefix="lwh-hdf5-viewer-"))
        self.uploaded_files: list[Path] = []

    def add_upload(self, filename: str, payload: bytes) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower()
        if suffix not in (".hdf5", ".h5"):
            raise ValueError("Only .hdf5 and .h5 files can be uploaded.")
        safe_name = Path(filename).name
        output_path = self.upload_dir / f"{int(time.time_ns())}-{safe_name}"
        output_path.write_bytes(payload)
        # 上传后立即打开一次，确保它确实是 HDF5，避免前端下拉出现坏文件。
        with h5py.File(output_path, "r"):
            pass
        self.uploaded_files.append(output_path)
        for file_info in self.files():
            if Path(file_info["path"]) == output_path:
                return file_info
        raise RuntimeError(f"Uploaded file was not indexed: {output_path}")

    def files(self) -> list[dict[str, Any]]:
        paths: list[Path] = []
        if self.data_dir.exists():
            paths.extend(sorted(self.data_dir.rglob("*.hdf5")))
            paths.extend(sorted(self.data_dir.rglob("*.h5")))
        paths.extend(path for path in self.explicit_files if path.is_file())
        paths.extend(path for path in self.uploaded_files if path.is_file())

        unique_paths = sorted({path.resolve() for path in paths})
        result: list[dict[str, Any]] = []
        for index, path in enumerate(unique_paths):
            stat = path.stat()
            result.append(
                {
                    "id": str(index),
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_unix_s": int(stat.st_mtime),
                }
            )
        return result

    def resolve(self, file_id: str) -> Path:
        for file_info in self.files():
            if file_info["id"] == file_id:
                return Path(file_info["path"])
        raise KeyError(f"Unknown file id: {file_id}")


def read_json_attr(attrs: h5py.AttributeManager, key: str, default: Any) -> Any:
    if key not in attrs:
        return default
    value = attrs[key]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def read_string_dataset(group: h5py.Group, key: str) -> list[str] | None:
    if key not in group:
        return None
    dataset = group[key]
    values = dataset.asstr()[:]
    return [str(value) for value in values.tolist()]


def episode_sort_key(name: str) -> int:
    if name.startswith("demo_"):
        return int(name.rsplit("_", 1)[-1])
    return int(name)


def episode_root(h5_file: h5py.File) -> h5py.Group:
    if "data" in h5_file:
        return h5_file["data"]
    if "episodes" in h5_file:
        return h5_file["episodes"]
    raise ValueError("HDF5 file has neither /data nor /episodes group.")


def list_camera_keys(h5_file: h5py.File, episode: h5py.Group | None) -> list[str]:
    metadata = h5_file.get("metadata")
    if metadata is not None:
        values = read_string_dataset(metadata, "camera_keys")
        if values:
            return values
        values = read_json_attr(metadata.attrs, "camera_keys", None)
        if values:
            return [str(value) for value in values]
    if episode is not None and "observation/images" in episode:
        return sorted(episode["observation/images"].keys())
    return []


def list_joint_names(h5_file: h5py.File) -> list[str]:
    metadata = h5_file.get("metadata")
    if metadata is None:
        return []
    values = read_string_dataset(metadata, "joint_names")
    if values:
        return values
    values = read_json_attr(metadata.attrs, "joint_names", None)
    if values:
        return [str(value) for value in values]
    return []


def dataset_shape(group: h5py.Group, path: str) -> list[int] | None:
    if path not in group:
        return None
    value = group[path]
    if not isinstance(value, h5py.Dataset):
        return None
    return [int(dim) for dim in value.shape]


def episode_info(name: str, group: h5py.Group) -> dict[str, Any]:
    num_samples = int(group.attrs.get("num_samples", group["action"].shape[0] if "action" in group else 0))
    camera_keys = []
    if "observation/images" in group:
        camera_keys = sorted(group["observation/images"].keys())
    return {
        "id": name,
        "label": name,
        "episode_index": int(group.attrs.get("episode_index", episode_sort_key(name))),
        "success": bool(group.attrs.get("success", False)),
        "valid": bool(group.attrs.get("valid", True)),
        "outcome": str(group.attrs.get("outcome", "")),
        "num_samples": num_samples,
        "duration_s": float(group.attrs.get("duration_s", 0.0)),
        "camera_keys": camera_keys,
        "state_shape": dataset_shape(group, "observation/state"),
        "action_shape": dataset_shape(group, "action"),
        "timestamp_shape": dataset_shape(group, "timestamp"),
    }


def file_summary(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5_file:
        root = episode_root(h5_file)
        names = sorted(root.keys(), key=episode_sort_key)
        first_episode = root[names[0]] if names else None
        metadata = h5_file.get("metadata")
        metadata_attrs = metadata.attrs if metadata is not None else {}
        episodes = [episode_info(name, root[name]) for name in names]
        return {
            "path": str(path),
            "name": path.name,
            "task": str(metadata_attrs.get("task", "")),
            "fps": int(metadata_attrs.get("fps", 30)),
            "teleop_device": str(metadata_attrs.get("teleop_device", "")),
            "action_dim": int(metadata_attrs.get("action_dim", 0)),
            "camera_keys": list_camera_keys(h5_file, first_episode),
            "joint_names": list_joint_names(h5_file),
            "episodes": episodes,
        }


def sample_frame(path: Path, episode_id: str, frame_index: int) -> dict[str, Any]:
    with h5py.File(path, "r") as h5_file:
        group = episode_root(h5_file)[episode_id]
        num_samples = int(group.attrs.get("num_samples", group["action"].shape[0] if "action" in group else 0))
        if num_samples < 1:
            raise ValueError("Episode has no frames.")
        index = min(max(frame_index, 0), num_samples - 1)

        def read_array(dataset_path: str, limit: int = 16) -> list[float] | None:
            if dataset_path not in group:
                return None
            array = np.asarray(group[dataset_path][index]).reshape(-1)
            return [float(value) for value in array[:limit]]

        timestamp = float(group["timestamp"][index]) if "timestamp" in group else float(index)
        camera_keys = sorted(group["observation/images"].keys()) if "observation/images" in group else []
        return {
            "frame_index": index,
            "num_samples": num_samples,
            "timestamp": timestamp,
            "camera_keys": camera_keys,
            "state": read_array("observation/state"),
            "action": read_array("action"),
        }


def encode_bmp(rgb: Any) -> bytes:
    """把 uint8 RGB 图像编码成浏览器可直接显示的 top-down BMP。"""
    height, width, _channels = rgb.shape
    row_padding = (4 - (width * 3) % 4) % 4
    row_stride = width * 3 + row_padding
    pixel_bytes = bytearray()
    bgr = rgb[..., ::-1]
    padding = b"\x00" * row_padding
    for row in bgr:
        pixel_bytes.extend(row.tobytes())
        pixel_bytes.extend(padding)

    header_size = 14 + 40
    file_size = header_size + len(pixel_bytes)
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, header_size)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        -height,
        1,
        24,
        0,
        row_stride * height,
        2835,
        2835,
        0,
        0,
    )
    return file_header + info_header + bytes(pixel_bytes)


def encode_frame(path: Path, episode_id: str, camera_key: str, frame_index: int) -> bytes:
    with h5py.File(path, "r") as h5_file:
        group = episode_root(h5_file)[episode_id]
        dataset_path = f"observation/images/{camera_key}"
        if dataset_path not in group:
            raise KeyError(f"Camera stream not found: {camera_key}")
        dataset = group[dataset_path]
        if dataset.shape[0] < 1:
            raise ValueError(f"Camera stream has no frames: {camera_key}")
        index = min(max(frame_index, 0), dataset.shape[0] - 1)
        image = np.asarray(dataset[index])
        if image.ndim != 3 or image.shape[-1] < 3:
            raise ValueError(f"Unexpected image shape for {camera_key}: {image.shape}")
        rgb = image[..., :3]
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        return encode_bmp(np.ascontiguousarray(rgb))


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def html_page() -> bytes:
    return INDEX_HTML.encode("utf-8")


def socket_inodes_for_port(port: int) -> set[str]:
    """从 /proc/net/tcp* 找到占用指定本地端口的 socket inode。"""
    inodes: set[str] = set()
    port_hex = f"{port:04X}"
    for proc_net in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not proc_net.is_file():
            continue
        for line in proc_net.read_text(encoding="utf-8").splitlines()[1:]:
            columns = line.split()
            if len(columns) < 10:
                continue
            local_address = columns[1]
            local_port = local_address.rsplit(":", 1)[-1]
            inode = columns[9]
            if local_port.upper() == port_hex and inode != "0":
                inodes.add(inode)
    return inodes


def pids_for_socket_inodes(inodes: set[str]) -> set[int]:
    """把 socket inode 映射到持有它们的进程 pid。"""
    pids: set[int] = set()
    if not inodes:
        return pids
    current_pid = os.getpid()
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue
        fd_dir = proc_dir / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    pids.add(pid)
                    break
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return pids


def kill_processes_on_port(port: int) -> list[int]:
    """杀掉占用 viewer 端口的旧进程；用户期望固定端口而不是自动顺延。"""
    pids = sorted(pids_for_socket_inodes(socket_inodes_for_port(port)))
    if not pids:
        return []

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not pids_for_socket_inodes(socket_inodes_for_port(port)):
            return pids
        time.sleep(0.05)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return pids


def create_server(host: str, port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    """固定使用请求端口；若被旧进程占用，则先清理旧进程。"""
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        if exc.errno not in (98, 48):
            raise
        killed_pids = kill_processes_on_port(port)
        if killed_pids:
            print(f"LWH_HDF5_VIEWER_PORT_CLEANED port={port} pids={killed_pids}", flush=True)
        return ThreadingHTTPServer((host, port), handler)


class ViewerHandler(BaseHTTPRequestHandler):
    catalog: HDF5Catalog

    server_version = "LWHHDF5Viewer/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                self.send_blob(html_page(), "text/html; charset=utf-8")
            elif path == "/api/files":
                self.send_json({"files": self.catalog.files()})
            elif path.startswith("/api/files/") and path.endswith("/summary"):
                file_id = path.split("/")[3]
                self.send_json(file_summary(self.catalog.resolve(file_id)))
            elif path.startswith("/api/files/") and "/sample" in path:
                parts = path.strip("/").split("/")
                file_id = parts[2]
                episode_id = parts[4]
                frame = int(query.get("frame", ["0"])[0])
                self.send_json(sample_frame(self.catalog.resolve(file_id), episode_id, frame))
            elif path.startswith("/api/files/") and "/frame" in path:
                parts = path.strip("/").split("/")
                file_id = parts[2]
                episode_id = parts[4]
                camera = query.get("camera", ["front"])[0]
                frame = int(query.get("frame", ["0"])[0])
                image = encode_frame(self.catalog.resolve(file_id), episode_id, camera, frame)
                self.send_blob(image, "image/bmp", cache_control="no-store")
            elif path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                content_type = mimetypes.guess_type(path)[0] or "text/plain"
                self.send_error(HTTPStatus.NOT_FOUND, f"Not found: {path} ({content_type})")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path != "/api/upload":
                self.send_error(HTTPStatus.NOT_FOUND, f"Not found: {parsed.path}")
                return
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            if "file" not in form:
                raise ValueError("Upload form must include a 'file' field.")
            item = form["file"]
            if isinstance(item, list):
                item = item[0]
            filename = item.filename or "upload.hdf5"
            payload = item.file.read()
            file_info = self.catalog.add_upload(filename, payload)
            self.send_json({"file": file_info, "files": self.catalog.files()})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: Any) -> None:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}", flush=True)

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_blob(json_bytes(payload), "application/json; charset=utf-8", status=status)

    def send_blob(
        self,
        payload: bytes,
        content_type: str,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(payload)


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LWH HDF5 Viewer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f6f3;
      --panel: #ffffff;
      --line: #deded8;
      --line-strong: #c8c8c0;
      --text: #171717;
      --muted: #74746d;
      --soft: #ecece7;
      --accent: #111111;
      --ok: #1f7a45;
      --bad: #a33930;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    button, select, input {
      font: inherit;
    }

    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    .topbar {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 28px;
      align-items: center;
      padding: 22px 28px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(246, 246, 243, 0.96);
    }

    .brand {
      display: flex;
      align-items: baseline;
      gap: 14px;
      min-width: 220px;
    }

    .brand-title {
      font-size: 18px;
      font-weight: 620;
    }

    .brand-subtitle {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }

    .selectors {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(160px, 260px) auto;
      gap: 12px;
      align-items: end;
    }

    .field {
      display: grid;
      gap: 6px;
    }

    .field label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
    }

    select, input[type="range"] {
      width: 100%;
    }

    select {
      height: 36px;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      background: var(--panel);
      color: var(--text);
      padding: 0 10px;
    }

    .status {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: flex-end;
      color: var(--muted);
      font-size: 13px;
      min-width: 190px;
    }

    .dot {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--line-strong);
    }

    .dot.ok { background: var(--ok); }
    .dot.bad { background: var(--bad); }

    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 0;
      min-height: 0;
    }

    .viewer {
      display: grid;
      grid-template-rows: 40fr 60fr;
      gap: 12px;
      padding: 18px;
      min-height: 0;
    }

    .top-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      min-height: 0;
    }

    .bottom-row {
      min-height: 0;
    }

    .viewport {
      position: relative;
      min-height: 0;
      border: 1px solid var(--line);
      background: #101010;
      overflow: hidden;
      display: grid;
      place-items: center;
    }

    .viewport img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }

    .viewport-header {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 38px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px;
      color: #f4f4f0;
      background: linear-gradient(to bottom, rgba(0, 0, 0, 0.62), rgba(0, 0, 0, 0));
      z-index: 2;
    }

    .viewport-header span {
      font-size: 12px;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.82);
    }

    .camera-select {
      width: 140px;
      height: 26px;
      border-color: rgba(255, 255, 255, 0.22);
      background: rgba(18, 18, 18, 0.72);
      color: #fff;
      font-size: 12px;
    }

    .empty {
      color: rgba(255, 255, 255, 0.64);
      font-size: 15px;
      text-align: center;
      padding: 24px;
    }

    .side {
      border-left: 1px solid var(--line);
      padding: 18px;
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 18px;
      min-height: 0;
      background: rgba(255, 255, 255, 0.34);
    }

    .controls {
      display: grid;
      gap: 12px;
    }

    .button-row {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
    }

    button {
      height: 36px;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
    }

    button.primary {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }

    button:disabled {
      cursor: default;
      color: var(--muted);
      background: var(--soft);
    }

    .upload-button {
      min-width: 128px;
    }

    .file-input {
      display: none;
    }

    .scrubber {
      display: grid;
      gap: 6px;
    }

    input[type="range"] {
      accent-color: var(--accent);
    }

    .readout {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }

    .metric {
      border-top: 1px solid var(--line);
      padding-top: 10px;
      min-width: 0;
    }

    .metric .label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      margin-bottom: 4px;
    }

    .metric .value {
      font-size: 14px;
      overflow-wrap: anywhere;
    }

    .vectors {
      min-height: 0;
      overflow: auto;
      display: grid;
      gap: 14px;
      align-content: start;
    }

    .vector-block {
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }

    .vector-block h2 {
      margin: 0 0 8px;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 540;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #343430;
      font-size: 12px;
      line-height: 1.45;
    }

    @media (max-width: 980px) {
      .topbar {
        grid-template-columns: 1fr;
      }

      .selectors {
        grid-template-columns: 1fr;
      }

      .workspace {
        grid-template-columns: 1fr;
      }

      .side {
        border-left: 0;
        border-top: 1px solid var(--line);
      }
    }

    @media (max-width: 720px) {
      .viewer {
        grid-template-rows: auto auto;
      }

      .top-row {
        grid-template-columns: 1fr;
      }

      .viewport {
        aspect-ratio: 4 / 3;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-title">LWH HDF5 Viewer</div>
        <div class="brand-subtitle">Local playback</div>
      </div>
      <div class="selectors">
        <div class="field">
          <label for="fileSelect">File</label>
          <select id="fileSelect"></select>
        </div>
        <div class="field">
          <label for="episodeSelect">Episode</label>
          <select id="episodeSelect"></select>
        </div>
        <div class="field">
          <label>Local</label>
          <button id="uploadButton" class="upload-button" type="button">Choose HDF5</button>
          <input id="uploadInput" class="file-input" type="file" accept=".hdf5,.h5" />
        </div>
      </div>
      <div class="status">
        <span id="statusDot" class="dot"></span>
        <span id="statusText">Loading</span>
      </div>
    </header>

    <main class="workspace">
      <section class="viewer">
        <div class="top-row">
          <article class="viewport" data-slot="front">
            <div class="viewport-header">
              <span>front</span>
              <select class="camera-select" id="slotFront"></select>
            </div>
            <img id="imgFront" alt="front camera" />
            <div class="empty" id="emptyFront">front 未录制</div>
          </article>
          <article class="viewport" data-slot="wrist">
            <div class="viewport-header">
              <span>wrist</span>
              <select class="camera-select" id="slotWrist"></select>
            </div>
            <img id="imgWrist" alt="wrist camera" />
            <div class="empty" id="emptyWrist">wrist 未录制</div>
          </article>
        </div>
        <div class="bottom-row">
          <article class="viewport" data-slot="overview">
            <div class="viewport-header">
              <span>overview</span>
              <select class="camera-select" id="slotOverview"></select>
            </div>
            <img id="imgOverview" alt="overview camera" />
            <div class="empty" id="emptyOverview">overview 未录制</div>
          </article>
        </div>
      </section>

      <aside class="side">
        <section class="controls">
          <div class="button-row">
            <button id="prevButton" type="button">Prev</button>
            <button id="playButton" type="button" class="primary">Play</button>
            <button id="nextButton" type="button">Next</button>
          </div>
          <div class="field">
            <label for="speedSelect">Speed</label>
            <select id="speedSelect">
              <option value="0.25">0.25x</option>
              <option value="0.5">0.5x</option>
              <option value="1" selected>1x</option>
              <option value="2">2x</option>
            </select>
          </div>
          <div class="scrubber">
            <label for="frameSlider">Timeline</label>
            <input id="frameSlider" type="range" min="0" max="0" value="0" />
          </div>
        </section>

        <section class="readout">
          <div class="metric"><div class="label">Frame</div><div class="value" id="frameValue">0 / 0</div></div>
          <div class="metric"><div class="label">Timestamp</div><div class="value" id="timeValue">0.000 s</div></div>
          <div class="metric"><div class="label">FPS</div><div class="value" id="fpsValue">30</div></div>
          <div class="metric"><div class="label">Outcome</div><div class="value" id="outcomeValue">-</div></div>
        </section>

        <section class="vectors">
          <div class="vector-block">
            <h2>Action</h2>
            <pre id="actionValue">[]</pre>
          </div>
          <div class="vector-block">
            <h2>State</h2>
            <pre id="stateValue">[]</pre>
          </div>
          <div class="vector-block">
            <h2>Dataset</h2>
            <pre id="datasetValue">No file selected.</pre>
          </div>
        </section>
      </aside>
    </main>
  </div>

  <script>
    const state = {
      files: [],
      summary: null,
      fileId: null,
      episodeId: null,
      frame: 0,
      playing: false,
      timer: null,
      fps: 30,
      cameras: [],
    };

    const els = {
      fileSelect: document.getElementById("fileSelect"),
      episodeSelect: document.getElementById("episodeSelect"),
      uploadButton: document.getElementById("uploadButton"),
      uploadInput: document.getElementById("uploadInput"),
      statusDot: document.getElementById("statusDot"),
      statusText: document.getElementById("statusText"),
      prevButton: document.getElementById("prevButton"),
      playButton: document.getElementById("playButton"),
      nextButton: document.getElementById("nextButton"),
      speedSelect: document.getElementById("speedSelect"),
      frameSlider: document.getElementById("frameSlider"),
      frameValue: document.getElementById("frameValue"),
      timeValue: document.getElementById("timeValue"),
      fpsValue: document.getElementById("fpsValue"),
      outcomeValue: document.getElementById("outcomeValue"),
      actionValue: document.getElementById("actionValue"),
      stateValue: document.getElementById("stateValue"),
      datasetValue: document.getElementById("datasetValue"),
      slotFront: document.getElementById("slotFront"),
      slotWrist: document.getElementById("slotWrist"),
      slotOverview: document.getElementById("slotOverview"),
      imgFront: document.getElementById("imgFront"),
      imgWrist: document.getElementById("imgWrist"),
      imgOverview: document.getElementById("imgOverview"),
      emptyFront: document.getElementById("emptyFront"),
      emptyWrist: document.getElementById("emptyWrist"),
      emptyOverview: document.getElementById("emptyOverview"),
    };

    function setStatus(text, kind = "") {
      els.statusText.textContent = text;
      els.statusDot.className = `dot ${kind}`;
    }

    async function api(path) {
      const response = await fetch(path);
      const payload = await response.json();
      if (!response.ok || payload.error) {
        throw new Error(payload.error || response.statusText);
      }
      return payload;
    }

    async function uploadLocalFile(file) {
      const form = new FormData();
      form.append("file", file);
      setStatus("Uploading");
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const payload = await response.json();
      if (!response.ok || payload.error) {
        throw new Error(payload.error || response.statusText);
      }
      state.files = payload.files;
      fillSelect(
        els.fileSelect,
        state.files.map((item) => ({ value: item.id, label: item.name })),
        payload.file.id,
      );
      await loadSummary(payload.file.id);
    }

    function currentEpisode() {
      if (!state.summary) return null;
      return state.summary.episodes.find((episode) => episode.id === state.episodeId) || null;
    }

    function formatVector(values) {
      if (!values) return "missing";
      return values.map((value, index) => `${String(index).padStart(2, "0")}: ${value.toFixed(5)}`).join("\n");
    }

    function fillSelect(select, options, selected) {
      select.innerHTML = "";
      for (const option of options) {
        const node = document.createElement("option");
        node.value = option.value;
        node.textContent = option.label;
        if (option.value === selected) node.selected = true;
        select.appendChild(node);
      }
    }

    function cameraOptions() {
      const values = Array.from(new Set(["front", "wrist", "overview", ...state.cameras]));
      return values.map((value) => ({ value, label: value }));
    }

    function configureCameraSlots() {
      const options = cameraOptions();
      fillSelect(els.slotFront, options, state.cameras.includes("front") ? "front" : options[0]?.value);
      fillSelect(els.slotWrist, options, state.cameras.includes("wrist") ? "wrist" : options[0]?.value);
      fillSelect(els.slotOverview, options, state.cameras.includes("overview") ? "overview" : "overview");
    }

    function imageUrl(camera) {
      const cacheKey = Date.now();
      return `/api/files/${state.fileId}/episodes/${state.episodeId}/frame?camera=${encodeURIComponent(camera)}&frame=${state.frame}&_=${cacheKey}`;
    }

    function updateImage(img, empty, camera) {
      if (!state.cameras.includes(camera)) {
        img.removeAttribute("src");
        img.style.display = "none";
        empty.style.display = "block";
        empty.textContent = `${camera} 未录制`;
        return;
      }
      empty.style.display = "none";
      img.style.display = "block";
      img.src = imageUrl(camera);
    }

    async function renderFrame() {
      const episode = currentEpisode();
      if (!episode) return;
      const maxFrame = Math.max(episode.num_samples - 1, 0);
      state.frame = Math.min(Math.max(state.frame, 0), maxFrame);
      els.frameSlider.max = String(maxFrame);
      els.frameSlider.value = String(state.frame);

      updateImage(els.imgFront, els.emptyFront, els.slotFront.value);
      updateImage(els.imgWrist, els.emptyWrist, els.slotWrist.value);
      updateImage(els.imgOverview, els.emptyOverview, els.slotOverview.value);

      try {
        const sample = await api(`/api/files/${state.fileId}/episodes/${state.episodeId}/sample?frame=${state.frame}`);
        els.frameValue.textContent = `${sample.frame_index + 1} / ${sample.num_samples}`;
        els.timeValue.textContent = `${sample.timestamp.toFixed(3)} s`;
        els.actionValue.textContent = formatVector(sample.action);
        els.stateValue.textContent = formatVector(sample.state);
      } catch (error) {
        setStatus(error.message, "bad");
      }
    }

    function stopPlayback() {
      state.playing = false;
      if (state.timer) clearInterval(state.timer);
      state.timer = null;
      els.playButton.textContent = "Play";
    }

    function startPlayback() {
      const episode = currentEpisode();
      if (!episode || episode.num_samples <= 0) return;
      state.playing = true;
      els.playButton.textContent = "Pause";
      const speed = Number(els.speedSelect.value);
      const intervalMs = Math.max(8, 1000 / Math.max(state.fps * speed, 1));
      state.timer = setInterval(() => {
        const maxFrame = Math.max(episode.num_samples - 1, 0);
        state.frame = state.frame >= maxFrame ? 0 : state.frame + 1;
        renderFrame();
      }, intervalMs);
    }

    async function loadFiles() {
      const payload = await api("/api/files");
      state.files = payload.files;
      if (state.files.length === 0) {
        setStatus("No HDF5 files", "bad");
        fillSelect(els.fileSelect, [{ value: "", label: "No files found" }], "");
        return;
      }
      fillSelect(
        els.fileSelect,
        state.files.map((file) => ({ value: file.id, label: file.name })),
        state.files[0].id,
      );
      await loadSummary(state.files[0].id);
    }

    async function loadSummary(fileId) {
      stopPlayback();
      state.fileId = fileId;
      state.summary = await api(`/api/files/${fileId}/summary`);
      state.fps = state.summary.fps || 30;
      const episodes = state.summary.episodes || [];
      state.cameras = episodes[0]?.camera_keys || state.summary.camera_keys || [];
      fillSelect(
        els.episodeSelect,
        episodes.map((episode) => ({
          value: episode.id,
          label: `${episode.label} · ${episode.success ? "success" : "failure"} · ${episode.num_samples} frames`,
        })),
        episodes[0]?.id || "",
      );
      state.episodeId = episodes[0]?.id || null;
      configureCameraSlots();
      state.frame = 0;
      els.fpsValue.textContent = String(state.fps);
      els.datasetValue.textContent = JSON.stringify({
        file: state.summary.name,
        task: state.summary.task,
        teleop_device: state.summary.teleop_device,
        cameras: state.cameras,
        joint_names: state.summary.joint_names,
      }, null, 2);
      updateEpisodeReadout();
      setStatus("Ready", "ok");
      await renderFrame();
    }

    function updateEpisodeReadout() {
      const episode = currentEpisode();
      if (!episode) {
        els.outcomeValue.textContent = "-";
        return;
      }
      els.outcomeValue.textContent = episode.success ? "success" : "failure";
    }

    els.fileSelect.addEventListener("change", () => loadSummary(els.fileSelect.value).catch((error) => setStatus(error.message, "bad")));
    els.uploadButton.addEventListener("click", () => els.uploadInput.click());
    els.uploadInput.addEventListener("change", () => {
      const file = els.uploadInput.files[0];
      if (!file) return;
      uploadLocalFile(file).catch((error) => setStatus(error.message, "bad"));
      els.uploadInput.value = "";
    });
    els.episodeSelect.addEventListener("change", () => {
      stopPlayback();
      state.episodeId = els.episodeSelect.value;
      const episode = currentEpisode();
      state.cameras = episode?.camera_keys || state.summary?.camera_keys || [];
      configureCameraSlots();
      state.frame = 0;
      updateEpisodeReadout();
      renderFrame();
    });
    els.playButton.addEventListener("click", () => state.playing ? stopPlayback() : startPlayback());
    els.prevButton.addEventListener("click", () => {
      stopPlayback();
      state.frame -= 1;
      renderFrame();
    });
    els.nextButton.addEventListener("click", () => {
      stopPlayback();
      state.frame += 1;
      renderFrame();
    });
    els.frameSlider.addEventListener("input", () => {
      stopPlayback();
      state.frame = Number(els.frameSlider.value);
      renderFrame();
    });
    els.speedSelect.addEventListener("change", () => {
      if (state.playing) {
        stopPlayback();
        startPlayback();
      }
    });
    [els.slotFront, els.slotWrist, els.slotOverview].forEach((select) => {
      select.addEventListener("change", renderFrame);
    });

    loadFiles().catch((error) => setStatus(error.message, "bad"));
  </script>
</body>
</html>
"""


def main() -> None:
    if IMPORT_ERROR is not None:
        raise RuntimeError(
            "Missing dependency for HDF5 viewer. Install h5py and numpy in the Python environment."
        ) from IMPORT_ERROR
    args = parse_args()
    catalog = HDF5Catalog(args.data_dir, args.file)
    ViewerHandler.catalog = catalog
    server = create_server(args.host, args.port, ViewerHandler)
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    print(f"LWH_HDF5_VIEWER_READY url={url} data_dir={args.data_dir}", flush=True)
    print("Press Ctrl+C to stop the viewer.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLWH_HDF5_VIEWER_STOPPED", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
