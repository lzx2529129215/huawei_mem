#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
SCRIPT="$ROOT/tools/myself_kswapd/capture_lruvec_trace.sh"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

TRACEFS="$TMP/tracefs"
OUTPUT="$TMP/output"
DEBUGFS="$TMP/debugfs"
mkdir -p "$TRACEFS/per_cpu/cpu0" "$DEBUGFS/myself_kswapd"
touch "$TRACEFS/tracing_on" "$TRACEFS/trace" "$TRACEFS/stats" \
      "$TRACEFS/per_cpu/cpu0/stats"
for event in request_begin priority_round request_end lruvec_snapshot; do
    mkdir -p "$TRACEFS/events/myself_kswapd/$event"
    touch "$TRACEFS/events/myself_kswapd/$event/enable"
done
printf '0x0000\n' > "$TMP/lru_gen_enabled"
printf 'enabled=1\n' > "$DEBUGFS/myself_kswapd/observer_config"

TRACEFS="$TRACEFS" DEBUGFS="$DEBUGFS" \
MGLRU_ENABLED="$TMP/lru_gen_enabled" \
bash "$SCRIPT" "$OUTPUT" true

test -f "$OUTPUT/capture_start.txt"
test -f "$OUTPUT/capture_end.txt"
test -f "$OUTPUT/before_global_stats.txt"
test -f "$OUTPUT/before_cpu0_stats.txt"
test -f "$OUTPUT/after_global_stats.txt"
test -f "$OUTPUT/after_cpu0_stats.txt"
grep -q '^mglru_enabled=0x0000$' "$OUTPUT/observer_metadata.txt"
grep -q '^enabled=1$' "$OUTPUT/observer_metadata.txt"
