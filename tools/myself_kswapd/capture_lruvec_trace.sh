#!/usr/bin/env bash
set -euo pipefail

TRACEFS="${TRACEFS:-}"
DEBUGFS="${DEBUGFS:-/sys/kernel/debug}"
MGLRU_ENABLED="${MGLRU_ENABLED:-/sys/kernel/mm/lru_gen/enabled}"
OUTPUT_DIR="${1:?用法: $0 输出目录 压力命令 [参数 ...]}"
shift
PRESSURE_COMMAND=("$@")
EVENT_GROUP="myself_kswapd"
mkdir -p "$OUTPUT_DIR"
if [[ -z "$TRACEFS" ]]; then
    [[ -d /sys/kernel/tracing ]] && TRACEFS=/sys/kernel/tracing
    [[ -d "$TRACEFS" ]] || TRACEFS=/sys/kernel/debug/tracing
fi
[[ -d "$TRACEFS" && -w "$TRACEFS" ]]
[[ -d "$TRACEFS/events/$EVENT_GROUP" ]]

cleanup() {
    echo 0 > "$TRACEFS/tracing_on" || true
    for event in request_begin priority_round request_end lruvec_snapshot; do
        echo 0 > "$TRACEFS/events/$EVENT_GROUP/$event/enable" || true
    done
}
trap cleanup EXIT

save_trace_stats() {
    local prefix="$1"

    if [[ -r "$TRACEFS/stats" ]]; then
        cp "$TRACEFS/stats" "$OUTPUT_DIR/${prefix}_global_stats.txt"
    fi
    for stats_file in "$TRACEFS"/per_cpu/cpu*/stats; do
        [[ -r "$stats_file" ]] || continue
        local cpu_name
        cpu_name="${stats_file%/stats}"
        cpu_name="${cpu_name##*/}"
        cp "$stats_file" "$OUTPUT_DIR/${prefix}_${cpu_name}_stats.txt"
    done
}

date --iso-8601=seconds > "$OUTPUT_DIR/capture_start.txt"
printf 'tracefs=%s\n' "$TRACEFS" > "$OUTPUT_DIR/observer_metadata.txt"
if [[ -r "$MGLRU_ENABLED" ]]; then
    printf 'mglru_enabled=' >> "$OUTPUT_DIR/observer_metadata.txt"
    cat "$MGLRU_ENABLED" >> "$OUTPUT_DIR/observer_metadata.txt"
fi
if [[ -r "$DEBUGFS/myself_kswapd/observer_config" ]]; then
    cat "$DEBUGFS/myself_kswapd/observer_config" >> "$OUTPUT_DIR/observer_metadata.txt"
fi
save_trace_stats before
echo 0 > "$TRACEFS/tracing_on"
echo > "$TRACEFS/trace"
for event in request_begin priority_round request_end lruvec_snapshot; do
    echo 1 > "$TRACEFS/events/$EVENT_GROUP/$event/enable"
done
echo 1 > "$TRACEFS/tracing_on"
"${PRESSURE_COMMAND[@]}"
echo 0 > "$TRACEFS/tracing_on"
cp "$TRACEFS/trace" "$OUTPUT_DIR/trace.txt"
date --iso-8601=seconds > "$OUTPUT_DIR/capture_end.txt"
save_trace_stats after
