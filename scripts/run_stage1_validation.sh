#!/usr/bin/env bash
set -eo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ROOT="${LWH_CONDA_ROOT:-/home/a/anaconda3}"
ISAAC_ENV="${LWH_ISAAC_ENV:-lwh_isaac}"
ISAAC_SIM_SETUP="${PROJECT_ROOT}/dependencies/IsaacLab/_isaac_sim/setup_conda_env.sh"
DEFAULT_ASSETS_ROOT="/home/a/.local/share/ov/pkg/leisaac/assets"

source "${CONDA_ROOT}/etc/profile.d/conda.sh"
conda activate "${ISAAC_ENV}"
source "${ISAAC_SIM_SETUP}"
set -u

export LEISAAC_ASSETS_ROOT="${LEISAAC_ASSETS_ROOT:-${DEFAULT_ASSETS_ROOT}}"

# 防止 Git LFS pointer 被误当作 USD，必须使用已下载的真实资产。
robot_asset="${LEISAAC_ASSETS_ROOT}/robots/so101_follower.usd"
scene_asset="${LEISAAC_ASSETS_ROOT}/scenes/table_with_cube/scene.usd"
if [[ ! -f "${robot_asset}" || ! -f "${scene_asset}" ]]; then
    echo "LeIsaac assets are missing under ${LEISAAC_ASSETS_ROOT}." >&2
    exit 2
fi
if (( $(stat -c '%s' "${robot_asset}") < 1000000 )); then
    echo "${robot_asset} is not a downloaded SO101 USD asset." >&2
    exit 2
fi

status_file="$(mktemp)"
cleanup() {
    rm -f "${status_file}"
}
trap cleanup EXIT
export LWH_VALIDATION_STATUS_FILE="${status_file}"

# Isaac Sim 4.5 关闭 Kit 时可能覆盖 Python 异常退出码，因此同时检查进程内哨兵。
set +e
python "${PROJECT_ROOT}/scripts/validate_env.py" "$@"
python_status=$?
set -e

if (( python_status != 0 )); then
    exit "${python_status}"
fi
if [[ "$(tr -d '\r\n' < "${status_file}")" != "passed" ]]; then
    echo "Stage-1 validation did not produce a passed status." >&2
    exit 1
fi
