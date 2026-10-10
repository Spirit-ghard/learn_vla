"""Read-only SO101 Leader teleoperation device for IsaacLab simulation."""

from __future__ import annotations

import json
import math
import os
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lwh_isaaclab_tasks.assets.so101_constants import (
    SO101_FOLLOWER_JOINT_LIMITS_DEG,
    SO101_JOINT_NAMES,
    SO101_LEADER_MOTOR_LIMITS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROJECT_LEADER_CALIBRATION = PROJECT_ROOT / "configs/so101_leader_calibration.json"
DEFAULT_LEISAAC_LEADER_CALIBRATION = (
    Path.home() / ".local/share/ov/pkg/leisaac/source/leisaac/leisaac/devices/lerobot/.cache/so101_leader.json"
)
DEFAULT_LEROBOT_CALIBRATION_ROOTS = (
    Path.home() / ".cache/huggingface/lerobot/calibration/teleoperators/so_leader",
    Path.home() / ".cache/huggingface/lerobot/calibration/teleoperators/so101_leader",
)

PRESENT_POSITION_ADDR = 56
PRESENT_POSITION_LEN = 2
TORQUE_ENABLE_ADDR = 40
LOCK_ADDR = 55
STS3215_MODEL_NUMBER = 777
STS3215_RESOLUTION = 4096
DEFAULT_BAUDRATE = 1_000_000


@dataclass(frozen=True)
class LeaderMotorCalibration:
    """LeRobot/LeIsaac SO101 leader calibration file entry."""

    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int


class SO101LeaderBus:
    """Minimal Feetech STS3215 bus wrapper used only for leader joint reading."""

    def __init__(
        self,
        port: str,
        calibration_path: Path,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        disable_torque_on_connect: bool = True,
        handshake: bool = True,
    ) -> None:
        self.port = port
        self.calibration_path = calibration_path
        self.baudrate = baudrate
        self.disable_torque_on_connect = disable_torque_on_connect
        self.handshake = handshake
        self.calibration = self._load_calibration(calibration_path)
        self._connected = False

        import scservo_sdk as scs

        self._scs = scs
        self._port_handler = scs.PortHandler(self.port)
        self._packet_handler = scs.PacketHandler(0)
        self._sync_reader = scs.GroupSyncRead(
            self._port_handler,
            self._packet_handler,
            PRESENT_POSITION_ADDR,
            PRESENT_POSITION_LEN,
        )

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def _load_calibration(path: Path) -> dict[str, LeaderMotorCalibration]:
        if not path.is_file():
            raise FileNotFoundError(
                f"SO101 leader calibration file not found: {path}. "
                "Run LeRobot/LeIsaac calibration first or pass --leader_calibration."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = set(SO101_JOINT_NAMES).difference(data)
        if missing:
            raise ValueError(f"SO101 leader calibration missing joints: {sorted(missing)}")
        return {
            name: LeaderMotorCalibration(
                id=int(entry["id"]),
                drive_mode=int(entry["drive_mode"]),
                homing_offset=int(entry["homing_offset"]),
                range_min=int(entry["range_min"]),
                range_max=int(entry["range_max"]),
            )
            for name, entry in data.items()
            if name in SO101_JOINT_NAMES
        }

    def connect(self) -> None:
        if self._connected:
            return
        if not self._port_handler.openPort():
            raise ConnectionError(f"Failed to open SO101 leader serial port: {self.port}")
        if not self._port_handler.setBaudRate(self.baudrate):
            self._port_handler.closePort()
            raise ConnectionError(f"Failed to set SO101 leader baudrate to {self.baudrate} on {self.port}")

        if self.handshake:
            self._ping_expected_motors()
        self._setup_sync_reader()
        if self.disable_torque_on_connect:
            # 只关闭 leader 本体扭矩，避免真实 leader 臂主动出力；不会向 follower 发送动作。
            self.disable_torque()
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            if self.disable_torque_on_connect:
                self.disable_torque()
        finally:
            self._sync_reader.clearParam()
            self._port_handler.closePort()
            self._connected = False

    def _ping_expected_motors(self) -> None:
        missing: list[str] = []
        wrong_model: list[str] = []
        for joint_name in SO101_JOINT_NAMES:
            motor_id = self.calibration[joint_name].id
            model, comm, error = self._packet_handler.ping(self._port_handler, motor_id)
            if comm != self._scs.COMM_SUCCESS or error != 0:
                missing.append(f"{joint_name}(id={motor_id})")
            elif model != STS3215_MODEL_NUMBER:
                wrong_model.append(f"{joint_name}(id={motor_id}, model={model})")
        if missing or wrong_model:
            parts = []
            if missing:
                parts.append("missing/unreachable: " + ", ".join(missing))
            if wrong_model:
                parts.append("unexpected model: " + ", ".join(wrong_model))
            raise ConnectionError("SO101 leader motor handshake failed: " + "; ".join(parts))

    def _setup_sync_reader(self) -> None:
        self._sync_reader.clearParam()
        self._sync_reader.start_address = PRESENT_POSITION_ADDR
        self._sync_reader.data_length = PRESENT_POSITION_LEN
        for joint_name in SO101_JOINT_NAMES:
            if not self._sync_reader.addParam(self.calibration[joint_name].id):
                raise ConnectionError(f"Failed to add SO101 leader motor to sync reader: {joint_name}")

    def disable_torque(self) -> None:
        for joint_name in SO101_JOINT_NAMES:
            motor_id = self.calibration[joint_name].id
            self._packet_handler.write1ByteTxRx(self._port_handler, motor_id, TORQUE_ENABLE_ADDR, 0)
            self._packet_handler.write1ByteTxRx(self._port_handler, motor_id, LOCK_ADDR, 0)

    def read_raw_positions(self) -> dict[str, int]:
        if not self._connected:
            raise RuntimeError("SO101 leader bus is not connected.")
        comm = self._sync_reader.txRxPacket()
        if comm != self._scs.COMM_SUCCESS:
            raise ConnectionError("SO101 leader sync read failed: " + self._packet_handler.getTxRxResult(comm))
        return {
            joint_name: int(
                self._sync_reader.getData(
                    self.calibration[joint_name].id,
                    PRESENT_POSITION_ADDR,
                    PRESENT_POSITION_LEN,
                )
            )
            for joint_name in SO101_JOINT_NAMES
        }

    def read_normalized_positions(self) -> dict[str, float]:
        raw_positions = self.read_raw_positions()
        return {name: self._normalize(name, raw_positions[name]) for name in SO101_JOINT_NAMES}

    def _normalize(self, joint_name: str, raw_position: int) -> float:
        calibration = self.calibration[joint_name]
        if calibration.range_max == calibration.range_min:
            raise ValueError(f"Invalid calibration range for {joint_name}.")
        bounded = min(calibration.range_max, max(calibration.range_min, raw_position))
        if joint_name == "gripper":
            value = ((bounded - calibration.range_min) / (calibration.range_max - calibration.range_min)) * 100.0
            return 100.0 - value if calibration.drive_mode else value

        value = (((bounded - calibration.range_min) / (calibration.range_max - calibration.range_min)) * 200.0) - 100.0
        return -value if calibration.drive_mode else value


class SO101LeaderArm:
    """SO101 Leader device that reads a real leader arm and drives only the simulated follower."""

    device_type = "so101leader"

    def __init__(
        self,
        env,
        *,
        port: str,
        calibration_path: Path,
        start_immediately: bool = False,
        disable_torque_on_connect: bool = True,
        handshake: bool = True,
    ) -> None:
        self.env = env
        self._started = start_immediately
        self._reset_state = False
        self._additional_callbacks: dict[str, Callable[[], None]] = {}
        self._latest_normalized_positions: dict[str, float] | None = None

        self.bus = SO101LeaderBus(
            port,
            calibration_path,
            disable_torque_on_connect=disable_torque_on_connect,
            handshake=handshake,
        )
        self.bus.connect()

        import carb
        import omni.appwindow

        self._carb = carb
        self._appwindow = omni.appwindow.get_default_app_window()
        self._input = carb.input.acquire_input_interface()
        self._keyboard = self._appwindow.get_keyboard()
        self._keyboard_sub = self._input.subscribe_to_keyboard_events(
            self._keyboard,
            lambda event, *args, obj=weakref.proxy(self): obj._on_keyboard_event(event, *args),
        )

    @property
    def started(self) -> bool:
        return self._started

    @property
    def reset_state(self) -> bool:
        return self._reset_state

    @property
    def latest_normalized_positions(self) -> dict[str, float] | None:
        return self._latest_normalized_positions

    def add_callback(self, key: str, func: Callable[[], None]) -> None:
        self._additional_callbacks[key.upper()] = func

    def reset(self) -> None:
        self._reset_state = False

    def advance(self):
        """持续读取 leader；B 只切换 episode 控制状态，不触发首次位置跳变。"""
        if self._reset_state:
            self._reset_state = False
            return {"reset": True, "started": self._started, self.device_type: True}

        self._latest_normalized_positions = self.bus.read_normalized_positions()
        action = {
            "reset": False,
            "started": self._started,
            self.device_type: True,
            "joint_state": self._latest_normalized_positions,
        }
        return self.env.cfg.preprocess_device_action(action, self)

    def display_controls(self) -> None:
        print(
            "\n".join(
                [
                    "Teleoperation Controls for SO101 real leader",
                    "  Leader position is synchronized to simulation immediately",
                    "  B: start a control/recording episode",
                    "  R: reset simulation and mark failure",
                    "  N: reset simulation and mark success",
                    "  Ctrl+C: quit",
                ]
            ),
            flush=True,
        )

    def disconnect(self) -> None:
        self._stop_keyboard_listener()
        self.bus.disconnect()

    def __del__(self) -> None:
        try:
            self.disconnect()
        except Exception:
            pass

    def _on_keyboard_event(self, event, *args, **kwargs) -> None:
        if event.type != self._carb.input.KeyboardEventType.KEY_PRESS:
            return
        key_name = event.input.name
        if key_name == "B":
            self._started = True
            self._reset_state = False
        elif key_name in ("R", "N"):
            self._started = False
            self._reset_state = True
            callback = self._additional_callbacks.get(key_name)
            if callback is not None:
                callback()

    def _stop_keyboard_listener(self) -> None:
        if getattr(self, "_keyboard_sub", None) is not None:
            self._input.unsubscribe_to_keyboard_events(self._keyboard, self._keyboard_sub)
            self._keyboard_sub = None


def resolve_leader_calibration_path(path: str | None, leader_id: str | None = None) -> Path:
    """Resolve calibration path without importing LeRobot or LeIsaac at runtime."""
    if path:
        return Path(path).expanduser()
    env_path = os.environ.get("LWH_SO101_LEADER_CALIBRATION")
    if env_path:
        return Path(env_path).expanduser()
    if DEFAULT_PROJECT_LEADER_CALIBRATION.is_file():
        return DEFAULT_PROJECT_LEADER_CALIBRATION
    if leader_id:
        for root in DEFAULT_LEROBOT_CALIBRATION_ROOTS:
            lerobot_path = root / f"{leader_id}.json"
            if lerobot_path.is_file():
                return lerobot_path
    if DEFAULT_LEISAAC_LEADER_CALIBRATION.is_file():
        return DEFAULT_LEISAAC_LEADER_CALIBRATION
    return DEFAULT_LEROBOT_CALIBRATION_ROOTS[0] / f"{leader_id or 'so101_leader'}.json"


def normalized_positions_to_sim_radians(normalized_positions: dict[str, float]) -> np.ndarray:
    """Map LeRobot/LeIsaac normalized SO101 leader positions to simulated follower joint radians."""
    values = []
    for joint_name in SO101_JOINT_NAMES:
        motor_min, motor_max = SO101_LEADER_MOTOR_LIMITS[joint_name]
        joint_min, joint_max = SO101_FOLLOWER_JOINT_LIMITS_DEG[joint_name]
        normalized = min(motor_max, max(motor_min, float(normalized_positions[joint_name])))
        joint_degree = ((normalized - motor_min) / (motor_max - motor_min)) * (joint_max - joint_min) + joint_min
        values.append(math.radians(joint_degree))
    return np.asarray(values, dtype=np.float32)
