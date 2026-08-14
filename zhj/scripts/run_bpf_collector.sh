#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 5 ]]; then
  echo "usage: $0 DURATION_SECONDS OUTPUT_DIRECTORY [READY_FILE] [START_FILE] [STOP_FILE]" >&2
  exit 2
fi

duration="$1"
output="$2"
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ready_file="${3:-$output/bpf.ready}"
start_file="${4:-}"
stop_file="${5:-}"
effective_duration="$duration"
[[ -z "$start_file" ]] || effective_duration="$(python3 -c 'import sys; print(float(sys.argv[1]) + 5.0)' "$duration")"
mkdir -p "$output"
rm -f "$ready_file"

if ! command -v bpftrace >/dev/null 2>&1; then
  echo "bpftrace is required; vmstat/cgroup collection can still run without it" >&2
  exit 3
fi

if ! sudo -n true; then
  echo "sudo credentials are not cached; run sudo -v before starting the background collector" >&2
  exit 4
fi

sudo -n timeout --signal=INT --kill-after=5 "${effective_duration}s" \
  bpftrace "$root_dir/bpf/reclaim.bt" >"$output/reclaim-events.jsonl" 2>"$output/reclaim-bpf.stderr" &
collector_pid=$!
cleanup_collector() {
  if kill -0 "$collector_pid" 2>/dev/null; then
    sudo -n kill -INT "$collector_pid" 2>/dev/null || kill -INT "$collector_pid" 2>/dev/null || true
    wait "$collector_pid" 2>/dev/null || true
  fi
}
trap cleanup_collector EXIT INT TERM
for _ in {1..300}; do
  if grep -q '"type":"collector_start"' "$output/reclaim-events.jsonl" 2>/dev/null; then
    touch "$ready_file"
    break
  fi
  if ! kill -0 "$collector_pid" 2>/dev/null; then
    wait "$collector_pid" || status=$?
    echo "bpftrace exited before reporting collector_start" >&2
    exit "${status:-4}"
  fi
  sleep 0.1
done
if [[ ! -e "$ready_file" ]]; then
  kill -TERM "$collector_pid" 2>/dev/null || true
  wait "$collector_pid" || true
  echo "timed out waiting for bpftrace collector_start" >&2
  exit 4
fi
if [[ -n "$stop_file" ]]; then
  while kill -0 "$collector_pid" 2>/dev/null && [[ ! -e "$stop_file" ]]; do
    sleep 0.1
  done
  if kill -0 "$collector_pid" 2>/dev/null; then
    sleep "${BPF_STOP_GRACE_SECONDS:-0.5}"
    sudo -n kill -INT "$collector_pid" 2>/dev/null || kill -INT "$collector_pid" 2>/dev/null || true
  fi
fi
wait "$collector_pid" || status=$?
trap - EXIT INT TERM
status="${status:-0}"
if [[ "$status" -ne 0 && "$status" -ne 124 && "$status" -ne 130 ]]; then
  exit "$status"
fi
parser_args=(
  --input "$output/reclaim-events.jsonl"
  --stderr "$output/reclaim-bpf.stderr"
  --output "$output/reclaim-events-summary.json"
)
if [[ -n "$start_file" ]]; then
  parser_args+=(--start-file "$start_file" --duration "$duration")
fi
if [[ -n "$stop_file" ]]; then
  parser_args+=(--stop-file "$stop_file")
fi
python3 -m memsched_exp.bpf_events "${parser_args[@]}"
