#!/usr/bin/env bash
set -euo pipefail

# lzx--------------------------- 捕获配置 ---------------------------
TRACEFS="${TRACEFS:-}"
OUTPUT_DIR="${1:?用法: $0 输出目录 压力命令 [参数 ...]}"
shift
PRESSURE_COMMAND=("$@")
EVENT_GROUP="myself_kswapd"
mkdir -p "$OUTPUT_DIR"

if [[ -z "$TRACEFS" ]]; then
    if [[ -d /sys/kernel/tracing ]]; then
        TRACEFS=/sys/kernel/tracing
    elif [[ -d /sys/kernel/debug/tracing ]]; then
        TRACEFS=/sys/kernel/debug/tracing
    fi
fi
if [[ ! -d "$TRACEFS" || ! -w "$TRACEFS" ]]; then
    echo "tracefs 不可写: $TRACEFS" >&2
    exit 1
fi
if [[ ! -d "$TRACEFS/events/$EVENT_GROUP" ]]; then
    echo "未发现 $EVENT_GROUP 事件，请确认内核已启用 CONFIG_MYSELF_KSWAPD" >&2
    exit 1
fi

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

save_trace_stats before
echo 0 > "$TRACEFS/tracing_on"
echo > "$TRACEFS/trace"
echo 16384 > "$TRACEFS/buffer_size_kb"
for event in request_begin priority_round request_end lruvec_snapshot; do
    echo 1 > "$TRACEFS/events/$EVENT_GROUP/$event/enable"
done
echo 1 > "$TRACEFS/tracing_on"
"${PRESSURE_COMMAND[@]}"
echo 0 > "$TRACEFS/tracing_on"
cp "$TRACEFS/trace" "$OUTPUT_DIR/trace.txt"
date --iso-8601=seconds > "$OUTPUT_DIR/capture_end.txt"
save_trace_stats after
# lzx--------------------------- 捕获配置结束 ---------------------------
