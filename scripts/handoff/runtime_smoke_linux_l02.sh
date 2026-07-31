#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
bounded=0; tracefs="${TRACEFS:-}"; output=""; trace_file=""; output_dir=""
pressure_command=()
while (($#)); do
    case "$1" in
        --help) usage_header; echo "Usage: $0 [--read-only] [--trace-file FILE] [--bounded-reclaim --output-dir DIR -- COMMAND [ARGS...]] [--tracefs DIR] [--output FILE]"; exit 0;;
        --read-only) bounded=0; shift;; --bounded-reclaim) bounded=1; shift;; --tracefs) tracefs=$2; shift 2;; --output) output=$2; shift 2;; --trace-file) trace_file=$2; shift 2;; --output-dir) output_dir=$2; shift 2;; --) shift; pressure_command=("$@"); break;; *) die "unknown argument: $1";;
    esac
done
if [[ -z "$tracefs" ]]; then [[ -d /sys/kernel/tracing ]] && tracefs=/sys/kernel/tracing || tracefs=/sys/kernel/debug/tracing; fi
if [[ -n "$output" ]]; then exec > >(tee "$output") 2>&1; fi
cleanup() { :; }; trap cleanup EXIT
printf 'kernel=%s\ntracefs=%s\n' "$(uname -r)" "$tracefs"; dmesg --level=err,warn | tail -80 || true
if [[ -r /sys/kernel/mm/lru_gen/enabled ]]; then printf 'mglru=%s\n' "$(cat /sys/kernel/mm/lru_gen/enabled)"; else echo 'mglru=unavailable'; fi
if [[ ! -d "$tracefs" || ! -d "$tracefs/events/myself_kswapd" ]]; then echo 'Runtime smoke: NOT RUN / ENVIRONMENT BLOCKED'; echo 'reason=tracefs or L0.2 trace events unavailable'; exit 0; fi
echo 'trace_events=myself_kswapd available'
if (( bounded )); then
    [[ -n "$output_dir" ]] || die "--bounded-reclaim requires --output-dir"
    ((${#pressure_command[@]})) || die "--bounded-reclaim requires a bounded pressure command after --"
    echo 'bounded reclaim requested; capture helper enables only L0.2 trace events and always disables them on exit'
    "$ROOT/tools/myself_kswapd/capture_lruvec_trace.sh" "$output_dir" "${pressure_command[@]}"
    trace_file="$output_dir/trace.txt"
fi
if [[ -n "$trace_file" ]]; then
    [[ -r "$trace_file" ]] || die "trace file is unreadable: $trace_file"
    python3 "$ROOT/tools/myself_kswapd/parse_lruvec_trace.py" "$trace_file"
    echo "parsed_trace=$trace_file"
    echo 'Runtime smoke: PASS / TRACE PARSER'
else
    echo 'read-only mode: no sysfs, cgroup, trace, or reclaim state was changed'; echo 'Runtime smoke: PASS / READ-ONLY PREFLIGHT'
fi
