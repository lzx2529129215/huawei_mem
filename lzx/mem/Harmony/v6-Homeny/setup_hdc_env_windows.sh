#!/usr/bin/env bash
# Source this file from WSL before HDC commands on the Windows checkout.

_HOMENY_TOOLCHAINS="/mnt/d/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/toolchains"
export OHOS_SDK="/mnt/d/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native"
_HOMENY_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${_HOMENY_SCRIPT_DIR}/scripts/device:${_HOMENY_TOOLCHAINS}:${PATH}"

_HOMENY_PROJECT_ENV="/mnt/d/lzx/school/lzx_code/lzx华为/lzx/operation_predictor/scripts/tools/device/setup_env.sh"
# The checked-in environment file currently has CRLF line endings. Source a
# read-only normalized stream so WSL Bash sees the same script semantics.
# shellcheck source=/dev/null
source <(tr -d '\r' < "${_HOMENY_PROJECT_ENV}")

unset _HOMENY_PROJECT_ENV
unset _HOMENY_SCRIPT_DIR
