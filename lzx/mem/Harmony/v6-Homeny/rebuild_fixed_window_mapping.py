#!/usr/bin/env python3
"""Rebuild derived fixed-window mappings from preserved collector reports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from operation_vma_mapping import load_config
from wps_v6_session import LEGACY_OPERATION_FIELDS, NEW_OPERATION_FIELDS, Session


DERIVED_FILES = (
    "operation_window_process_pairs.jsonl", "operation_window_vma_pairs.jsonl",
    "operation_window_file_vma_samples.jsonl", "operation_window_anon_vma_samples.jsonl",
    "operation_window_sequences.json", "fixed_window_quality.json", "fixed_window_summary.md",
)


def read_windows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rebuild(trial: Path, *, config_path: Path, content_complete: bool) -> dict[str, Any]:
    mapping_dir = trial / "vma_mapping"
    windows = read_windows(mapping_dir / "operation_window_samples.jsonl")
    existing = [name for name in DERIVED_FILES if (mapping_dir / name).exists()]
    if existing:
        raise FileExistsError(f"refusing to append existing derived files: {existing}")
    baselines = [item for item in windows if item.get("window_kind") == "BASELINE"]
    operations = [item for item in windows if item.get("window_kind") == "OPERATION"]
    if not operations:
        raise ValueError("no operation windows")
    execution_ids = {str(item.get("operation_execution_id", "")) for item in operations}
    operation_ids = {str(item.get("operation_id", "")) for item in operations}
    if len(execution_ids) != 1 or len(operation_ids) != 1:
        raise ValueError("rebuild currently requires one operation execution per trial")

    session = Session.__new__(Session)
    session.vma_mapping_dir = mapping_dir
    session.vma_mapping_config = load_config(config_path)
    session.saved_document = None
    session.fixed_window_records = windows
    session.fixed_window_sequences = []
    sequence = session.map_fixed_window_sequence(
        operation_execution_id=next(iter(execution_ids)), operation_id=next(iter(operation_ids)),
        baseline_windows=baselines, operation_windows=operations,
    )
    baseline_ok = all(bool(item.get("support_eligible")) for item in baselines)
    eligible_count = sum(bool(item.get("support_eligible")) for item in operations)
    eligible_ratio = eligible_count / len(operations)
    hash_rows = list(csv.DictReader((trial / "report_hashes.csv").open(encoding="utf-8")))
    hashes_ok = bool(hash_rows) and all(str(item.get("match", "")).lower() == "true" for item in hash_rows)
    acceptance = baseline_ok and eligible_ratio >= .9 and hashes_ok and content_complete

    fields = LEGACY_OPERATION_FIELDS + NEW_OPERATION_FIELDS
    row = {field: "" for field in fields}
    row.update({
        "session_id": next(iter(execution_ids)).rsplit("_04_heavy_edit_scroll", 1)[0],
        "index": 4, "stage": next(iter(operation_ids)), "label": "fixed-window heavy edit and scroll",
        "operation": "ordered safe input chunks form 20 complete logical blocks; separate scroll windows",
        "success": str(acceptance).lower(), "status": "success" if acceptance else "failed",
        "before_pids": json.dumps(baselines[0].get("processes", []), ensure_ascii=False) if baselines else "[]",
        "after_pids": json.dumps(operations[-1].get("processes", []), ensure_ascii=False),
        "report_count": sum(len(item.get("markdown_reports", [])) for item in operations),
        "report": ";".join(path for item in operations for path in item.get("markdown_reports", [])),
        "hash_mismatch_count": sum(str(item.get("match", "")).lower() != "true" for item in hash_rows),
        "baseline_enabled": "true", "baseline_status": "ENABLED", "baseline_state": "CURRENT_STATE_IDLE",
        "sample_semantics": "FIXED_WINDOW_BASELINE_MEDIAN_OPERATION_SEQUENCE",
        "fixed_windows_enabled": "true",
        "target_window_s": operations[0].get("target_window_s", 5.0),
        "baseline_window_count": len(baselines),
        "baseline_valid_window_count": sum(bool(item.get("support_eligible")) for item in baselines),
        "operation_window_count": len(operations), "operation_valid_window_count": eligible_count,
        "operation_partial_window_count": sum(item.get("window_quality") == "PARTIAL_WINDOW" for item in operations),
        "operation_overrun_window_count": sum(item.get("window_quality") == "OVERRUN_WINDOW" for item in operations),
        "operation_severe_overrun_count": sum(item.get("window_quality") == "SEVERE_OVERRUN" for item in operations),
        "window_sequence_path": str(mapping_dir / "operation_window_sequences.json"),
        "fixed_window_mapping_status": "OK", "fixed_window_error": "",
        "vma_mapping_status": "OK", "collection_quality": "OK" if hashes_ok else "HASH_MISMATCH",
        "baseline_quality": "OK" if baseline_ok else "NO_VALID_BASELINE_WINDOWS",
        "window_quality": "OK" if eligible_count == len(operations) else "DEGRADED",
        "error": "" if acceptance else "fixed-window acceptance gate not met",
    })
    with (trial / "operations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerow(row)
    result = {
        "schema_version": "homeny.fixed-window-rebuild.v1", "acceptance_passed": acceptance,
        "baseline_window_count": len(baselines), "baseline_all_eligible": baseline_ok,
        "operation_window_count": len(operations), "operation_eligible_count": eligible_count,
        "operation_eligible_ratio": eligible_ratio, "hash_record_count": len(hash_rows),
        "hashes_ok": hashes_ok, "content_complete": content_complete,
        "execution_aggregate_semantics": sequence["execution_aggregate"]["aggregation_semantics"],
    }
    (trial / "fixed_window_rebuild_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("vma_mapping_config.json"))
    parser.add_argument("--content-complete", action="store_true")
    args = parser.parse_args()
    result = rebuild(args.trial.resolve(), config_path=args.config.resolve(), content_complete=args.content_complete)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["acceptance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
