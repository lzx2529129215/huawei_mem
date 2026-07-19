#!/usr/bin/env python3
"""Validate baseline/VMA mapping on a stable device process without UI."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from operation_vma_mapping import load_config, load_vma_jsonl, map_operation_stage, write_stage_outputs  # noqa: E402
from process_role_resolver import enrich_process_rows, parse_proc_stat_starttime  # noqa: E402
from wps_v6_session import Device, find_hdc, list_targets, parse_collector_report_paths  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_pid(device: Device, pid: str) -> dict[str, object]:
    stat = device.shell(f"cat /proc/{pid}/stat")
    row = {
        "pid": pid,
        "ppid": stat[stat.rfind(")") + 1 :].strip().split()[1],
        "uid": "0",
        "vsz_kb": "",
        "rss_kb": "",
        "args": device.shell(f"cat /proc/{pid}/cmdline | tr '\\0' ' '", check=False),
        "cmdline": device.shell(f"cat /proc/{pid}/cmdline | tr '\\0' ' '", check=False),
        "comm": device.shell(f"cat /proc/{pid}/comm", check=False),
        "exe_path": device.shell(f"readlink /proc/{pid}/exe", check=False),
        "process_starttime": parse_proc_stat_starttime(stat),
        "starttime_available": parse_proc_stat_starttime(stat) is not None,
    }
    return enrich_process_rows([row])[0]


def collect(device: Device, binary: str, remote_root: str, local_root: Path, pid: str, kind: str) -> dict[str, object]:
    remote_md = f"{remote_root}/{kind.lower()}.md"
    remote_jsonl = f"{remote_root}/{kind.lower()}.jsonl"
    output = device.shell(
        f"'{binary}' '{pid}' -o '{remote_md}' --jsonl-output '{remote_jsonl}' --with-vma",
        timeout_s=300,
    )
    paths = parse_collector_report_paths(output)
    if len(paths["MARKDOWN"]) != 1 or len(paths["JSONL"]) != 1:
        raise RuntimeError(f"collector paths missing: {output}")
    destination = local_root / f"{kind.lower()}_reports" / "device_idle_pipeline"
    destination.mkdir(parents=True, exist_ok=True)
    local_md = destination / "report.md"
    local_jsonl = destination / "report.jsonl"
    device_md_hash = device.shell(f"sha256sum '{remote_md}' | cut -d ' ' -f 1")
    device_jsonl_hash = device.shell(f"sha256sum '{remote_jsonl}' | cut -d ' ' -f 1")
    device.recv(remote_md, local_md)
    device.recv(remote_jsonl, local_jsonl)
    return {
        "markdown": str(local_md),
        "jsonl": str(local_jsonl),
        "markdown_hash_match": device_md_hash.strip() == sha256(local_md),
        "jsonl_hash_match": device_jsonl_hash.strip() == sha256(local_jsonl),
    }


def main() -> int:
    hdc = find_hdc()
    targets = list_targets(hdc)
    if len(targets) != 1:
        print(json.dumps({"status": "BLOCKED", "targets": targets}, indent=2))
        return 2
    device = Device(hdc, targets[0])
    pid = device.shell("pidof hdcd", check=False).split()[0]
    if not pid:
        print(json.dumps({"status": "BLOCKED", "reason": "hdcd PID unavailable"}, indent=2))
        return 2
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT / "hdc_out" / f"non_ui_pipeline_smoke_{stamp}"
    remote_root = f"/data/local/tmp/mem_analyze_v6/non_ui_pipeline_smoke_{stamp}"
    binary = "/data/local/tmp/mem_analyze_v6/mem_analyze-v6"
    output.mkdir(parents=True)
    device.shell(f"mkdir -p '{remote_root}'")

    baseline_before = snapshot_pid(device, pid)
    device.shell(f"'{binary}' --clear-refs '{pid}'")
    baseline_start = time.monotonic()
    time.sleep(2)
    baseline_process = snapshot_pid(device, pid)
    baseline_window = time.monotonic() - baseline_start
    baseline = collect(device, binary, remote_root, output, pid, "BASELINE")

    device.shell(f"'{binary}' --clear-refs '{pid}'")
    operation_start = time.monotonic()
    device.shell("echo non_ui_noop")
    time.sleep(2)
    operation_process = snapshot_pid(device, pid)
    operation_window = time.monotonic() - operation_start
    operation = collect(device, binary, remote_root, output, pid, "OPERATION")

    result = map_operation_stage(
        stage="device_idle_pipeline",
        baseline_processes=[baseline_process],
        operation_processes=[operation_process],
        baseline_vmas=load_vma_jsonl([baseline["jsonl"]]),
        operation_vmas=load_vma_jsonl([operation["jsonl"]]),
        baseline_window_s=baseline_window,
        operation_window_s=operation_window,
        app_id="device.hdcd.smoke",
        config=load_config(),
    )
    write_stage_outputs(output / "vma_mapping", result)
    payload = {
        "status": "OK",
        "target": targets[0],
        "pid": pid,
        "process_instance_stable": baseline_before["process_starttime"] == operation_process["process_starttime"],
        "baseline_window_s": baseline_window,
        "operation_window_s": operation_window,
        "baseline": baseline,
        "operation": operation,
        "summary": result["summary"],
        "output": str(output),
        "semantics": "NON_UI_DEVICE_PIPELINE_SMOKE_NOT_WPS_OPERATION",
    }
    (output / "smoke_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
