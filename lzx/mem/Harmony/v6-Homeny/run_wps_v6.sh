#!/usr/bin/env bash
set -euo pipefail

# Single-entry launcher for the UI workload and the mem_analyze-v6 collector.
# The Python runner builds/pushes the collector, drives WPS, collects every
# related PID, pulls and hashes reports, and writes the complete session.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${HDC_TARGET:-}" && " $* " != *" --target "* && " $* " != *" --target="* ]]; then
    set -- --target "$HDC_TARGET" "$@"
fi

exec bash "$SCRIPT_DIR/collect_wps_v6.sh" "$@"
