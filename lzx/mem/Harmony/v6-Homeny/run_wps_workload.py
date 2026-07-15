#!/usr/bin/env python3
"""Run repeated real WPS sessions and build operation-level workload vectors."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("HDC_TARGET", "3QC0124C03000514"))
    parser.add_argument("--repeats", type=int, default=3, help="每个操作随完整 WPS 工作流重复的次数")
    parser.add_argument("--heavy-repeats", type=int, default=180)
    parser.add_argument("--test-serial", default="WPS-TEST-0001")
    parser.add_argument("--launch-wait-s", type=float, default=10.0)
    parser.add_argument("--editor-x", type=int, default=1100)
    parser.add_argument("--editor-y", type=int, default=1020)
    parser.add_argument("--tolerance", type=float, default=0.05, help="稳定性判断的逐维相对范围容差")
    parser.add_argument("--out-root", type=Path, help="重复实验根目录；默认写入 hdc_out")
    parser.add_argument("--no-build", action="store_true", help="所有轮次复用已有 mem_analyze-v6-ohos")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats 必须 >= 1")
    script_dir = Path(__file__).resolve().parent
    if args.out_root:
        root = args.out_root.expanduser().resolve()
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        root = script_dir / "hdc_out" / f"wps_workload_experiment_{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    base_stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    trials: list[dict[str, object]] = []
    session_script = script_dir / "wps_v6_session.py"
    binary = script_dir / "mem_analyze-v6-ohos"

    for repeat in range(1, args.repeats + 1):
        trial_dir = root / f"trial_{repeat:02d}"
        trial_dir.mkdir(parents=True, exist_ok=True)
        session_suffix = f"{base_stamp}_workload_r{repeat:02d}"
        command = [
            sys.executable,
            str(session_script),
            "--target", args.target,
            "--out", str(trial_dir),
            "--session-id", session_suffix,
            "--heavy-repeats", str(args.heavy_repeats),
            "--test-serial", args.test_serial,
            "--launch-wait-s", str(args.launch_wait_s),
            "--editor-x", str(args.editor_x),
            "--editor-y", str(args.editor_y),
        ]
        if args.no_build or (repeat > 1 and binary.is_file()):
            command.append("--no-build")
        (trial_dir / "command.json").write_text(json.dumps(command, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[wps-workload] repeat {repeat}/{args.repeats}: {' '.join(command)}", flush=True)
        started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        result = subprocess.run(command, cwd=script_dir)
        ended = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        success = result.returncode == 0
        trials.append({
            "repeat": repeat,
            "trial_dir": str(trial_dir),
            "session_suffix": session_suffix,
            "started_at": started,
            "ended_at": ended,
            "return_code": result.returncode,
            "success": success,
        })
        print(f"[wps-workload] repeat {repeat}: {'success' if success else 'failed'} (rc={result.returncode})", flush=True)

    analyzer = script_dir / "analyze_wps_workload.py"
    analysis_command = [
        sys.executable,
        str(analyzer),
        "--session-root", str(root),
        "--repeats", str(args.repeats),
        "--tolerance", str(args.tolerance),
    ]
    print(f"[wps-workload] building operation-workload mappings", flush=True)
    analysis_result = subprocess.run(analysis_command, cwd=script_dir, text=True, capture_output=True)
    if analysis_result.stdout:
        print(analysis_result.stdout, end="", flush=True)
    if analysis_result.stderr:
        print(analysis_result.stderr, end="", file=sys.stderr, flush=True)

    metadata = {
        "schema_version": 1,
        "experiment_type": "repeated_wps_operation_workload_vector",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": args.target,
        "repeats_expected": args.repeats,
        "heavy_repeats": args.heavy_repeats,
        "test_serial": args.test_serial,
        "tolerance": args.tolerance,
        "session_root": str(root),
        "trials": trials,
        "analysis_return_code": analysis_result.returncode,
        "analysis_stdout": analysis_result.stdout,
        "analysis_stderr": analysis_result.stderr,
        "notes": [
            "每个 repeat 是一轮完整的 WPS 打开、编辑、保存、前后台、关闭、重新打开和关闭流程，因此每个操作自然得到一个独立操作级样本。",
            "同一操作内的多个 PID 报告先按 7 个逻辑段聚合，再生成 56 维向量。",
            "稳定性同时报告 exact_fixed 和 tolerance-based stable，避免把连续内存指标误判为必须逐字节不变。",
        ],
    }
    metadata_path = root / "workload_experiment_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[wps-workload] output root: {root}", flush=True)
    print(f"[wps-workload] mapping: {root / 'operation_workload_mapping.json'}", flush=True)
    print(f"[wps-workload] stability: {root / 'workload_stability.md'}", flush=True)
    if analysis_result.returncode != 0:
        return analysis_result.returncode
    return 0 if all(bool(item["success"]) for item in trials) else 1


if __name__ == "__main__":
    raise SystemExit(main())
