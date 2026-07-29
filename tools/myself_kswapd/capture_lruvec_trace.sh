#!/usr/bin/env bash
set -euo pipefail

TRACEFS="${TRACEFS:-}"
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

date --iso-8601=seconds > "$OUTPUT_DIR/capture_start.txt"
printf 'tracefs=%s\n' "$TRACEFS" > "$OUTPUT_DIR/observer_metadata.txt"
[[ -r /sys/kernel/mm/transparent_hugepage/enabled ]] &&
    cat /sys/kernel/mm/transparent_hugepage/enabled >> "$OUTPUT_DIR/observer_metadata.txt" || true
echo 0 > "$TRACEFS/tracing_on"
echo > "$TRACEFS/trace"
for event in request_begin priority_round request_end lruvec_snapshot; do
    echo 1 > "$TRACEFS/events/$EVENT_GROUP/$event/enable"
done
echo 1 > "$TRACEFS/tracing_on"
"${PRESSURE_COMMAND[@]}"
echo 0 > "$TRACEFS/tracing_on"
cp "$TRACEFS/trace" "$OUTPUT_DIR/trace.txt"
[[ -r "$TRACEFS/stats" ]] && cp "$TRACEFS/stats" "$OUTPUT_DIR/tracefs_stats.txt" || true
date --iso-8601=seconds > "$OUTPUT_DIR/capture_end.txt"
