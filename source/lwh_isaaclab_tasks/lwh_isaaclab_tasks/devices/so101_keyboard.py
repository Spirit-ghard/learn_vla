"""Carb keyboard teleoperation for the simulated SO101 follower."""

from __future__ import annotations

import weakref
from collections.abc import Callable

import carb
import isaaclab.utils.math as math_utils
import numpy as np
import omni.appwindow
import torch


def _rotvec_to_euler(rotvec: torch.Tensor) -> torch.Tensor:
    """将旋转向量转成 IsaacLab Differential IK 需要的 XYZ Euler 增量。"""
    rotvec_norm = torch.linalg.norm(rotvec, dim=-1, keepdim=True)
    rotvec_norm_clamped = torch.clamp(rotvec_norm, min=1.0e-8)
    axis = rotvec / rotvec_norm_clamped
    default_axis = torch.tensor([1.0, 0.0, 0.0], device=rotvec.device, dtype=rotvec.dtype).view(1, 3)
    axis = torch.where(rotvec_norm > 1.0e-8, axis, default_axis.repeat(rotvec.shape[0], 1))
    delta_quat = math_utils.quat_from_angle_axis(rotvec_norm.squeeze(-1), axis)
    delta_roll, delta_pitch, delta_yaw = math_utils.euler_xyz_from_quat(delta_quat)
    return torch.stack([delta_roll, delta_pitch, delta_yaw], dim=-1).squeeze(0)


class SO101Keyboard:
    """Single-process SO101 keyboard device built on Omniverse Carb input events."""

    def __init__(self, env, sensitivity: float = 1.0) -> None:
        self.env = env
        self.device_type = "keyboard"
        self.pos_sensitivity = 0.01 * sensitivity
        self.joint_sensitivity = 0.15 * sensitivity
        self.rot_sensitivity = 0.15 * sensitivity
        self._delta_action = np.zeros(8, dtype=np.float32)
        self._active_motion_keys: set[str] = set()
        self._additional_callbacks: dict[str, Callable[[], None]] = {}
        self._started = False
        self._reset_state = False

        self._create_key_bindings()

        self.robot_asset = self.env.scene["robot"]
        body_ids, _ = self.robot_asset.find_bodies("gripper")
        self.target_frame_idx = body_ids[0]

        self._appwindow = omni.appwindow.get_default_app_window()
        self._input = carb.input.acquire_input_interface()
        self._keyboard = self._appwindow.get_keyboard()
        self._keyboard_sub = self._input.subscribe_to_keyboard_events(
            self._keyboard,
            lambda event, *args, obj=weakref.proxy(self): obj._on_keyboard_event(event, *args),
        )

    def __del__(self) -> None:
        self._stop_keyboard_listener()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def reset_state(self) -> bool:
        return self._reset_state

    def reset(self) -> None:
        """清空按键增量；B/R/N 的 episode 状态由事件回调维护。"""
        self._delta_action[:] = 0.0
        self._active_motion_keys.clear()
        self._reset_state = False

    def add_callback(self, key: str, func: Callable[[], None]) -> None:
        self._additional_callbacks[key.upper()] = func

    def advance(self):
        """返回 env.step 可直接使用的动作；B 前返回 None，R/N 返回 reset 字典。"""
        if self._reset_state:
            self._reset_state = False
            return {"reset": True, "started": self._started, self.device_type: True}
        if not self._started:
            return None

        joint_state = self._convert_delta_from_frame(self._delta_action)
        action = {"reset": False, "started": True, self.device_type: True, "joint_state": joint_state}
        return self.env.cfg.preprocess_device_action(action, self)

    def display_controls(self) -> None:
        print(
            "\n".join(
                [
                    "Teleoperation Controls for SO101 keyboard",
                    "  B: start control",
                    "  R: reset simulation and mark failure",
                    "  N: reset simulation and mark success",
                    "  W/S: forward/backward",
                    "  Q/E: up/down",
                    "  A/D: shoulder left/right",
                    "  I/K/J/L: rotate",
                    "  U/O: gripper open/close",
                    "  Ctrl+C: quit",
                ]
            ),
            flush=True,
        )

    def _on_keyboard_event(self, event, *args, **kwargs) -> None:
        if event.type == carb.input.KeyboardEventType.KEY_PRESS:
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
            elif key_name in self._input_key_mapping and key_name not in self._active_motion_keys:
                self._active_motion_keys.add(key_name)
                self._delta_action += self._action_delta_mapping[self._input_key_mapping[key_name]]
        elif event.type == carb.input.KeyboardEventType.KEY_RELEASE:
            key_name = event.input.name
            if key_name in self._input_key_mapping and key_name in self._active_motion_keys:
                self._active_motion_keys.remove(key_name)
                self._delta_action -= self._action_delta_mapping[self._input_key_mapping[key_name]]

    def _stop_keyboard_listener(self) -> None:
        if getattr(self, "_keyboard_sub", None) is not None:
            self._input.unsubscribe_to_keyboard_events(self._keyboard, self._keyboard_sub)
            self._keyboard_sub = None

    def _convert_delta_from_frame(self, delta_action: np.ndarray) -> np.ndarray:
        """把末端相机/夹爪坐标系下的增量转换到机器人根坐标系。"""
        if np.allclose(delta_action[:3], 0.0) and np.allclose(delta_action[3:6], 0.0):
            return delta_action.copy()

        is_delta_rot = not np.allclose(delta_action[3:6], 0.0)
        torch_delta_action = torch.tensor(delta_action, device=self.env.device, dtype=torch.float32)
        delta_pos_f = torch_delta_action[:3].repeat(self.env.num_envs, 1)
        delta_rot_f = torch_delta_action[3:6].repeat(self.env.num_envs, 1)
        delta_quat_f = math_utils.quat_from_euler_xyz(delta_rot_f[:, 0], delta_rot_f[:, 1], delta_rot_f[:, 2])
        delta_rotvec_f = math_utils.axis_angle_from_quat(delta_quat_f)

        frame_pos = self.robot_asset.data.root_pos_w
        frame_quat = self.robot_asset.data.body_quat_w[:, self.target_frame_idx]
        root_pos = self.robot_asset.data.root_pos_w
        root_quat = self.robot_asset.data.root_quat_w
        _, frame2root = math_utils.subtract_frame_transforms(root_pos, root_quat, frame_pos, frame_quat)
        frame2root_quat = math_utils.quat_unique(frame2root)

        delta_pos_r = math_utils.quat_apply(frame2root_quat, delta_pos_f)
        delta_rotvec_r = math_utils.quat_apply(frame2root_quat, delta_rotvec_f)
        if is_delta_rot:
            delta_rot_r = _rotvec_to_euler(delta_rotvec_r)
        else:
            delta_rot_r = torch.zeros(3, device=self.env.device)

        delta_action_r = torch.cat([delta_pos_r.squeeze(0), delta_rot_r, torch_delta_action[6:]], dim=0)
        return delta_action_r.detach().cpu().numpy()

    def _create_key_bindings(self) -> None:
        self._action_delta_mapping = {
            "forward": np.asarray([0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0]) * self.pos_sensitivity,
            "backward": np.asarray([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]) * self.pos_sensitivity,
            "left": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0]) * self.joint_sensitivity,
            "right": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]) * self.joint_sensitivity,
            "up": np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]) * self.pos_sensitivity,
            "down": np.asarray([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]) * self.pos_sensitivity,
            "rotate_up": np.asarray([0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0]) * self.rot_sensitivity,
            "rotate_down": np.asarray([0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]) * self.rot_sensitivity,
            "rotate_left": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]) * self.rot_sensitivity,
            "rotate_right": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0]) * self.rot_sensitivity,
            "gripper_open": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]) * self.joint_sensitivity,
            "gripper_close": np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0]) * self.joint_sensitivity,
        }
        self._input_key_mapping = {
            "W": "forward",
            "S": "backward",
            "A": "left",
            "D": "right",
            "Q": "up",
            "E": "down",
            "K": "rotate_up",
            "I": "rotate_down",
            "J": "rotate_left",
            "L": "rotate_right",
            "U": "gripper_open",
            "O": "gripper_close",
        }
