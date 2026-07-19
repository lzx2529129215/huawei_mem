#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/setup_hdc_env_windows.sh"
exec python3 "${ROOT}/scripts/device/run_stage_smoke.py"
