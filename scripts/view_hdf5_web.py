#!/usr/bin/env python3
"""Serve a lightweight browser viewer for LWH HDF5 teleoperation recordings.

已完成：
- 这是纯 HDF5 数据查看器，不启动 IsaacSim，不执行 env.step，不访问真实 leader/follower。
- 默认扫描 datasets/hdf5，也支持网页内 Choose HDF5 手动选择本地文件。
- 支持 file/episode 下拉、三窗口同步图像回放、播放/暂停/逐帧/timeline/速度控制。
- 页面默认布局为上 40% front+wrist，下 60% overview，并支持拖拽调整相机区和侧栏尺寸。
- 读取并显示当前帧 timestamp、episode outcome，action/state 前 16 个值以主画面浮层显示。
- action/state 时间曲线（分桶降采样、逐维自动缩放、随帧游标），支持点击放大查看。
- 数据质量检查：timestamp 间隔/单调性、相机空白帧、缺失相机，异常 episode 标记。
- 质量报告 JSON 下载，用于快速筛查采集数据问题。
- 服务端 LRU 帧缓存，降低拖动 timeline 时的重复编码开销。
- 固定使用 --port 指定端口；端口被占用时会先清理旧进程，再绑定同一个端口。

录制端支持 --camera_mode triple，overview 第三视角会写入原始 HDF5；LeRobot 转换默认只读取
training_camera_keys，也就是 front/wrist，不会把 overview 混入训练输入。
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
from collections import OrderedDict
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


def list_metadata_string_values(h5_file: h5py.File, key: str) -> list[str]:
    metadata = h5_file.get("metadata")
    if metadata is None:
        return []
    values = read_string_dataset(metadata, key)
    if values:
        return values
    values = read_json_attr(metadata.attrs, key, None)
    if values:
        return [str(value) for value in values]
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
            "training_camera_keys": list_metadata_string_values(h5_file, "training_camera_keys"),
            "visualization_camera_keys": list_metadata_string_values(h5_file, "visualization_camera_keys"),
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


class FrameCache:
    """LRU 缓存编码后的 BMP 帧，拖动 timeline 时避免重复读盘和编码。"""

    def __init__(self, max_entries: int = 512) -> None:
        self._max_entries = max_entries
        self._store: "OrderedDict[tuple[str, str, str, int], bytes]" = OrderedDict()

    def get(self, path: Path, episode_id: str, camera_key: str, frame_index: int) -> bytes | None:
        key = (str(path), episode_id, camera_key, frame_index)
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def put(self, path: Path, episode_id: str, camera_key: str, frame_index: int, payload: bytes) -> None:
        key = (str(path), episode_id, camera_key, frame_index)
        self._store[key] = payload
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)


FRAME_CACHE = FrameCache()


def cached_encode_frame(path: Path, episode_id: str, camera_key: str, frame_index: int) -> bytes:
    """带 LRU 缓存的帧编码入口。"""
    cached = FRAME_CACHE.get(path, episode_id, camera_key, frame_index)
    if cached is not None:
        return cached
    payload = encode_frame(path, episode_id, camera_key, frame_index)
    FRAME_CACHE.put(path, episode_id, camera_key, frame_index, payload)
    return payload


def series_frame(path: Path, episode_id: str, max_points: int = 400) -> dict[str, Any]:
    """把 action/state 数值序列分桶降采样成 min/max 曲线数据。

    只读 action/state 这类小数值数组，不读图像，适合网页画时间曲线。
    """
    with h5py.File(path, "r") as h5_file:
        group = episode_root(h5_file)[episode_id]
        num_samples = int(group.attrs.get("num_samples", group["action"].shape[0] if "action" in group else 0))
        if num_samples < 1:
            raise ValueError("Episode has no frames.")

        def bucketize(array: np.ndarray) -> dict[str, Any]:
            total, dims = array.shape
            if total <= max_points:
                indices = list(range(total))
                values = [[float(array[t, d]) for t in range(total)] for d in range(dims)]
                return {"indices": indices, "mins": values, "maxs": values}

            bucket_size = (total + max_points - 1) // max_points
            indices: list[int] = []
            mins: list[list[float]] = [[] for _ in range(dims)]
            maxs: list[list[float]] = [[] for _ in range(dims)]
            for start in range(0, total, bucket_size):
                chunk = array[start : start + bucket_size]
                indices.append(start + chunk.shape[0] // 2)
                for dim in range(dims):
                    mins[dim].append(float(chunk[:, dim].min()))
                    maxs[dim].append(float(chunk[:, dim].max()))
            return {"indices": indices, "mins": mins, "maxs": maxs}

        def read_series(dataset_path: str) -> dict[str, Any] | None:
            if dataset_path not in group:
                return None
            array = np.asarray(group[dataset_path], dtype=np.float32)
            if array.ndim != 2:
                return None
            return bucketize(array)

        return {
            "num_samples": num_samples,
            "action": read_series("action"),
            "state": read_series("observation/state"),
        }


# 空白帧判据与录制端 validate 保持一致：采样帧 RGB 标准差小于 1 视为空白。
BLANK_STD_THRESHOLD = 1.0
QUALITY_SAMPLE_FRAMES = 8


def file_quality(path: Path) -> dict[str, Any]:
    """检查文件内所有 episode 的 timestamp 间隔/单调性和相机空白帧。

    图像只采样每个 camera 最多 8 帧，避免大文件全量扫描过慢。
    """
    with h5py.File(path, "r") as h5_file:
        root = episode_root(h5_file)
        names = sorted(root.keys(), key=episode_sort_key)
        metadata = h5_file.get("metadata")
        metadata_attrs = metadata.attrs if metadata is not None else {}
        file_camera_keys = list_camera_keys(h5_file, root[names[0]] if names else None)
        episodes: list[dict[str, Any]] = []
        for name in names:
            group = root[name]
            num_samples = int(group.attrs.get("num_samples", group["action"].shape[0] if "action" in group else 0))
            timestamps = np.asarray(group["timestamp"][:], dtype=np.float64) if "timestamp" in group else np.array([])
            if timestamps.shape[0] == num_samples and num_samples > 1:
                diffs = np.diff(timestamps)
                non_monotonic = int(np.count_nonzero(diffs < -1.0e-6))
                max_gap_s = float(diffs.max())
                median_interval_s = float(np.median(diffs))
                actual_fps = float(1.0 / median_interval_s) if median_interval_s > 1.0e-6 else None
            else:
                non_monotonic = 0
                max_gap_s = 0.0
                median_interval_s = 0.0
                actual_fps = None

            episode_cameras = sorted(group["observation/images"].keys()) if "observation/images" in group else []
            blank_cameras: list[str] = []
            for camera_key in episode_cameras:
                dataset = group[f"observation/images/{camera_key}"]
                sample_indices = np.unique(
                    np.linspace(0, dataset.shape[0] - 1, QUALITY_SAMPLE_FRAMES, dtype=np.int64)
                )
                stds = [float(np.asarray(dataset[int(i)])[..., :3].std()) for i in sample_indices]
                if min(stds) < BLANK_STD_THRESHOLD:
                    blank_cameras.append(camera_key)

            missing_cameras = [key for key in file_camera_keys if key not in episode_cameras]
            anomalies: list[str] = []
            if num_samples < 1:
                anomalies.append("no frames")
            if non_monotonic > 0:
                anomalies.append(f"{non_monotonic} timestamp backward jumps")
            if actual_fps is not None and actual_fps < 15.0:
                anomalies.append(f"low fps {actual_fps:.1f}")
            for camera_key in blank_cameras:
                anomalies.append(f"{camera_key} blank")
            for camera_key in missing_cameras:
                anomalies.append(f"{camera_key} 未录制")

            episodes.append(
                {
                    "id": name,
                    "episode_index": int(group.attrs.get("episode_index", episode_sort_key(name))),
                    "success": bool(group.attrs.get("success", False)),
                    "valid": bool(group.attrs.get("valid", True)),
                    "outcome": str(group.attrs.get("outcome", "")),
                    "num_samples": num_samples,
                    "duration_s": float(timestamps[-1] - timestamps[0]) if timestamps.shape[0] > 1 else 0.0,
                    "median_frame_interval_s": median_interval_s,
                    "actual_fps": actual_fps,
                    "max_frame_gap_s": max_gap_s,
                    "non_monotonic_count": non_monotonic,
                    "camera_keys": episode_cameras,
                    "blank_cameras": blank_cameras,
                    "missing_cameras": missing_cameras,
                    "anomalies": anomalies,
                }
            )

        return {
            "path": str(path),
            "name": path.name,
            "task": str(metadata_attrs.get("task", "")),
            "fps": int(metadata_attrs.get("fps", 30)),
            "teleop_device": str(metadata_attrs.get("teleop_device", "")),
            "camera_keys": file_camera_keys,
            "training_camera_keys": list_metadata_string_values(h5_file, "training_camera_keys"),
            "visualization_camera_keys": list_metadata_string_values(h5_file, "visualization_camera_keys"),
            "overview_recorded": "overview" in file_camera_keys,
            "episodes": episodes,
        }


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# 质量报告按 (path, mtime) 缓存，避免每次点击都重扫 HDF5。
QUALITY_CACHE: "OrderedDict[tuple[str, int], dict[str, Any]]" = OrderedDict()
QUALITY_CACHE_MAX = 8


def cached_file_quality(path: Path) -> dict[str, Any]:
    stat = path.stat()
    key = (str(path), int(stat.st_mtime), int(stat.st_size))
    if key in QUALITY_CACHE:
        QUALITY_CACHE.move_to_end(key)
        return QUALITY_CACHE[key]
    report = file_quality(path)
    QUALITY_CACHE[key] = report
    QUALITY_CACHE.move_to_end(key)
    while len(QUALITY_CACHE) > QUALITY_CACHE_MAX:
        QUALITY_CACHE.popitem(last=False)
    return report


def html_page() -> bytes:
    return INDEX_HTML.encode("utf-8")


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """允许旧 viewer 退出后立即复用同一端口。"""

    allow_reuse_address = True


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
        except (PermissionError, ProcessLookupError):
            pass

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not pids_for_socket_inodes(socket_inodes_for_port(port)):
            return pids
        time.sleep(0.05)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not pids_for_socket_inodes(socket_inodes_for_port(port)):
            break
        time.sleep(0.05)
    return pids


def create_server(host: str, port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    """固定使用请求端口；若被旧进程占用，则先清理旧进程。"""
    try:
        return ReusableThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        if exc.errno not in (98, 48):
            raise
        killed_pids = kill_processes_on_port(port)
        if killed_pids:
            print(f"网页端口清理 port={port} pids={killed_pids}", flush=True)
        return ReusableThreadingHTTPServer((host, port), handler)


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
            elif path.startswith("/api/files/") and path.endswith("/quality"):
                file_id = path.split("/")[3]
                report = cached_file_quality(self.catalog.resolve(file_id))
                if query.get("download", ["0"])[0] == "1":
                    filename = f"quality_report_{Path(report['name']).stem}.json"
                    self.send_blob(
                        json_bytes(report),
                        "application/json; charset=utf-8",
                        extra_headers=[("Content-Disposition", f'attachment; filename="{filename}"')],
                    )
                else:
                    self.send_json(report)
            elif path.startswith("/api/files/") and "/series" in path:
                parts = path.strip("/").split("/")
                file_id = parts[2]
                episode_id = parts[4]
                self.send_json(series_frame(self.catalog.resolve(file_id), episode_id))
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
                image = cached_encode_frame(self.catalog.resolve(file_id), episode_id, camera, frame)
                self.send_blob(image, "image/bmp", cache_control="no-store")
            elif path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                content_type = mimetypes.guess_type(path)[0] or "text/plain"
                self.send_error(HTTPStatus.NOT_FOUND, f"Not found: {path} ({content_type})")
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except (BrokenPipeError, ConnectionResetError):
                return

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
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except (BrokenPipeError, ConnectionResetError):
                return

    def log_message(self, fmt: str, *args: Any) -> None:
        if "/frame?" in self.path or "/sample?" in self.path:
            return
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
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache_control)
            for header_name, header_value in extra_headers or []:
                self.send_header(header_name, header_value)
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LWH HDF5 Viewer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f4f1;
      --panel: #ffffff;
      --panel-soft: #fafaf7;
      --line: #ddddda;
      --line-strong: #c7c7c1;
      --text: #171717;
      --muted: #74746d;
      --soft: #ecece7;
      --accent: #111111;
      --ok: #1f7a45;
      --bad: #a33930;
      --warning: #9a6b12;
      --side-width: 360px;
      --viewer-top: 40%;
      --camera-left: 50%;
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
      padding: 18px 24px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 252, 0.94);
      backdrop-filter: blur(10px);
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
      grid-template-columns: minmax(0, 1fr) 8px var(--side-width);
      gap: 0;
      min-height: 0;
    }

    .viewer {
      display: grid;
      grid-template-rows: var(--viewer-top) 8px minmax(0, 1fr);
      gap: 0;
      padding: 18px;
      min-height: 0;
    }

    .top-row {
      display: grid;
      grid-template-columns: var(--camera-left) 8px minmax(0, 1fr);
      gap: 0;
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
      border-radius: 6px;
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

    .viewport-tools {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }

    .mini-dark-button {
      height: 26px;
      border: 1px solid rgba(255, 255, 255, 0.22);
      background: rgba(18, 18, 18, 0.72);
      color: #fff;
      border-radius: 4px;
      font-size: 12px;
      padding: 0 9px;
    }

    .empty {
      color: rgba(255, 255, 255, 0.64);
      font-size: 15px;
      text-align: center;
      padding: 24px;
    }

    .resizer {
      position: relative;
      z-index: 6;
      touch-action: none;
    }

    .side-resizer,
    .column-resizer {
      cursor: col-resize;
    }

    .row-resizer {
      cursor: row-resize;
    }

    .side-resizer::before,
    .column-resizer::before {
      content: "";
      position: absolute;
      top: 18px;
      bottom: 18px;
      left: 3px;
      width: 2px;
      border-radius: 99px;
      background: var(--line-strong);
      opacity: 0.65;
    }

    .row-resizer::before {
      content: "";
      position: absolute;
      left: 18px;
      right: 18px;
      top: 3px;
      height: 2px;
      border-radius: 99px;
      background: var(--line-strong);
      opacity: 0.65;
    }

    body.resizing {
      user-select: none;
      cursor: grabbing;
    }

    .vector-overlay {
      position: absolute;
      top: 42px;
      left: 10px;
      width: min(390px, calc(100% - 20px));
      max-height: calc(100% - 54px);
      overflow: auto;
      z-index: 3;
      color: #f7f7f0;
      background: rgba(12, 12, 12, 0.72);
      border: 1px solid rgba(255, 255, 255, 0.16);
      border-radius: 6px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.22);
      backdrop-filter: blur(10px);
    }

    .vector-overlay.hidden {
      display: none;
    }

    .vector-overlay-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 8px 9px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.12);
      font-size: 12px;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.76);
    }

    .vector-overlay-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
    }

    .vector-overlay-block {
      min-width: 0;
      padding: 9px;
    }

    .vector-overlay-block + .vector-overlay-block {
      border-left: 1px solid rgba(255, 255, 255, 0.12);
    }

    .vector-overlay-block h2 {
      margin: 0 0 7px;
      font-size: 11px;
      font-weight: 560;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.68);
    }

    .vector-overlay pre {
      color: #f7f7f0;
      font-size: 12px;
      line-height: 1.45;
    }

    .side {
      border-left: 1px solid var(--line);
      padding: 18px;
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr);
      gap: 18px;
      min-height: 0;
      background: rgba(255, 255, 255, 0.55);
    }

    .charts {
      display: grid;
      gap: 12px;
    }

    .chart-block {
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }

    .chart-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 6px;
    }

    .chart-block h2 {
      margin: 0;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 540;
    }

    .chart-block canvas {
      width: 100%;
      height: 124px;
      display: block;
      background: #fbfbf9;
      border: 1px solid var(--line);
      border-radius: 4px;
      cursor: zoom-in;
    }

    .mini-button {
      height: 24px;
      padding: 0 10px;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      background: var(--panel-soft);
      color: var(--text);
      font-size: 12px;
      line-height: 1;
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .quality {
      display: grid;
      gap: 8px;
    }

    .quality-list {
      display: grid;
      gap: 6px;
      font-size: 12px;
      max-height: 220px;
      overflow: auto;
    }

    .quality-item {
      border-top: 1px solid var(--line);
      padding-top: 6px;
      display: grid;
      gap: 2px;
    }

    .quality-item .head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }

    .quality-item .meta {
      color: var(--muted);
      font-size: 11px;
    }

    .quality-item .anomalies {
      color: var(--bad);
    }

    .quality-item .clean {
      color: var(--ok);
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

    .quality-actions {
      grid-template-columns: 1fr 1fr;
    }

    button {
      height: 36px;
      padding: 0 12px;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      background: var(--panel);
      color: var(--text);
      cursor: pointer;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
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
      display: none;
    }

    .chart-modal {
      position: fixed;
      inset: 0;
      z-index: 20;
      background: rgba(16, 16, 16, 0.64);
      display: grid;
      place-items: center;
      padding: 24px;
    }

    .chart-modal.hidden {
      display: none;
    }

    .chart-modal-panel {
      width: min(1100px, 100%);
      height: min(82vh, 760px);
      background: var(--panel);
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.28);
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 0;
    }

    .chart-modal-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 16px 10px;
      border-bottom: 1px solid var(--line);
    }

    .chart-modal-head strong {
      font-size: 14px;
      display: block;
    }

    .chart-modal-head span {
      color: var(--muted);
      font-size: 12px;
    }

    .chart-modal-canvas-wrap {
      min-height: 0;
      padding: 14px;
    }

    .chart-modal-canvas {
      width: 100%;
      height: 100%;
      display: block;
      background: #fcfcfa;
      border: 1px solid var(--line);
      border-radius: 4px;
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

      .side-resizer {
        display: none;
      }

      .side {
        border-left: 0;
        border-top: 1px solid var(--line);
      }
    }

    @media (max-width: 720px) {
      .viewer {
        grid-template-rows: auto auto;
        gap: 12px;
      }

      .top-row {
        grid-template-columns: 1fr;
        gap: 12px;
      }

      .column-resizer,
      .row-resizer {
        display: none;
      }

      .viewport {
        aspect-ratio: 4 / 3;
      }

      .vector-overlay {
        position: absolute;
        top: 42px;
        left: 8px;
        right: 8px;
        width: auto;
      }

      .vector-overlay-grid {
        grid-template-columns: 1fr;
      }

      .vector-overlay-block + .vector-overlay-block {
        border-left: 0;
        border-top: 1px solid rgba(255, 255, 255, 0.12);
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

    <main class="workspace" id="workspace">
      <section class="viewer" id="viewer">
        <div class="top-row">
          <article class="viewport" data-slot="front">
            <div class="viewport-header">
              <span>front</span>
              <select class="camera-select" id="slotFront"></select>
            </div>
            <img id="imgFront" alt="front camera" />
            <div class="empty" id="emptyFront">front 未录制</div>
          </article>
          <div class="resizer column-resizer" data-resize="camera-split" aria-label="Adjust camera split"></div>
          <article class="viewport" data-slot="wrist">
            <div class="viewport-header">
              <span>wrist</span>
              <select class="camera-select" id="slotWrist"></select>
            </div>
            <img id="imgWrist" alt="wrist camera" />
            <div class="empty" id="emptyWrist">wrist 未录制</div>
          </article>
        </div>
        <div class="resizer row-resizer" data-resize="viewer-split" aria-label="Adjust viewer split"></div>
        <div class="bottom-row">
          <article class="viewport" data-slot="overview">
            <div class="viewport-header">
              <span>overview</span>
              <div class="viewport-tools">
                <button class="mini-dark-button" id="toggleVectorButton" type="button">Values</button>
                <select class="camera-select" id="slotOverview"></select>
              </div>
            </div>
            <img id="imgOverview" alt="overview camera" />
            <div class="empty" id="emptyOverview">overview 未录制</div>
            <div class="vector-overlay" id="vectorOverlay">
              <div class="vector-overlay-head">
                <span>Action / State</span>
                <button class="mini-dark-button" id="hideVectorButton" type="button">Hide</button>
              </div>
              <div class="vector-overlay-grid">
                <div class="vector-overlay-block">
                  <h2>Action</h2>
                  <pre id="actionValue">[]</pre>
                </div>
                <div class="vector-overlay-block">
                  <h2>State</h2>
                  <pre id="stateValue">[]</pre>
                </div>
              </div>
            </div>
          </article>
        </div>
      </section>
      <div class="resizer side-resizer" data-resize="side-panel" aria-label="Adjust side panel width"></div>

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

        <section class="charts">
          <div class="chart-block">
            <div class="chart-head">
              <h2>Action curves</h2>
              <button class="mini-button" type="button" data-chart-open="action">放大</button>
            </div>
            <canvas id="actionChart" title="点击放大"></canvas>
          </div>
          <div class="chart-block">
            <div class="chart-head">
              <h2>State curves</h2>
              <button class="mini-button" type="button" data-chart-open="state">放大</button>
            </div>
            <canvas id="stateChart" title="点击放大"></canvas>
          </div>
        </section>

        <section class="quality">
          <div class="button-row quality-actions">
            <button id="qualityButton" type="button">质量报告</button>
            <button id="qualityDownload" type="button" disabled>下载 JSON</button>
          </div>
          <div class="quality-list" id="qualityList"></div>
        </section>
      </aside>
    </main>
  </div>

  <div class="chart-modal hidden" id="chartModal" aria-hidden="true">
    <div class="chart-modal-panel" role="dialog" aria-modal="true" aria-labelledby="chartModalTitle">
      <div class="chart-modal-head">
        <div>
          <strong id="chartModalTitle">Chart</strong>
          <span id="chartModalHint">点击图表空白处或按 Esc 关闭</span>
        </div>
        <button id="chartModalClose" type="button">Close</button>
      </div>
      <div class="chart-modal-canvas-wrap">
        <canvas class="chart-modal-canvas" id="chartModalCanvas"></canvas>
      </div>
    </div>
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
      series: null,
      quality: null,
      showVectors: true,
      chartModal: null,
      imageLoading: {
        front: false,
        wrist: false,
        overview: false,
      },
      sampleLoading: false,
      sampleRequestId: 0,
      layout: {
        sideWidth: 360,
        viewerTop: 40,
        cameraLeft: 50,
      },
    };

    const els = {
      workspace: document.getElementById("workspace"),
      viewer: document.getElementById("viewer"),
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
      slotFront: document.getElementById("slotFront"),
      slotWrist: document.getElementById("slotWrist"),
      slotOverview: document.getElementById("slotOverview"),
      imgFront: document.getElementById("imgFront"),
      imgWrist: document.getElementById("imgWrist"),
      imgOverview: document.getElementById("imgOverview"),
      emptyFront: document.getElementById("emptyFront"),
      emptyWrist: document.getElementById("emptyWrist"),
      emptyOverview: document.getElementById("emptyOverview"),
      actionChart: document.getElementById("actionChart"),
      stateChart: document.getElementById("stateChart"),
      qualityButton: document.getElementById("qualityButton"),
      qualityDownload: document.getElementById("qualityDownload"),
      qualityList: document.getElementById("qualityList"),
      vectorOverlay: document.getElementById("vectorOverlay"),
      toggleVectorButton: document.getElementById("toggleVectorButton"),
      hideVectorButton: document.getElementById("hideVectorButton"),
      chartModal: document.getElementById("chartModal"),
      chartModalCanvas: document.getElementById("chartModalCanvas"),
      chartModalTitle: document.getElementById("chartModalTitle"),
      chartModalHint: document.getElementById("chartModalHint"),
      chartModalClose: document.getElementById("chartModalClose"),
      chartOpenButtons: Array.from(document.querySelectorAll("[data-chart-open]")),
      resizeHandles: Array.from(document.querySelectorAll("[data-resize]")),
    };

    const CHART_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f", "#00a2a2", "#b2793d"];

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

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
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

    function syncLayoutVariables() {
      document.documentElement.style.setProperty("--side-width", `${state.layout.sideWidth}px`);
      document.documentElement.style.setProperty("--viewer-top", `${state.layout.viewerTop}%`);
      document.documentElement.style.setProperty("--camera-left", `${state.layout.cameraLeft}%`);
    }

    function setVectorOverlayVisible(visible) {
      state.showVectors = visible;
      els.vectorOverlay.classList.toggle("hidden", !visible);
      els.toggleVectorButton.textContent = visible ? "Hide" : "Values";
    }

    function openChartModal(kind) {
      state.chartModal = kind;
      const title = kind === "action" ? "Action curves" : "State curves";
      els.chartModalTitle.textContent = title;
      els.chartModalHint.textContent = "点击空白处或按 Esc 关闭";
      els.chartModal.classList.remove("hidden");
      els.chartModal.setAttribute("aria-hidden", "false");
      drawChartModal();
    }

    function closeChartModal() {
      state.chartModal = null;
      els.chartModal.classList.add("hidden");
      els.chartModal.setAttribute("aria-hidden", "true");
    }

    function configureCameraSlots() {
      const options = cameraOptions();
      fillSelect(els.slotFront, options, state.cameras.includes("front") ? "front" : options[0]?.value);
      fillSelect(els.slotWrist, options, state.cameras.includes("wrist") ? "wrist" : options[0]?.value);
      fillSelect(els.slotOverview, options, state.cameras.includes("overview") ? "overview" : "overview");
    }

    function imageUrl(camera) {
      return `/api/files/${state.fileId}/episodes/${state.episodeId}/frame?camera=${encodeURIComponent(camera)}&frame=${state.frame}`;
    }

    function updateImage(img, empty, camera, slotName) {
      if (!state.cameras.includes(camera)) {
        img.removeAttribute("src");
        img.style.display = "none";
        empty.style.display = "block";
        empty.textContent = `${camera} 未录制`;
        state.imageLoading[slotName] = false;
        return;
      }
      if (state.playing && state.imageLoading[slotName]) {
        return;
      }
      empty.style.display = "none";
      img.style.display = "block";
      state.imageLoading[slotName] = true;
      img.onload = () => {
        state.imageLoading[slotName] = false;
      };
      img.onerror = () => {
        state.imageLoading[slotName] = false;
      };
      img.src = imageUrl(camera);
    }

    function drawSeriesChart(canvas, series, labels, cursorIndex, options = {}) {
      const large = Boolean(options.large);
      const ctx = canvas.getContext("2d");
      const dpr = window.devicePixelRatio || 1;
      const cssW = canvas.clientWidth || 280;
      const cssH = canvas.clientHeight || 110;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);
      if (!series) {
        ctx.fillStyle = "#999";
        ctx.font = large ? "13px sans-serif" : "12px sans-serif";
        ctx.fillText("missing", 8, large ? 28 : 20);
        return;
      }
      const count = series.indices.length;
      if (count < 1) return;
      const tMin = series.indices[0];
      const tMax = series.indices[count - 1] || 1;
      const padL = large ? 12 : 8;
      const padR = large ? 12 : 8;
      const padT = large ? 10 : 6;
      const padB = large ? 28 : 18;
      const plotW = cssW - padL - padR;
      const plotH = cssH - padT - padB;
      const xOf = (t) => padL + ((t - tMin) / Math.max(tMax - tMin, 1)) * plotW;
      ctx.font = large ? "10px sans-serif" : "9px sans-serif";
      series.mins.forEach((mins, dim) => {
        const all = mins.concat(series.maxs[dim]);
        let vMin = Math.min(...all);
        let vMax = Math.max(...all);
        if (vMax - vMin < 1e-9) { vMax += 1; vMin -= 1; }
        const yOf = (v) => padT + (1 - (v - vMin) / (vMax - vMin)) * plotH;
        const color = CHART_COLORS[dim % CHART_COLORS.length];
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.14;
        ctx.beginPath();
        ctx.moveTo(xOf(series.indices[0]), yOf(mins[0]));
        for (let i = 1; i < count; i++) ctx.lineTo(xOf(series.indices[i]), yOf(mins[i]));
        for (let i = count - 1; i >= 0; i--) ctx.lineTo(xOf(series.indices[i]), yOf(series.maxs[dim][i]));
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = color;
        ctx.lineWidth = large ? 1.4 : 1;
        ctx.beginPath();
        ctx.moveTo(xOf(series.indices[0]), yOf((mins[0] + series.maxs[dim][0]) / 2));
        for (let i = 1; i < count; i++) ctx.lineTo(xOf(series.indices[i]), yOf((mins[i] + series.maxs[dim][i]) / 2));
        ctx.stroke();
        if (options.legend === "bottom-right") return; // 图例统一画在右下角
        const label = labels && labels[dim] !== undefined ? labels[dim] : `d${dim}`;
        ctx.fillStyle = color;
        const labelX = padL + dim * (large ? 58 : 42);
        if (labelX < cssW - 20) {
          ctx.fillText(String(label), labelX, cssH - (large ? 8 : 4));
        }
      });
      if (cursorIndex !== null && cursorIndex !== undefined && tMax >= tMin) {
        ctx.strokeStyle = "rgba(0, 0, 0, 0.45)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xOf(cursorIndex), padT);
        ctx.lineTo(xOf(cursorIndex), padT + plotH);
        ctx.stroke();
      }
      if (options.legend === "bottom-right") {
        drawLegendBottomRight(ctx, series, labels, cssW, cssH, large);
      }
    }

    // 右下角图例：色块 + 名称，多列排列，类似 Excel 图例。
    function drawLegendBottomRight(ctx, series, labels, cssW, cssH, large) {
      const dims = series.mins.length;
      if (dims === 0) return;
      const fontPx = large ? 10 : 9;
      ctx.font = `${fontPx}px sans-serif`;
      const lineH = large ? 15 : 13;
      const swatchW = large ? 16 : 12;
      const swatchH = large ? 4 : 3;
      const gap = large ? 6 : 4;
      const padX = large ? 8 : 6;
      const padY = large ? 6 : 5;
      const rows = large ? 6 : 4;
      const cols = Math.ceil(dims / rows);
      const colW = Array(cols).fill(0);
      for (let dim = 0; dim < dims; dim++) {
        const label = labels && labels[dim] !== undefined ? labels[dim] : `d${dim}`;
        const width = ctx.measureText(String(label)).width;
        colW[Math.floor(dim / rows)] = Math.max(colW[Math.floor(dim / rows)], width);
      }
      const boxW = padX * 2 + cols * (swatchW + gap) + colW.reduce((sum, w) => sum + w, 0);
      const boxH = padY * 2 + Math.min(dims, rows) * lineH;
      const x0 = cssW - boxW - 4;
      const y0 = cssH - boxH - 4;
      ctx.fillStyle = "rgba(255, 255, 255, 0.86)";
      ctx.strokeStyle = "#ddddda";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.rect(x0, y0, boxW, boxH);
      ctx.fill();
      ctx.stroke();
      let colX = x0 + padX;
      for (let col = 0; col < cols; col++) {
        for (let row = 0; row < rows; row++) {
          const dim = col * rows + row;
          if (dim >= dims) continue;
          const label = labels && labels[dim] !== undefined ? labels[dim] : `d${dim}`;
          const y = y0 + padY + row * lineH + lineH / 2;
          ctx.fillStyle = CHART_COLORS[dim % CHART_COLORS.length];
          ctx.fillRect(colX, y - swatchH / 2, swatchW, swatchH);
          ctx.fillStyle = "#333";
          ctx.fillText(String(label), colX + swatchW + gap, y + fontPx / 3);
        }
        colX += colW[col] + swatchW + gap;
      }
    }

    function chartLabels(series, names, prefix) {
      if (!series) return [];
      return series.mins.map((_, dim) => names && names[dim] ? names[dim].replace(/\.pos$/, "") : `${prefix}${dim}`);
    }

    function chartDescriptor(kind) {
      const series = state.series ? state.series[kind] : null;
      const stateNames = state.summary && state.summary.joint_names ? state.summary.joint_names : [];
      if (kind === "action") {
        // 维数一致时复用 joint_names，图例可直接看出哪条曲线对应哪个关节。
        const actionNames = series && series.mins.length === stateNames.length ? stateNames : [];
        return { title: "Action curves", series, labels: chartLabels(series, actionNames, "a") };
      }
      return { title: "State curves", series, labels: chartLabels(series, stateNames, "s") };
    }

    function drawCharts() {
      const action = chartDescriptor("action");
      const stateSeries = chartDescriptor("state");
      drawSeriesChart(els.actionChart, action.series, action.labels, state.frame, { legend: "bottom-right" });
      drawSeriesChart(els.stateChart, stateSeries.series, stateSeries.labels, state.frame);
      drawChartModal();
    }

    function drawChartModal() {
      if (!state.chartModal || els.chartModal.classList.contains("hidden")) return;
      const descriptor = chartDescriptor(state.chartModal);
      drawSeriesChart(els.chartModalCanvas, descriptor.series, descriptor.labels, state.frame, {
        large: true,
        legend: state.chartModal === "action" ? "bottom-right" : null,
      });
    }

    async function loadSeries() {
      if (!state.fileId || !state.episodeId) return;
      try {
        state.series = await api(`/api/files/${state.fileId}/episodes/${state.episodeId}/series`);
        drawCharts();
      } catch (error) {
        state.series = null;
        drawCharts();
        setStatus(error.message, "bad");
      }
    }

    async function renderFrame() {
      const episode = currentEpisode();
      if (!episode) return;
      const maxFrame = Math.max(episode.num_samples - 1, 0);
      state.frame = Math.min(Math.max(state.frame, 0), maxFrame);
      els.frameSlider.max = String(maxFrame);
      els.frameSlider.value = String(state.frame);

      updateImage(els.imgFront, els.emptyFront, els.slotFront.value, "front");
      updateImage(els.imgWrist, els.emptyWrist, els.slotWrist.value, "wrist");
      updateImage(els.imgOverview, els.emptyOverview, els.slotOverview.value, "overview");
      drawCharts();

      if (state.playing && state.sampleLoading) {
        return;
      }
      const requestId = ++state.sampleRequestId;
      state.sampleLoading = true;
      try {
        const sample = await api(`/api/files/${state.fileId}/episodes/${state.episodeId}/sample?frame=${state.frame}`);
        if (requestId !== state.sampleRequestId) return;
        els.frameValue.textContent = `${sample.frame_index + 1} / ${sample.num_samples}`;
        els.timeValue.textContent = `${sample.timestamp.toFixed(3)} s`;
        els.actionValue.textContent = formatVector(sample.action);
        els.stateValue.textContent = formatVector(sample.state);
      } catch (error) {
        setStatus(error.message, "bad");
      } finally {
        if (requestId === state.sampleRequestId) {
          state.sampleLoading = false;
        }
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
      const maxFrame = Math.max(episode.num_samples - 1, 0);
      // 停在最后一帧时按播放则从头重播；播放到最后一帧后自动暂停。
      if (state.frame >= maxFrame) state.frame = 0;
      state.playing = true;
      els.playButton.textContent = "Pause";
      const speed = Number(els.speedSelect.value);
      const intervalMs = Math.max(33, 1000 / Math.max(state.fps * speed, 1));
      state.timer = setInterval(() => {
        if (state.frame >= maxFrame) {
          stopPlayback();
          return;
        }
        state.frame += 1;
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
      state.quality = null;
      state.series = null;
      state.imageLoading = { front: false, wrist: false, overview: false };
      state.sampleLoading = false;
      state.sampleRequestId += 1;
      els.qualityList.innerHTML = "";
      els.qualityDownload.disabled = true;
      const episodes = state.summary.episodes || [];
      state.cameras = episodes[0]?.camera_keys || state.summary.camera_keys || [];
      state.episodeId = episodes[0]?.id || null;
      fillSelect(
        els.episodeSelect,
        episodes.map((episode) => ({
          value: episode.id,
          label: `${episode.label} · ${episode.success ? "success" : "failure"} · ${episode.num_samples} frames`,
        })),
        state.episodeId || "",
      );
      configureCameraSlots();
      state.frame = 0;
      els.fpsValue.textContent = String(state.fps);
      updateEpisodeReadout();
      setStatus("Ready", "ok");
      await loadSeries();
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

    function episodeAnomalies(episodeId) {
      if (!state.quality) return null;
      const report = state.quality.episodes.find((item) => item.id === episodeId);
      return report ? report.anomalies : null;
    }

    function refreshEpisodeOptions() {
      const episodes = state.summary ? state.summary.episodes || [] : [];
      fillSelect(
        els.episodeSelect,
        episodes.map((episode) => {
          const anomalies = episodeAnomalies(episode.id);
          const warning = anomalies && anomalies.length > 0 ? "⚠ " : "";
          return {
            value: episode.id,
            label: `${warning}${episode.label} · ${episode.success ? "success" : "failure"} · ${episode.num_samples} frames`,
          };
        }),
        state.episodeId || "",
      );
    }

    function renderQuality() {
      const report = state.quality;
      if (!report) return;
      els.qualityList.innerHTML = "";
      if (!report.overview_recorded) {
        const note = document.createElement("div");
        note.className = "quality-item";
        note.innerHTML = "<span>该文件录制时没有 overview 第三视角（旧数据）；bottom 窗口显示 \"overview 未录制\"。</span>";
        els.qualityList.appendChild(note);
      }
      for (const episode of report.episodes) {
        const item = document.createElement("div");
        item.className = "quality-item";
        const head = document.createElement("div");
        head.className = "head";
        const name = document.createElement("span");
        name.textContent = episode.anomalies.length > 0 ? `⚠ ${episode.id}` : episode.id;
        const outcome = document.createElement("span");
        outcome.textContent = `${episode.success ? "success" : "failure"} · ${episode.outcome || "-"}`;
        head.appendChild(name);
        head.appendChild(outcome);
        item.appendChild(head);
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = `${episode.num_samples} frames · ${episode.duration_s.toFixed(1)} s · ` +
          `${episode.actual_fps ? episode.actual_fps.toFixed(1) + " fps" : "no timestamps"}`;
        item.appendChild(meta);
        const anomalyLine = document.createElement("div");
        anomalyLine.className = episode.anomalies.length > 0 ? "anomalies" : "clean";
        anomalyLine.textContent = episode.anomalies.length > 0
          ? episode.anomalies.join(" · ")
          : `cameras: ${episode.camera_keys.join(", ") || "none"}`;
        item.appendChild(anomalyLine);
        els.qualityList.appendChild(item);
      }
      refreshEpisodeOptions();
      els.qualityDownload.disabled = false;
      setStatus(`Quality: ${report.episodes.filter((item) => item.anomalies.length > 0).length}/${report.episodes.length} episodes with warnings`, "ok");
    }

    async function loadQuality() {
      if (!state.fileId) return;
      setStatus("Analyzing quality");
      try {
        state.quality = await api(`/api/files/${state.fileId}/quality`);
        renderQuality();
      } catch (error) {
        setStatus(error.message, "bad");
      }
    }

    async function downloadQuality() {
      if (!state.fileId) return;
      try {
        const response = await fetch(`/api/files/${state.fileId}/quality?download=1`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "quality_report.json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      } catch (error) {
        setStatus(error.message, "bad");
      }
    }

    function setupResizablePanels() {
      let active = null;

      function beginResize(event, kind) {
        if (window.innerWidth <= 980) return;
        event.preventDefault();
        const workspaceRect = els.workspace.getBoundingClientRect();
        const viewerRect = els.viewer.getBoundingClientRect();
        const topRow = document.querySelector(".top-row");
        const topRowRect = topRow.getBoundingClientRect();
        active = {
          kind,
          workspaceRect,
          viewerRect,
          topRowRect,
        };
        document.body.classList.add("resizing");
        window.addEventListener("pointermove", onResizeMove);
        window.addEventListener("pointerup", endResize, { once: true });
      }

      function onResizeMove(event) {
        if (!active) return;
        if (active.kind === "side-panel") {
          const width = clamp(active.workspaceRect.right - event.clientX - 8, 260, 640);
          state.layout.sideWidth = width;
        } else if (active.kind === "viewer-split") {
          const percent = ((event.clientY - active.viewerRect.top) / active.viewerRect.height) * 100;
          state.layout.viewerTop = clamp(percent, 24, 68);
        } else if (active.kind === "camera-split") {
          const percent = ((event.clientX - active.topRowRect.left) / active.topRowRect.width) * 100;
          state.layout.cameraLeft = clamp(percent, 24, 76);
        }
        syncLayoutVariables();
        drawCharts();
      }

      function endResize() {
        active = null;
        document.body.classList.remove("resizing");
        window.removeEventListener("pointermove", onResizeMove);
      }

      els.resizeHandles.forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => beginResize(event, handle.dataset.resize));
      });
    }

    els.fileSelect.addEventListener("change", () => loadSummary(els.fileSelect.value).catch((error) => setStatus(error.message, "bad")));
    els.uploadButton.addEventListener("click", () => els.uploadInput.click());
    els.uploadInput.addEventListener("change", () => {
      const file = els.uploadInput.files[0];
      if (!file) return;
      uploadLocalFile(file).catch((error) => setStatus(error.message, "bad"));
      els.uploadInput.value = "";
    });
    els.episodeSelect.addEventListener("change", async () => {
      stopPlayback();
      state.episodeId = els.episodeSelect.value;
      const episode = currentEpisode();
      state.cameras = episode?.camera_keys || state.summary?.camera_keys || [];
      configureCameraSlots();
      state.frame = 0;
      state.imageLoading = { front: false, wrist: false, overview: false };
      state.sampleLoading = false;
      state.sampleRequestId += 1;
      updateEpisodeReadout();
      await loadSeries();
      renderFrame();
    });
    els.qualityButton.addEventListener("click", () => loadQuality());
    els.qualityDownload.addEventListener("click", () => downloadQuality());
    els.toggleVectorButton.addEventListener("click", () => setVectorOverlayVisible(!state.showVectors));
    els.hideVectorButton.addEventListener("click", () => setVectorOverlayVisible(false));
    els.actionChart.addEventListener("click", () => openChartModal("action"));
    els.stateChart.addEventListener("click", () => openChartModal("state"));
    els.chartOpenButtons.forEach((button) => {
      button.addEventListener("click", () => openChartModal(button.dataset.chartOpen));
    });
    els.chartModalClose.addEventListener("click", closeChartModal);
    els.chartModal.addEventListener("click", (event) => {
      if (event.target === els.chartModal) closeChartModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.chartModal) {
        closeChartModal();
        return;
      }
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "BUTTON") return;
      if (event.code === "Space") {
        event.preventDefault();
        state.playing ? stopPlayback() : startPlayback();
      } else if (event.key === "ArrowLeft") {
        stopPlayback();
        state.frame -= 1;
        renderFrame();
      } else if (event.key === "ArrowRight") {
        stopPlayback();
        state.frame += 1;
        renderFrame();
      }
    });
    window.addEventListener("resize", () => drawCharts());
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

    syncLayoutVariables();
    setVectorOverlayVisible(true);
    setupResizablePanels();
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
    print(f"网页已启动 url={url}", flush=True)
    print("Press Ctrl+C to stop the viewer.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n网页已停止", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
