#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/setup_hdc_env_windows.sh"
exec python3 "${SCRIPT_DIR}/scripts/device/check_roles.py"
