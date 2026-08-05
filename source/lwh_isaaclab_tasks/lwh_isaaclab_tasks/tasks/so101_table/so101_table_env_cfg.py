"""Manager-based configuration for the LWH SO101 table task."""

import isaaclab.sim as sim_utils
from isaaclab.assets import AssetBaseCfg
from isaaclab.utils import configclass
from leisaac.assets.scenes.simple import TABLE_WITH_CUBE_CFG, TABLE_WITH_CUBE_USD_PATH
from leisaac.tasks.template import (
    SingleArmObservationsCfg,
    SingleArmTaskEnvCfg,
    SingleArmTaskSceneCfg,
    SingleArmTerminationsCfg,
)
from leisaac.utils.general_assets import parse_usd_and_create_subassets


@configclass
class LwhSO101TableSceneCfg(SingleArmTaskSceneCfg):
    """SO101、桌面、方块、地面、灯光和相机的场景配置。"""

    # LeIsaac 场景 USD 提供桌面和可交互方块；机器人、灯光和两路相机由父类提供。
    scene: AssetBaseCfg = TABLE_WITH_CUBE_CFG.replace(prim_path="{ENV_REGEX_NS}/Scene")

    # 官方 table_with_cube USD 只有桌面板，没有地面，因此在全局命名空间补充地面。
    ground = AssetBaseCfg(
        prim_path="/World/GroundPlane",
        spawn=sim_utils.GroundPlaneCfg(
            size=(20.0, 20.0),
            color=(0.16, 0.18, 0.20),
        ),
    )

    def __post_init__(self) -> None:
        # 父类默认腕部相机不朝向本任务操作区；保持挂载位置并修正 ROS 相机姿态。
        self.wrist.offset.rot = (-0.704022, -0.065999, 0.646586, -0.286221)


@configclass
class LwhSO101TableEnvCfg(SingleArmTaskEnvCfg):
    """SO101 桌面任务的 ManagerBasedRLEnv 配置。"""

    scene: LwhSO101TableSceneCfg = LwhSO101TableSceneCfg(num_envs=1, env_spacing=2.0)
    observations: SingleArmObservationsCfg = SingleArmObservationsCfg()
    terminations: SingleArmTerminationsCfg = SingleArmTerminationsCfg()

    task_description: str = "Manipulate the red cube on the table."

    def __post_init__(self) -> None:
        super().__post_init__()

        self.viewer.eye = (-0.45, -1.05, 0.70)
        self.viewer.lookat = (0.35, -0.35, 0.08)

        # 沿用 LeIsaac LiftCube 已验证的机器人与桌面相对位置。
        self.scene.robot.init_state.pos = (0.35, -0.64, 0.01)

        # 将组合 USD 中的方块注册为 RigidObject，默认 reset 事件才能恢复其状态。
        parse_usd_and_create_subassets(TABLE_WITH_CUBE_USD_PATH, self)
