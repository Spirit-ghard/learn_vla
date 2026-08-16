"""Banana prop asset for the LWH SO101 table task.

香蕉 USD 来自 YCB object 011，网格本身没有作者化 physics/collision API。
本模块提供一个自定义 spawn 函数：spawn 后逐 mesh 补齐刚体、碰撞（凸包近似）
和质量属性，使香蕉可以作为带重力的 RigidObject 落在桌面上并被夹爪抓取。

网格参考信息（文件单位为 cm）：
- 长轴 x，长度约 19.7 cm；
- 宽 y，约 3.9 cm；
- 弓形高度 z，约 7.4 cm（香蕉弧度所在平面）。
"""

from __future__ import annotations

import os
from pathlib import Path

import isaaclab.sim as sim_utils
from isaaclab.assets import RigidObjectCfg
from isaaclab.sim import schemas
from isaaclab.sim.spawners.from_files import spawn_from_usd
from isaaclab.sim.utils import bind_physics_material, clone
from isaacsim.core.utils.stage import get_current_stage
from pxr import Sdf, Usd, UsdGeom, UsdPhysics


default_sim_assets_root = Path(__file__).resolve().parent
sim_assets_env = "LWH_SIM_ASSETS_ROOT"


def resolve_assets_root() -> Path:
    """优先使用显式资产目录；默认使用仓库内置资产，保证项目目录可搬迁。"""
    configured = os.environ.get(sim_assets_env)
    return Path(configured).expanduser() if configured else default_sim_assets_root


banana_usd_path = resolve_assets_root() / "props" / "011_banana.usd"

# 香蕉缩放
banana_scale = 0.7


@clone
def spawn_banana(
    prim_path: str,
    cfg: sim_utils.UsdFileCfg,
    translation: tuple[float, float, float] | None = None,
    orientation: tuple[float, float, float, float] | None = None,
) -> Usd.Prim:
    """Spawn 香蕉 USD 并补齐刚体/碰撞/质量属性。

    USD 文件只含视觉网格，没有任何 physics API；直接在 cfg 里传 rigid_props
    会失败，因此在这里显式 define schema，并对每个 mesh 开启凸包碰撞近似。
    """
    prim = spawn_from_usd(
        prim_path=prim_path,
        cfg=cfg,
        translation=translation,
        orientation=orientation,
    )
    stage = get_current_stage()
    # 香蕉是自由物体：保留重力，落到桌面后可以被夹爪拿起。
    schemas.define_rigid_body_properties(
        prim_path,
        sim_utils.RigidBodyPropertiesCfg(
            solver_position_iteration_count=16,
            solver_velocity_iteration_count=1,
            max_linear_velocity=1000.0,
            max_angular_velocity=1000.0,
            max_depenetration_velocity=5.0,
            disable_gravity=False,
        ),
        stage=stage,
    )
    schemas.define_collision_properties(
        prim_path,
        sim_utils.CollisionPropertiesCfg(collision_enabled=True),
        stage=stage,
    )
    schemas.define_mass_properties(
        prim_path,
        sim_utils.MassPropertiesCfg(mass=0.08),
        stage=stage,
    )
    # 视觉 mesh 没有 collision geometry，逐 mesh 开启凸包近似作为碰撞形状。
    # physics:approximation 通过通用 Usd 属性 API 写入，兼容当前 USD/pxr 绑定
    # 未暴露 CreateApproximationAttr 的情况。
    for child_prim in Usd.PrimRange(prim):
        if child_prim.IsA(UsdGeom.Mesh):
            collision_prim = child_prim.GetPrim()
            UsdPhysics.CollisionAPI.Apply(collision_prim)
            collision_prim.CreateAttribute("physics:approximation", Sdf.ValueTypeNames.Token, False).Set(
                "convexHull"
            )
    # 绑定略高于默认的摩擦材质，减少香蕉落桌后的滑动。
    material_path = f"{prim_path}/banana_physics_material"
    material_cfg = sim_utils.RigidBodyMaterialCfg(static_friction=0.9, dynamic_friction=0.7)
    material_cfg.func(material_path, material_cfg)
    bind_physics_material(prim_path, material_path)
    return prim


banana_cfg = RigidObjectCfg(
    prim_path="{ENV_REGEX_NS}/Banana",
    # 默认位姿
    init_state=RigidObjectCfg.InitialStateCfg(pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0)),
    spawn=sim_utils.UsdFileCfg(
        usd_path=str(banana_usd_path),
        scale=(banana_scale, banana_scale, banana_scale),
        # 物理属性由 spawn_banana 补齐
        rigid_props=None,
        collision_props=None,
        mass_props=None,
        func=spawn_banana,
    ),
)
