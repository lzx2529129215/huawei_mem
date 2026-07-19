#!/usr/bin/env python3
"""Run ordered fixed-window timing, edit pilot, or stage-04 device experiments."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from wps_v6_session import HdcError, Session, parse_args as parse_session_args


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("timing", "pilot", "chunk-pilot", "stage04", "dataset"), required=True)
    parser.add_argument("--target", default="")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--fixed-window-s", type=float, default=5.0)
    parser.add_argument("--fixed-window-ok-tolerance-s", type=float, default=0.5)
    parser.add_argument("--baseline-window-count", type=int, default=2)
    parser.add_argument("--blocks-per-window", type=int, default=1)
    parser.add_argument("--edit-window-mode", choices=("block", "chunk"), default="chunk")
    parser.add_argument("--heavy-repeats", type=int, default=20)
    parser.add_argument("--test-serial", default="WPS-TEST-0001")
    parser.add_argument("--launch-wait-s", type=float, default=10.0)
    return parser.parse_args(argv)


def make_session(args: argparse.Namespace) -> Session:
    values = [
        "--out", str(args.out), "--session-id", args.out.name,
        "--fixed-window-s", str(args.fixed_window_s),
        "--fixed-window-ok-tolerance-s", str(args.fixed_window_ok_tolerance_s),
        "--baseline-window-count", str(args.baseline_window_count),
        "--blocks-per-window", str(args.blocks_per_window),
        "--heavy-repeats", str(args.heavy_repeats), "--test-serial", args.test_serial,
        "--launch-wait-s", str(args.launch_wait_s),
    ]
    if args.target:
        values.extend(["--target", args.target])
    if args.no_build:
        values.append("--no-build")
    session = Session(parse_session_args(values))
    session.args.edit_window_mode = args.edit_window_mode
    return session


def ensure_wps(session: Session) -> None:
    if not session.snapshot():
        session.start_wps()
        time.sleep(session.args.launch_wait_s)
    if not session.snapshot():
        raise HdcError("WPS automation setup did not produce a running process")


def setup_document(session: Session) -> None:
    session.force_stop_wps(); time.sleep(2)
    default_document = "/storage/media/100/local/files/Docs/Desktop/WPS.docx"
    preserved = f"/storage/media/100/local/files/Docs/Desktop/WPS_preserved_{session.session_timestamp}.docx"
    session.device.shell(
        f"if [ -f {default_document} ]; then mv {default_document} {preserved}; fi"
    )
    session.start_wps(); time.sleep(session.args.launch_wait_s)
    session.new_word()
    session.write_metadata()


def run_timing(session: Session) -> dict[str, object]:
    ensure_wps(session)
    windows = [session.run_fixed_window(
        operation_execution_id=f"{session.session_id}_timing",
        operation_id="NO_UI_TIMING_SMOKE", segment_index=index + 1,
        segment_label=f"NO_UI_{index + 1:02d}", window_kind="OPERATION",
        target_duration_s=float(session.args.fixed_window_s),
        action_metadata={"ui_action": "NONE"},
    ) for index in range(5)]
    session.write_fixed_window_quality()
    return {
        "mode": "timing", "window_count": len(windows),
        "actual_window_s": [item["actual_window_s"] for item in windows],
        "all_ok": all(
            item["window_quality"] == "OK" and item["collection_quality"] == "OK"
            and bool(item["support_eligible"]) for item in windows
        ),
    }


def run_pilot(session: Session) -> dict[str, object]:
    setup_document(session)
    windows = []
    total_blocks = 0
    selected = None
    for blocks in (5, 4, 3, 2, 1):
        start = total_blocks + 1
        window = session.run_fixed_window(
            operation_execution_id=f"{session.session_id}_pilot",
            operation_id="04_heavy_edit_scroll", segment_index=len(windows) + 1,
            segment_label=f"EDIT_BATCH_PILOT_{blocks}", window_kind="OPERATION",
            target_duration_s=float(session.args.fixed_window_s),
            action_callback=lambda start=start, blocks=blocks: session.write_pressure_blocks(start, blocks),
            action_metadata={"blocks_per_window": blocks, "pilot": True},
        )
        windows.append(window); total_blocks += blocks
        if window["window_quality"] == "OK" and window["action_quality"] == "OK":
            selected = blocks
            break
    session.args.heavy_repeats = total_blocks
    saved: dict[str, object] = {}
    save_error = ""
    try:
        saved = session.save_document()
    except HdcError as exc:
        save_error = str(exc)
    session.write_fixed_window_quality()
    payload = {
        "mode": "pilot", "tested_blocks": [item["action_count"] for item in windows],
        "selected_blocks_per_window": selected, "total_blocks_written": total_blocks,
        "window_results": [{key: item.get(key) for key in (
            "window_id", "action_count", "actual_window_s", "window_quality", "support_eligible",
            "support_exclusion_reason", "error") } for item in windows],
        "content_markers_verified": saved.get("content_markers_verified", {}),
        "content_validation_error": save_error,
        "selection_reason": "largest tested complete block count in 5.0+/-0.5 seconds" if selected else
                            "no complete logical block count fit the default fixed window",
        "success": selected is not None and not save_error,
    }
    (session.local_out / "pilot_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def run_chunk_pilot(session: Session) -> dict[str, object]:
    setup_document(session)
    chunks = session.ui_text_chunks(session.heavy_workload_block())
    windows = []
    execution_id = f"{session.session_id}_chunk_pilot"
    for chunk_index in range(1, len(chunks) + 1):
        windows.append(session.run_fixed_window(
            operation_execution_id=execution_id, operation_id="04_heavy_edit_scroll",
            segment_index=chunk_index,
            segment_label=f"EDIT_BATCH_01_CHUNK_{chunk_index:02d}", window_kind="OPERATION",
            target_duration_s=float(session.args.fixed_window_s),
            action_callback=lambda chunk_index=chunk_index: session.write_pressure_block_chunk(1, chunk_index),
            action_metadata={"microaction": "COMPLETE_SAFE_INPUT_CHUNK", "logical_block": 1},
        ))
    session.args.heavy_repeats = 1
    saved = session.save_document()
    session.write_fixed_window_quality()
    content_ok = bool(saved.get("content_markers_verified", {}).get("heavy_workload_complete"))
    success = content_ok and all(bool(item["support_eligible"]) for item in windows)
    return {
        "mode": "chunk-pilot", "success": success, "chunk_count": len(chunks),
        "window_results": [{key: item.get(key) for key in (
            "window_id", "segment_label", "action_elapsed_s", "actual_window_s", "window_quality",
            "support_eligible", "collection_quality", "error") } for item in windows],
        "content_markers_verified": saved.get("content_markers_verified", {}),
        "aggregation_semantics": "ORDERED_CHUNKS_FORM_ONE_COMPLETE_LOGICAL_BLOCK",
    }


def run_stage04(session: Session) -> dict[str, object]:
    setup_document(session)
    success = session.fixed_heavy_edit_stage(
        4, blocks_per_window=session.args.blocks_per_window, edit_window_mode=args_edit_mode(session)
    )
    session.device.shell("power-shell wakeup", check=False)
    time.sleep(1)
    session.device.shell("uitest uiInput swipe 1560 1800 1560 350 800", check=False)
    time.sleep(3)
    saved = session.save_document()
    session.close_wps(99, "close_final")
    quality = json.loads((session.vma_mapping_dir / "fixed_window_quality.json").read_text(encoding="utf-8"))
    baselines = [item for item in session.fixed_window_records if item["window_kind"] == "BASELINE"]
    operations = [item for item in session.fixed_window_records if item["window_kind"] == "OPERATION"]
    operation_eligible_ratio = (
        sum(bool(item["support_eligible"]) for item in operations) / len(operations) if operations else 0.0
    )
    hashes_ok = all(int(item.get("hash_mismatch_count", 0)) == 0 for item in session.fixed_window_records)
    content_ok = bool(saved.get("content_markers_verified", {}).get("heavy_workload_complete"))
    acceptance = (
        success and all(bool(item["support_eligible"]) for item in baselines)
        and operation_eligible_ratio >= .9 and hashes_ok and content_ok
    )
    return {
        "mode": "stage04", "success": acceptance, "stage_action_success": success,
        "blocks_per_window": session.args.blocks_per_window,
        "edit_window_mode": args_edit_mode(session),
        "heavy_repeats": session.args.heavy_repeats,
        "content_markers_verified": saved.get("content_markers_verified", {}),
        "fixed_window_quality": quality,
        "baseline_all_eligible": all(bool(item["support_eligible"]) for item in baselines),
        "operation_eligible_ratio": operation_eligible_ratio,
        "hashes_ok": hashes_ok,
    }


def args_edit_mode(session: Session) -> str:
    return str(getattr(session.args, "edit_window_mode", "chunk"))


def _write_dataset_row(
    session: Session, index: int, operation_id: str, baselines: list[dict[str, object]],
    windows: list[dict[str, object]], success: bool,
) -> None:
    session.write_operation({
        "index": index, "stage": operation_id, "label": f"fixed-window {operation_id}",
        "operation": f"support-eligible fixed-window samples for {operation_id}",
        "success": success, "started_at": baselines[0]["clear_refs_started_at"],
        "ended_at": windows[-1]["collection_ended_at"], "before": baselines[0].get("processes", []),
        "after": windows[-1].get("processes", []), "fixed_windows_enabled": True,
        "target_window_s": session.args.fixed_window_s,
        "baseline_window_count": len(baselines),
        "baseline_valid_window_count": sum(bool(item["support_eligible"]) for item in baselines),
        "operation_window_count": len(windows),
        "operation_valid_window_count": sum(bool(item["support_eligible"]) for item in windows),
        "operation_partial_window_count": sum(item["window_quality"] == "PARTIAL_WINDOW" for item in windows),
        "operation_overrun_window_count": sum(item["window_quality"] == "OVERRUN_WINDOW" for item in windows),
        "operation_severe_overrun_count": sum(item["window_quality"] == "SEVERE_OVERRUN" for item in windows),
        "window_sequence_path": str(session.vma_mapping_dir / "operation_window_sequences.json"),
        "fixed_window_mapping_status": "OK", "fixed_window_error": "",
        "report": ";".join(path for item in windows for path in item.get("markdown_reports", [])),
        "report_count": sum(len(item.get("markdown_reports", [])) for item in windows),
        "hash_mismatch_count": sum(int(item.get("hash_mismatch_count", 0)) for item in baselines + windows),
        "collection_quality": "OK", "baseline_quality": "OK", "window_quality": "OK",
        "vma_mapping_status": "OK", "error": "",
    })


def run_dataset(session: Session) -> dict[str, object]:
    setup_document(session)
    session.ui_click(session.args.editor_x, session.args.editor_y)
    target = float(session.args.fixed_window_s)
    results: dict[str, object] = {"mode": "dataset", "classes": {}}

    metadata_base = f"fwexec_meta_{session.session_timestamp[-8:]}"
    metadata_group, metadata_baselines = session.collect_fixed_baselines(
        operation_execution_id=metadata_base, operation_id="WRITE_METADATA",
        baseline_state="CURRENT_STATE_IDLE",
    )
    metadata_windows = []
    for index in range(1, 11):
        payload = f"Dataset_metadata_sample_{index:02d}_WPS_TEST_complete_safe_chunk"
        metadata_windows.append(session.run_fixed_window(
            operation_execution_id=f"{metadata_base}_{index:02d}", operation_id="WRITE_METADATA",
            segment_index=index, segment_label=f"WRITE_METADATA_{index:02d}", window_kind="OPERATION",
            target_duration_s=target,
            action_callback=lambda payload=payload, index=index:
                session.write_safe_text_chunk(payload, content_label=f"metadata_{index:02d}"),
            baseline_group_id=metadata_group,
        ))
    session.map_fixed_window_sequence(
        operation_execution_id=metadata_base, operation_id="WRITE_METADATA",
        baseline_windows=metadata_baselines, operation_windows=metadata_windows,
    )
    metadata_success = all(bool(item["support_eligible"]) for item in metadata_baselines + metadata_windows)
    _write_dataset_row(session, 3, "WRITE_METADATA", metadata_baselines, metadata_windows, metadata_success)
    results["classes"]["WRITE_METADATA"] = {
        "baseline_count": len(metadata_baselines), "window_count": len(metadata_windows),
        "eligible_count": sum(bool(item["support_eligible"]) for item in metadata_windows),
    }

    scroll_base = f"fwexec_scroll_{session.session_timestamp[-8:]}"
    scroll_group, scroll_baselines = session.collect_fixed_baselines(
        operation_execution_id=scroll_base, operation_id="SCROLL_DOCUMENT",
        baseline_state="CURRENT_STATE_IDLE",
    )
    scroll_windows = []
    for index in range(1, 21):
        direction = "DOWN" if index % 2 else "UP"
        scroll_windows.append(session.run_fixed_window(
            operation_execution_id=f"{scroll_base}_{index:02d}", operation_id="SCROLL_DOCUMENT",
            segment_index=index, segment_label=f"SCROLL_{direction}", window_kind="OPERATION",
            target_duration_s=target,
            action_callback=lambda direction=direction: session.scroll_for_window(direction, target),
            baseline_group_id=scroll_group,
        ))
    session.map_fixed_window_sequence(
        operation_execution_id=scroll_base, operation_id="SCROLL_DOCUMENT",
        baseline_windows=scroll_baselines, operation_windows=scroll_windows,
    )
    scroll_success = all(bool(item["support_eligible"]) for item in scroll_baselines + scroll_windows)
    _write_dataset_row(session, 4, "SCROLL_DOCUMENT", scroll_baselines, scroll_windows, scroll_success)
    results["classes"]["SCROLL_DOCUMENT"] = {
        "baseline_count": len(scroll_baselines), "window_count": len(scroll_windows),
        "eligible_count": sum(bool(item["support_eligible"]) for item in scroll_windows),
    }
    results["success"] = metadata_success and scroll_success
    session.force_stop_wps(); time.sleep(2)
    return results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out = args.out.expanduser().resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    session: Session | None = None
    return_code = 2
    try:
        session = make_session(args)
        session.verify_access(); session.build_and_push(); session.record_document_baseline()
        if args.mode == "timing":
            result = run_timing(session)
        elif args.mode == "pilot":
            result = run_pilot(session)
        elif args.mode == "chunk-pilot":
            result = run_chunk_pilot(session)
        elif args.mode == "dataset":
            result = run_dataset(session)
        else:
            result = run_stage04(session)
        result["created_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        result["target"] = session.device.target
        (session.local_out / "fixed_window_experiment_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return_code = 0 if bool(result.get("all_ok", result.get("success", True))) else 1
        return return_code
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        if session is not None:
            session.failures.append(str(exc))
        return return_code
    finally:
        if session is not None:
            try:
                session.write_metadata_file(return_code)
            finally:
                session.close_files()


if __name__ == "__main__":
    raise SystemExit(main())
