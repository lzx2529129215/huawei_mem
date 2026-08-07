#!/usr/bin/env bash
set -euo pipefail

fail=0
tracepoints_ok=1
kernel="$(uname -r)"
if [[ "$kernel" != 6.17* ]]; then
  echo "FAIL kernel: expected Linux 6.17.x, got $kernel" >&2
  fail=1
else
  echo "OK kernel: $kernel"
fi

if [[ "$(stat -fc %T /sys/fs/cgroup)" != "cgroup2fs" ]]; then
  echo "FAIL cgroup: unified cgroup v2 is required" >&2
  fail=1
else
  echo "OK cgroup v2"
fi

for file in /proc/vmstat /proc/pressure/memory; do
  if [[ -r "$file" ]]; then
    echo "OK readable: $file"
  else
    echo "FAIL unreadable: $file" >&2
    fail=1
  fi
done

for event in \
  /sys/kernel/tracing/events/vmscan/mm_vmscan_direct_reclaim_begin/id \
  /sys/kernel/tracing/events/vmscan/mm_vmscan_direct_reclaim_end/id \
  /sys/kernel/tracing/events/vmscan/mm_vmscan_kswapd_wake/id \
  /sys/kernel/tracing/events/vmscan/mm_vmscan_kswapd_sleep/id \
  /sys/kernel/tracing/events/oom/mark_victim/id; do
  if [[ -e "$event" ]]; then
    echo "OK tracepoint: ${event%/id}"
  else
    echo "WARN missing tracepoint: ${event%/id} (vmstat fallback remains available)" >&2
    tracepoints_ok=0
  fi
done

for command in python3 systemd-run wmctrl; do
  if command -v "$command" >/dev/null 2>&1; then
    echo "OK command: $command"
  else
    echo "FAIL missing command: $command" >&2
    fail=1
  fi
done

if command -v bpftrace >/dev/null 2>&1; then
  echo "OK command: bpftrace"
  if [[ "$tracepoints_ok" != "1" ]]; then
    echo "FAIL bpftrace is installed but reclaim.bt cannot attach all required tracepoints" >&2
    fail=1
  fi
else
  echo "WARN missing command: bpftrace (exact reclaim-event collection disabled)" >&2
fi

exit "$fail"
