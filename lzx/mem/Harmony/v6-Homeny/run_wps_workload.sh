#!/usr/bin/env bash
set -euo pipefail

# One-command repeated WPS workload experiment:
# complete workflow N times -> collect all WPS PID reports -> build 56d
# operation vectors -> compare exact and tolerance-based stability.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${HDC_TARGET:-}" && " $* " != *" --target "* && " $* " != *" --target="* ]]; then
    set -- --target "$HDC_TARGET" "$@"
fi

exec python3 "$SCRIPT_DIR/run_wps_workload.py" "$@"
