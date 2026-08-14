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
  controllers="$(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true)"
  for controller in memory cpu io; do
    if [[ " $controllers " == *" $controller "* ]]; then
      echo "OK cgroup controller: $controller"
    else
      echo "FAIL missing cgroup controller: $controller" >&2
      fail=1
    fi
  done
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

if systemctl --user show-environment >/dev/null 2>&1; then
  echo "OK systemd user manager"
else
  echo "FAIL systemd user manager is unavailable" >&2
  fail=1
fi

if python3 -c 'import memsched_exp.cli, memsched_exp.protocol, memsched_exp.schema' >/dev/null 2>&1; then
  echo "OK memsched_exp package"
else
  echo "FAIL memsched_exp is not installed in the active Python environment" >&2
  fail=1
fi

if python3 -c 'import os; raise SystemExit(0 if hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED") else 1)' >/dev/null 2>&1; then
  echo "OK per-file cold-cache eviction"
else
  echo "FAIL Python lacks POSIX_FADV_DONTNEED support" >&2
  fail=1
fi

if [[ -d "${POLICY_DEBUGFS_ROOT:-/sys/kernel/debug/parp}" ]]; then
  policy_root="${POLICY_DEBUGFS_ROOT:-/sys/kernel/debug/parp}"
  for file in effective_tier_mode effective_tier_stats effective_tier_config; do
    if [[ -r "$policy_root/$file" ]]; then
      echo "OK policy state: $policy_root/$file"
    else
      echo "FAIL unreadable policy state: $policy_root/$file" >&2
      fail=1
    fi
  done
fi

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
