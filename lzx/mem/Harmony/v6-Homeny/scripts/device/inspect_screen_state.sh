#!/usr/bin/env bash
set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/setup_hdc_env_windows.sh"
stamp="$(date +%Y%m%d_%H%M%S)"
local_dir="${ROOT}/hdc_out/screen_state_${stamp}"
remote_png="/data/local/tmp/mem_analyze_v6/screen_state_${stamp}.png"
mkdir -p "${local_dir}"

echo "---UITEST_HELP---"
hdc shell 'uitest uiInput help' || true
echo "---POWER_HELP---"
hdc shell 'power-shell help' || true
echo "---POWER_DUMP---"
hdc shell 'hidumper -s PowerManagerService -a -h' || true
hdc shell "uitest screenCap -p '${remote_png}'" || true
hdc file recv "${remote_png}" "${local_dir}/screen.png" || true
echo "screen_state_dir=${local_dir}"
