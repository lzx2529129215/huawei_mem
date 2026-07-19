#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/setup_hdc_env_windows.sh"
stamp="$(date +%Y%m%d_%H%M%S)"
local_dir="${ROOT}/hdc_out/screen_wake_${stamp}"
remote_png="/data/local/tmp/mem_analyze_v6/screen_wake_${stamp}.png"
mkdir -p "${local_dir}"

hdc shell 'power-shell wakeup'
sleep 1
hdc shell 'uitest uiInput swipe 1560 1800 1560 350 800'
sleep 2
hdc shell "uitest screenCap -p '${remote_png}'"
hdc file recv "${remote_png}" "${local_dir}/screen.png"
echo "screen_wake_dir=${local_dir}"
