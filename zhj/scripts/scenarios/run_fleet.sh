#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$root_dir/scripts/lib/experiment.sh"
object_bytes="${1:-512}"
app_count="${2:-18}"
footprint_mb="${FOOTPRINT_MB:-180}"
background_seconds="${BACKGROUND_SECONDS:-30}"
collector_duration="${MAX_COLLECTION_SECONDS:-900}"
post_launch_seconds="${POST_LAUNCH_SECONDS:-35}"
hold_seconds="${HOLD_SECONDS:-$((collector_duration + 60))}"
output="${OUTPUT_DIR:-$root_dir/results/fleet-${object_bytes}B-$(date +%Y%m%d-%H%M%S)}"
classes="$root_dir/tmp/fleet-classes"
mkdir -p "$output" "$classes"
require_memory_ceiling "${MAX_TEST_MEMORY_GB:-4}" "$output"

command -v javac >/dev/null || { echo "JDK is required for the Fleet managed-object workload" >&2; exit 3; }
javac -d "$classes" "$root_dir/workloads/fleet/ObjectWorkload.java"

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
  [[ -z "${collector_pid:-}" ]] || kill -TERM "$collector_pid" 2>/dev/null || true
  cancel_bpf_collector
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

stop_file="$output/experiment-stop.marker"
rm -f "$stop_file"
start_bpf_collector "$collector_duration" "$output" "" "$stop_file"
python3 -m memsched_exp.cli collect \
  --name "fleet-${object_bytes}B" --duration "$collector_duration" --interval 1 \
  --scenario fleet --cache-state warm --stop-file "$stop_file" --output "$output" &
collector_pid=$!

launched_count=0
for ((index=0; index<app_count; index++)); do
  java -Xms"${footprint_mb}m" -Xmx"$((footprint_mb + 128))m" -cp "$classes" ObjectWorkload \
    --object-bytes "$object_bytes" --footprint-mb "$footprint_mb" \
    --background-seconds "$background_seconds" --hold-seconds "$hold_seconds" \
    >"$output/app-$index.jsonl" 2>"$output/app-$index.stderr" &
  new_pid=$!
  pids+=("$new_pid")
  launched_count=$((index + 1))
  ready=0
  for _ in {1..100}; do
    grep -q '"event":"ready"' "$output/app-$index.jsonl" 2>/dev/null && { ready=1; break; }
    kill -0 "$new_pid" 2>/dev/null || break
    sleep 0.1
  done
  alive=0
  for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && ((alive+=1)) || true; done
  printf '{"launched":%d,"alive":%d,"new_app_ready":%d}\n' "$((index + 1))" "$alive" "$ready" | tee -a "$output/caching-capacity.jsonl"
  if [[ "$ready" != "1" || "$alive" != "$launched_count" ]]; then
    break
  fi
done
record_memory_state "$output/memory-pressure-loaded.json"
sleep "$post_launch_seconds"
alive=0
for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && ((alive+=1)) || true; done
printf '{"launched":%d,"alive":%d,"phase":"final"}\n' "$launched_count" "$alive" | tee -a "$output/caching-capacity.jsonl"
for ((index=0; index<${#pids[@]}; index++)); do
  pid="${pids[$index]}"
  rss_kib="$(awk '/^VmRSS:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
  [[ -n "$rss_kib" ]] || continue
  printf '{"app_index":%d,"pid":%d,"rss_bytes":%d}\n' "$index" "$pid" "$((rss_kib * 1024))" >>"$output/app-rss.jsonl"
done
python3 -m memsched_exp.workload_summary --type fleet --run "$output"
touch "$stop_file"
wait "$collector_pid"
wait_bpf_collector
echo "$output"
