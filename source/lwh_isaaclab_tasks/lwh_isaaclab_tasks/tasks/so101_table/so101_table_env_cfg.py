"""Manager-based configuration for the LWH SO101 table task."""

from __future__ import annotations

from dataclasses import MISSING
import math
from typing import Any

import isaaclab.sim as sim_utils
import torch
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.envs.mdp.recorders.recorders_cfg import ActionStateRecorderManagerCfg as RecordTerm
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import FrameTransformerCfg, OffsetCfg, TiledCameraCfg
from isaaclab.utils import configclass

from lwh_isaaclab_tasks.assets import SO101_FOLLOWER_CFG, SO101_JOINT_NAMES
from lwh_isaaclab_tasks.devices.so101_leader import normalized_positions_to_sim_radians

from . import mdp

# wrist 相机位姿 以wrist为parent
wrist_camera_pos = (-0.0177, 0.0662, -0.01376)
wrist_camera_rot_xyz_deg = (-41.74, -10.242, 3.54)

# front 相机位姿(手外眼) 以base为parent
front_camera_pos = (0.0, -0.30289, 0.67961)
front_camera_rot_xyz_deg = (0.0, 0.0, 0.0)

# overview 相机位姿
overview_camera_pos = (0.13108, -0.89468, 0.64109)
overview_camera_rot_xyz_deg = (44.18174, 0.0, -12.69987)

# 相机画面宽度
camera_width = 640
# 相机画面高度
camera_height = 480
# 相机采集周期
camera_update_period = 1 / 30.0

# 机器人初始关节位置（rad）
robot_initial_joint_pos = {
    "shoulder_pan": 0.0,
    "shoulder_lift": 0.0,
    "elbow_flex": 0.0,
    "wrist_flex": 0.0,
    "wrist_roll": 0.0,
    "gripper": 0.0,
}

# 可抓取棍子初始位置
object_init_pos = (0.18, -0.34, 0.062)
# 可抓取棍子初始姿态（绕 z 顺时针 90°，棍身由沿 y 转到沿 x）
object_init_rot = (0.70710678, 0.0, 0.0, -0.70710678)
# 可抓取棍子半径（0.018 × 0.7）
object_radius = 0.0126
# 可抓取棍子长度
object_length = 0.10
# 可抓取棍子质量
object_mass = 0.035

# 放置框中心位置
placement_box_center = (0.43, -0.34)
# 放置框内部尺寸
placement_box_inner_size = (0.13, 0.12)
# 放置框边缘厚度
placement_box_wall_thickness = 0.012
# 放置框边缘高度
placement_box_wall_height = 0.028 * 3.0
# 放置框底板厚度
placement_box_pad_thickness = 0.002
# 桌面上表面高度
table_top_z = 0.04


def quat_from_euler_xyz_deg(rot_xyz_deg: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """把 UI 里的 XYZ 欧拉角转换为四元数。"""
    roll, pitch, yaw = (math.radians(value) for value in rot_xyz_deg)
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return (
        cy * cp * cr + sy * sp * sr,
        cy * cp * sr - sy * sp * cr,
        sy * cp * sr + cy * sp * cr,
        sy * cp * cr - cy * sp * sr,
    )


def rotate_vector_by_quat(
    quat: tuple[float, float, float, float],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    """用四元数旋转向量。"""
    w, x, y, z = quat
    q_vec = (x, y, z)

    def cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    first_cross = cross(q_vec, vector)
    t = tuple(2.0 * value for value in first_cross)
    second_cross = cross(q_vec, t)
    return tuple(vector[index] + w * t[index] + second_cross[index] for index in range(3))


def camera_target_from_euler_xyz_deg(
    pos: tuple[float, float, float],
    rot_xyz_deg: tuple[float, float, float],
    distance: float = 1.0,
) -> tuple[float, float, float]:
    """根据 UI 相机姿态计算主窗口注视点。"""
    forward = rotate_vector_by_quat(quat_from_euler_xyz_deg(rot_xyz_deg), (0.0, 0.0, -1.0))
    return tuple(pos[index] + distance * forward[index] for index in range(3))


def placement_box_part_cfg(
    prim_path: str,
    *,
    pos: tuple[float, float, float],
    size: tuple[float, float, float],
    color: tuple[float, float, float],
    collision_enabled: bool,
) -> AssetBaseCfg:
    """创建桌面放置框的一个静态部件。"""
    return AssetBaseCfg(
        prim_path=prim_path,
        init_state=AssetBaseCfg.InitialStateCfg(pos=pos, rot=(1.0, 0.0, 0.0, 0.0)),
        spawn=sim_utils.CuboidCfg(
            size=size,
            collision_props=sim_utils.CollisionPropertiesCfg(collision_enabled=collision_enabled),
            physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=0.9, dynamic_friction=0.7),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=color, roughness=0.65),
        ),
    )


@configclass
class LwhSO101TableSceneCfg(InteractiveSceneCfg):
    """SO101、桌面、可抓取棍子、放置框、地面、灯光和相机的场景配置。"""

    robot: ArticulationCfg = SO101_FOLLOWER_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")

    ee_frame: FrameTransformerCfg = FrameTransformerCfg(
        prim_path="{ENV_REGEX_NS}/Robot/base",
        debug_vis=False,
        target_frames=[
            FrameTransformerCfg.FrameCfg(prim_path="{ENV_REGEX_NS}/Robot/gripper", name="gripper"),
            FrameTransformerCfg.FrameCfg(
                prim_path="{ENV_REGEX_NS}/Robot/jaw",
                name="jaw",
                offset=OffsetCfg(pos=(-0.021, -0.070, 0.02)),
            ),
        ],
    )

    wrist: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/gripper/wrist_camera",
        offset=TiledCameraCfg.OffsetCfg(
            pos=wrist_camera_pos,
            rot=quat_from_euler_xyz_deg(wrist_camera_rot_xyz_deg),
            convention="opengl",
        ),
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=36.5,
            focus_distance=400.0,
            horizontal_aperture=36.83,
            clipping_range=(0.01, 50.0),
            lock_camera=True,
        ),
        width=camera_width,
        height=camera_height,
        update_period=camera_update_period,
    )

    front: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/base/front_camera",
        offset=TiledCameraCfg.OffsetCfg(
            pos=front_camera_pos,
            rot=quat_from_euler_xyz_deg(front_camera_rot_xyz_deg),
            convention="opengl",
        ),
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=28.7,
            focus_distance=400.0,
            horizontal_aperture=38.11,
            clipping_range=(0.01, 50.0),
            lock_camera=True,
        ),
        width=camera_width,
        height=camera_height,
        update_period=camera_update_period,
    )

    overview: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/overview_camera",
        offset=TiledCameraCfg.OffsetCfg(
            pos=overview_camera_pos,
            rot=quat_from_euler_xyz_deg(overview_camera_rot_xyz_deg),
            convention="opengl",
        ),
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=24.0,
            focus_distance=400.0,
            horizontal_aperture=38.11,
            clipping_range=(0.01, 50.0),
            lock_camera=True,
        ),
        width=camera_width,
        height=camera_height,
        update_period=camera_update_period,
    )

    ground = AssetBaseCfg(
        prim_path="/World/GroundPlane",
        spawn=sim_utils.GroundPlaneCfg(
            size=(20.0, 20.0),
            color=(0.16, 0.18, 0.20),
        ),
    )

    table = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Table",
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.35, -0.34, 0.02), rot=(1.0, 0.0, 0.0, 0.0)),
        spawn=sim_utils.CuboidCfg(
            size=(0.62, 0.48, 0.04),
            collision_props=sim_utils.CollisionPropertiesCfg(collision_enabled=True),
            physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=0.8, dynamic_friction=0.6),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.46, 0.42, 0.36), roughness=0.75),
        ),
    )

    # scene key 沿用 banana，兼容已有录制/回放脚本。
    banana: RigidObjectCfg = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/Banana",
        init_state=RigidObjectCfg.InitialStateCfg(pos=object_init_pos, rot=object_init_rot),
        spawn=sim_utils.CapsuleCfg(
            radius=object_radius,
            height=object_length,
            axis="Y",
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                solver_position_iteration_count=16,
                solver_velocity_iteration_count=1,
                max_linear_velocity=1000.0,
                max_angular_velocity=1000.0,
                max_depenetration_velocity=3.0,
                disable_gravity=False,
            ),
            mass_props=sim_utils.MassPropertiesCfg(mass=object_mass),
            collision_props=sim_utils.CollisionPropertiesCfg(collision_enabled=True),
            physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=1.0, dynamic_friction=0.8),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.95, 0.78, 0.12), roughness=0.65),
        ),
    )

    # 放置框是低矮静态托盘，作为任务目标区域；不进入训练观测的 state/action。
    placement_box_pad = placement_box_part_cfg(
        "{ENV_REGEX_NS}/PlacementBoxPad",
        pos=(
            placement_box_center[0],
            placement_box_center[1],
            table_top_z + placement_box_pad_thickness * 0.5,
        ),
        size=(
            placement_box_inner_size[0],
            placement_box_inner_size[1],
            placement_box_pad_thickness,
        ),
        color=(0.10, 0.36, 0.62),
        collision_enabled=False,
    )
    placement_box_left_wall = placement_box_part_cfg(
        "{ENV_REGEX_NS}/PlacementBoxLeftWall",
        pos=(
            placement_box_center[0] - placement_box_inner_size[0] * 0.5 - placement_box_wall_thickness * 0.5,
            placement_box_center[1],
            table_top_z + placement_box_wall_height * 0.5,
        ),
        size=(
            placement_box_wall_thickness,
            placement_box_inner_size[1] + 2.0 * placement_box_wall_thickness,
            placement_box_wall_height,
        ),
        color=(0.07, 0.24, 0.42),
        collision_enabled=True,
    )
    placement_box_right_wall = placement_box_part_cfg(
        "{ENV_REGEX_NS}/PlacementBoxRightWall",
        pos=(
            placement_box_center[0] + placement_box_inner_size[0] * 0.5 + placement_box_wall_thickness * 0.5,
            placement_box_center[1],
            table_top_z + placement_box_wall_height * 0.5,
        ),
        size=(
            placement_box_wall_thickness,
            placement_box_inner_size[1] + 2.0 * placement_box_wall_thickness,
            placement_box_wall_height,
        ),
        color=(0.07, 0.24, 0.42),
        collision_enabled=True,
    )
    placement_box_front_wall = placement_box_part_cfg(
        "{ENV_REGEX_NS}/PlacementBoxFrontWall",
        pos=(
            placement_box_center[0],
            placement_box_center[1] - placement_box_inner_size[1] * 0.5 - placement_box_wall_thickness * 0.5,
            table_top_z + placement_box_wall_height * 0.5,
        ),
        size=(placement_box_inner_size[0], placement_box_wall_thickness, placement_box_wall_height),
        color=(0.07, 0.24, 0.42),
        collision_enabled=True,
    )
    placement_box_back_wall = placement_box_part_cfg(
        "{ENV_REGEX_NS}/PlacementBoxBackWall",
        pos=(
            placement_box_center[0],
            placement_box_center[1] + placement_box_inner_size[1] * 0.5 + placement_box_wall_thickness * 0.5,
            table_top_z + placement_box_wall_height * 0.5,
        ),
        size=(placement_box_inner_size[0], placement_box_wall_thickness, placement_box_wall_height),
        color=(0.07, 0.24, 0.42),
        collision_enabled=True,
    )

    light = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Light",
        spawn=sim_utils.DomeLightCfg(color=(0.75, 0.75, 0.75), intensity=1000.0),
    )


@configclass
class LwhSO101ActionsCfg:
    """SO101 动作项配置，运行入口会按遥操作设备填充。"""

    arm_action: mdp.ActionTermCfg = MISSING
    gripper_action: mdp.ActionTermCfg = MISSING


@configclass
class LwhSO101EventCfg:
    """默认 reset 行为：恢复场景并随机化可抓取物体位置。"""

    reset_all = EventTerm(func=mdp.reset_scene_to_default, mode="reset", params={"reset_joint_targets": True})
    randomize_object_xy = EventTerm(
        func=mdp.reset_root_state_uniform,
        mode="reset",
        params={
            # 只扰动桌面上的 XY 初始位置，幅度保持很小，避免目标漂出可抓区域或撞到放置框。
            "pose_range": {"x": (-0.03, 0.03), "y": (-0.03, 0.03)},
            "velocity_range": {},
            "asset_cfg": SceneEntityCfg("banana"),
        },
    )


@configclass
class LwhSO101ObservationsCfg:
    """Policy 观测契约：关节状态、相机图像、末端状态和上一帧动作。"""

    @configclass
    class PolicyCfg(ObsGroup):
        joint_pos = ObsTerm(func=mdp.joint_pos)
        joint_vel = ObsTerm(func=mdp.joint_vel)
        joint_pos_rel = ObsTerm(func=mdp.joint_pos_rel)
        joint_vel_rel = ObsTerm(func=mdp.joint_vel_rel)
        actions = ObsTerm(func=mdp.last_action)
        wrist = ObsTerm(
            func=mdp.image,
            params={"sensor_cfg": SceneEntityCfg("wrist"), "data_type": "rgb", "normalize": False},
        )
        front = ObsTerm(
            func=mdp.image,
            params={"sensor_cfg": SceneEntityCfg("front"), "data_type": "rgb", "normalize": False},
        )
        overview = ObsTerm(
            func=mdp.image,
            params={"sensor_cfg": SceneEntityCfg("overview"), "data_type": "rgb", "normalize": False},
        )
        ee_frame_state = ObsTerm(
            func=mdp.ee_frame_state,
            params={"ee_frame_cfg": SceneEntityCfg("ee_frame"), "robot_cfg": SceneEntityCfg("robot")},
        )
        joint_pos_target = ObsTerm(func=mdp.joint_pos_target, params={"asset_cfg": SceneEntityCfg("robot")})

        def __post_init__(self) -> None:
            self.enable_corruption = False
            self.concatenate_terms = False

    policy: PolicyCfg = PolicyCfg()


@configclass
class LwhSO101RewardsCfg:
    """阶段一/二暂不训练 RL 奖励。"""


@configclass
class LwhSO101TerminationsCfg:
    """默认只保留超时终止；遥操作入口会关闭自动超时。"""

    time_out = DoneTerm(func=mdp.time_out, time_out=True)


@configclass
class LwhSO101TableEnvCfg(ManagerBasedRLEnvCfg):
    """SO101 桌面任务的 ManagerBasedRLEnv 配置。"""

    scene: LwhSO101TableSceneCfg = LwhSO101TableSceneCfg(num_envs=1, env_spacing=8.0)
    observations: LwhSO101ObservationsCfg = LwhSO101ObservationsCfg()
    actions: LwhSO101ActionsCfg = LwhSO101ActionsCfg()
    events: LwhSO101EventCfg = LwhSO101EventCfg()
    rewards: LwhSO101RewardsCfg = LwhSO101RewardsCfg()
    terminations: LwhSO101TerminationsCfg = LwhSO101TerminationsCfg()
    recorders: RecordTerm = RecordTerm()

    dynamic_reset_gripper_effort_limit: bool = False
    robot_name: str = "so101_follower"
    default_feature_joint_names: list[str] = MISSING
    object_xy_randomization_m: float = 0.03
    task_description: str = "Move the rod into the placement tray."

    def __post_init__(self) -> None:
        super().__post_init__()

        self.decimation = 1
        self.episode_length_s = 25.0
        self.viewer.origin_type = "env"
        self.viewer.env_index = 0
        self.viewer.eye = overview_camera_pos
        self.viewer.lookat = camera_target_from_euler_xyz_deg(overview_camera_pos, overview_camera_rot_xyz_deg)

        self.sim.dt = 1 / 60.0
        self.sim.render_interval = 1
        self.sim.physx.bounce_threshold_velocity = 0.01
        self.sim.physx.friction_correlation_distance = 0.00625
        self.sim.render.enable_translucency = True

        self.scene.ee_frame.visualizer_cfg.markers["frame"].scale = (0.05, 0.05, 0.05)

        # 机器人、桌面、可抓取物体和放置框的位置在同一个任务配置内显式定义。
        self.scene.robot.init_state.pos = (0.35, -0.55, 0.01)
        self.scene.robot.init_state.joint_pos = robot_initial_joint_pos
        self.default_feature_joint_names = [f"{joint_name}.pos" for joint_name in SO101_JOINT_NAMES]

    def use_teleop_device(self, teleop_device: str) -> None:
        """按设备填充动作空间；键盘走 IK，真实 SO101 Leader 走关节位置。"""
        if teleop_device not in ("keyboard", "so101leader"):
            raise ValueError(f"Unsupported teleop device for this task: {teleop_device}")
        self.task_type = teleop_device
        if teleop_device == "so101leader":
            self.actions.arm_action = mdp.JointPositionActionCfg(
                asset_name="robot",
                joint_names=["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
                scale=1.0,
                use_default_offset=False,
            )
            self.actions.gripper_action = mdp.JointPositionActionCfg(
                asset_name="robot",
                joint_names=["gripper"],
                scale=1.0,
                use_default_offset=False,
            )
            self.scene.robot.spawn.rigid_props.disable_gravity = True
            return

        self.actions.arm_action = mdp.DifferentialInverseKinematicsActionCfg(
            asset_name="robot",
            joint_names=["shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
            body_name="gripper",
            controller=mdp.DifferentialIKControllerCfg(
                command_type="pose",
                ik_method="dls",
                use_relative_mode=True,
            ),
        )
        self.actions.gripper_action = mdp.RelativeJointPositionActionCfg(
            asset_name="robot",
            joint_names=["shoulder_pan", "gripper"],
            scale=1.0,
        )
        # 键盘 IK 模式下固定 SO101 底座并关闭机器人本体重力，减少仿真抖动。
        self.scene.robot.spawn.rigid_props.disable_gravity = True

    def preprocess_device_action(self, action: dict[str, Any], teleop_device) -> torch.Tensor:
        """将遥操作设备动作整理成 IsaacLab action tensor。"""
        if action.get("so101leader") is not None:
            joint_state = normalized_positions_to_sim_radians(action["joint_state"])
            return torch.as_tensor(joint_state, device=teleop_device.env.device, dtype=torch.float32).repeat(
                teleop_device.env.num_envs,
                1,
            )
        if action.get("keyboard") is None:
            raise NotImplementedError(f"Unsupported device action: {teleop_device.device_type}")
        joint_state = torch.as_tensor(action["joint_state"], device=teleop_device.env.device, dtype=torch.float32)
        if joint_state.ndim == 1:
            processed_action = torch.zeros(
                teleop_device.env.num_envs,
                8,
                device=teleop_device.env.device,
                dtype=torch.float32,
            )
            processed_action[:, :] = joint_state
            return processed_action
        return joint_state
