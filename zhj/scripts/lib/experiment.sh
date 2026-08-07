#!/usr/bin/env bash

start_bpf_collector() {
  local duration="$1"
  local output="$2"
  local start_file="${3:-}"
  local stop_file="${4:-}"
  BPF_PID=""
  if ! command -v bpftrace >/dev/null 2>&1; then
    return 0
  fi
  sudo -v
  local ready_file="$output/bpf.ready"
  rm -f "$ready_file"
  bash "$root_dir/scripts/run_bpf_collector.sh" "$duration" "$output" "$ready_file" "$start_file" "$stop_file" &
  BPF_PID=$!
  for _ in {1..300}; do
    [[ -e "$ready_file" ]] && return 0
    if ! kill -0 "$BPF_PID" 2>/dev/null; then
      wait "$BPF_PID" || true
      echo "bpftrace collector exited before probes became ready" >&2
      return 4
    fi
    sleep 0.1
  done
  kill -TERM "$BPF_PID" 2>/dev/null || true
  wait "$BPF_PID" || true
  echo "timed out waiting for bpftrace probe readiness" >&2
  return 4
}

wait_bpf_collector() {
  if [[ -n "${BPF_PID:-}" ]]; then
    if ! wait "$BPF_PID"; then
      echo "WARN: eBPF summary is invalid; inspect reclaim-events-summary.json" >&2
    fi
  fi
}

cancel_bpf_collector() {
  if [[ -n "${BPF_PID:-}" ]] && kill -0 "$BPF_PID" 2>/dev/null; then
    kill -TERM "$BPF_PID" 2>/dev/null || true
    wait "$BPF_PID" 2>/dev/null || true
  fi
}

require_memory_ceiling() {
  local max_gb="$1"
  local output="$2"
  local args=(--max-memory-gb "$max_gb" --output "$output/memory-pressure-baseline.json")
  if [[ "${ALLOW_UNCONSTRAINED_MEMORY:-0}" == "1" ]]; then
    args+=(--allow-unconstrained)
  fi
  python3 -m memsched_exp.pressure_guard "${args[@]}"
}

record_memory_state() {
  python3 -m memsched_exp.pressure_guard \
    --max-memory-gb 1000000 --allow-unconstrained --output "$1"
}
