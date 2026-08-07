#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$root_dir/scripts/lib/experiment.sh"
level="${1:-medium}"
data_file="${DATA_FILE:-$root_dir/data/appflow-1.2GiB.bin}"
duration="${DURATION_SECONDS:-120}"
small_mb="${SMALL_APP_MB:-100}"
large_mb="${LARGE_APP_MB:-1024}"
output="${OUTPUT_DIR:-$root_dir/results/appflow-${level}-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$output"
require_memory_ceiling "${MAX_TEST_MEMORY_GB:-8}" "$output"

case "$level" in
  low) small_count=5; large_count=0 ;;
  medium) small_count=15; large_count=0 ;;
  high) small_count=15; large_count=2 ;;
  *) echo "level must be low, medium, or high" >&2; exit 2 ;;
esac

if ! python3 "$root_dir/workloads/io_cold_launch.py" verify --path "$data_file" --size-gb 1.2 >/dev/null; then
  python3 "$root_dir/workloads/io_cold_launch.py" create --path "$data_file" --size-gb 1.2
fi

workers=()
worker_logs=()
cleanup() {
  for pid in "${workers[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
  [[ -z "${collector_pid:-}" ]] || kill -TERM "$collector_pid" 2>/dev/null || true
  cancel_bpf_collector
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for ((index=0; index<small_count; index++)); do
  python3 "$root_dir/workloads/memory_worker.py" --mb "$small_mb" \
    --duration "$((duration + 60))" --label "appflow-small-$index" \
    --mode resident-idle \
    >"$output/small-$index.jsonl" &
  workers+=("$!")
  worker_logs+=("$output/small-$index.jsonl")
done
for ((index=0; index<large_count; index++)); do
  python3 "$root_dir/workloads/memory_worker.py" --mb "$large_mb" \
    --duration "$((duration + 60))" --label "appflow-large-$index" \
    --mode resident-idle \
    >"$output/large-$index.jsonl" &
  workers+=("$!")
  worker_logs+=("$output/large-$index.jsonl")
done
for ((attempt=0; attempt<600; attempt++)); do
  ready_count=0
  for log in "${worker_logs[@]}"; do
    grep -q '"event": "ready"' "$log" 2>/dev/null && ((ready_count+=1)) || true
  done
  [[ "$ready_count" == "${#worker_logs[@]}" ]] && break
  for pid in "${workers[@]}"; do
    kill -0 "$pid" 2>/dev/null || { echo "background worker exited before ready" >&2; exit 4; }
  done
  sleep 0.1
done
if [[ "$ready_count" != "${#worker_logs[@]}" ]]; then
  echo "timed out waiting for AppFlow background workers" >&2
  exit 4
fi
record_memory_state "$output/memory-pressure-loaded.json"

if [[ "${DROP_CACHES:-0}" == "1" ]]; then
  sync
  echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
fi

start_bpf_collector "$duration" "$output"

python3 -m memsched_exp.cli collect \
  --name "appflow-$level" --duration "$duration" --interval 0.5 \
  --scenario appflow --cache-state "$([[ "${DROP_CACHES:-0}" == "1" ]] && echo strict-cold || echo process-cold)" \
  --output "$output" &
collector_pid=$!

python3 "$root_dir/workloads/io_cold_launch.py" read \
  --path "$data_file" --block-kb "${BLOCK_KB:-128}" | tee "$output/cold-launch.jsonl"
wait "$collector_pid"
wait_bpf_collector
echo "$output"
