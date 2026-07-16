#!/usr/bin/env bash
set -euo pipefail

# One-command repeated WPS workload experiment:
# complete workflow N times -> collect all WPS PID reports -> build 56d
# operation vectors -> compare exact and tolerance-based stability.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_TARGET="${HDC_TARGET:-3QC0124C03000514}"

if [[ " $* " != *" --target "* && " $* " != *" --target="* ]]; then
    set -- --target "$DEFAULT_TARGET" "$@"
fi

exec python3 "$SCRIPT_DIR/run_wps_workload.py" "$@"
