"""SO101 follower articulation config for IsaacLab."""

from __future__ import annotations

import os
from pathlib import Path

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg

from .so101_constants import SO101_JOINT_NAMES


DEFAULT_SIM_ASSETS_ROOT = Path("/home/a/.local/share/ov/pkg/leisaac/assets")
SIM_ASSETS_ENV = "LWH_SIM_ASSETS_ROOT"
LEGACY_ASSETS_ENV = "LEISAAC_ASSETS_ROOT"


def _resolve_assets_root() -> Path:
    """优先使用项目自己的资产环境变量，兼容旧的本机资产目录。"""
    configured = os.environ.get(SIM_ASSETS_ENV) or os.environ.get(LEGACY_ASSETS_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_SIM_ASSETS_ROOT


SO101_SIM_ASSET_PATH = _resolve_assets_root() / "robots" / "so101_follower.usd"

SO101_FOLLOWER_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=str(SO101_SIM_ASSET_PATH),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(disable_gravity=False),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=True,
            solver_position_iteration_count=4,
            solver_velocity_iteration_count=4,
            fix_root_link=True,
        ),
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        pos=(2.2, -0.61, 0.89),
        rot=(0.0, 0.0, 0.0, 1.0),
        joint_pos={joint_name: 0.0 for joint_name in SO101_JOINT_NAMES},
    ),
    actuators={
        "sts3215-gripper": ImplicitActuatorCfg(
            joint_names_expr=["gripper"],
            effort_limit_sim=10,
            velocity_limit_sim=10,
            stiffness=17.8,
            damping=0.60,
        ),
        "sts3215-arm": ImplicitActuatorCfg(
            joint_names_expr=["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
            effort_limit_sim=10,
            velocity_limit_sim=10,
            stiffness=17.8,
            damping=0.60,
        ),
    },
    soft_joint_pos_limit_factor=1.0,
)
