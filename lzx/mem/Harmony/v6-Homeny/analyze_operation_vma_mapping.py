#!/usr/bin/env python3
"""Aggregate operation-to-VMA support across repeated WPS trials."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from operation_vma_mapping import load_config


def classify_support(active_support: float, config: Mapping[str, Any]) -> str:
    thresholds = config["support_thresholds"]
    if active_support >= float(thresholds["core"]):
        return "CORE"
    if active_support >= float(thresholds["common"]):
        return "COMMON"
    if active_support >= float(thresholds["occasional"]):
        return "OCCASIONAL"
    return "NOISE"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_number}: expected object")
        records.append(item)
    return records


def _valid_operation(row: Mapping[str, str]) -> bool:
    return (
        row.get("success") == "true"
        and row.get("baseline_status") == "ENABLED"
        and row.get("vma_mapping_status") == "OK"
        and row.get("collection_quality") == "OK"
        and row.get("process_match_quality") == "OK"
        and row.get("baseline_quality") == "OK"
        and row.get("window_quality") == "OK"
        and row.get("activity_quality") == "OK"
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _support_rows(
    *,
    records: list[dict[str, Any]],
    key_field: str,
    valid_trials_by_stage: Mapping[str, set[str]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_stage_key_trial: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    keys_by_stage: dict[str, set[str]] = defaultdict(set)
    for record in records:
        stage = str(record.get("stage", ""))
        key = str(record.get(key_field, ""))
        trial = str(record.get("trial", ""))
        if stage and key and trial:
            keys_by_stage[stage].add(key)
            by_stage_key_trial[(stage, key, trial)].append(record)

    include_weak = bool(config["support_thresholds"].get("include_weak_as_active", True))
    rows: list[dict[str, Any]] = []
    for stage in sorted(keys_by_stage):
        valid_trials = sorted(valid_trials_by_stage.get(stage, set()))
        for key in sorted(keys_by_stage[stage]):
            active_count = 0
            strong_count = 0
            excess_pages: list[float] = []
            excess_ratios: list[float] = []
            roles: Counter[str] = Counter()
            confidences: list[str] = []
            for trial in valid_trials:
                samples = by_stage_key_trial.get((stage, key, trial), [])
                levels = {str(item.get("activity_level", "INACTIVE")) for item in samples}
                active = "STRONG" in levels or (include_weak and "WEAK" in levels)
                active_count += int(active)
                strong_count += int("STRONG" in levels)
                excess_pages.append(max((float(item.get("estimated_excess_referenced_pages") or 0.0) for item in samples), default=0.0))
                excess_ratios.append(max((float(item.get("estimated_excess_rss_ratio") or 0.0) for item in samples), default=0.0))
                for item in samples:
                    roles[str(item.get("process_role", "WPS_OTHER"))] += 1
                    confidences.append(str(item.get("identity_confidence", "LOW")))
            valid_count = len(valid_trials)
            active_support = active_count / valid_count if valid_count else 0.0
            strong_support = strong_count / valid_count if valid_count else 0.0
            confidence = "LOW" if "LOW" in confidences or not confidences else "MEDIUM" if "MEDIUM" in confidences else "HIGH"
            rows.append({
                "stage": stage,
                key_field: key,
                "valid_execution_count": valid_count,
                "active_execution_count": active_count,
                "strong_execution_count": strong_count,
                "active_support": active_support,
                "strong_support": strong_support,
                "support_class": classify_support(active_support, config),
                "median_estimated_excess_pages": statistics.median(excess_pages) if excess_pages else 0.0,
                "p25_estimated_excess_pages": _percentile(excess_pages, 0.25),
                "p75_estimated_excess_pages": _percentile(excess_pages, 0.75),
                "median_estimated_excess_rss_ratio": statistics.median(excess_ratios) if excess_ratios else 0.0,
                "baseline_complete_count": valid_count,
                "process_role_distribution": dict(sorted(roles.items())),
                "identity_confidence": confidence,
            })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], key_field: str) -> None:
    fields = [
        "stage", key_field, "valid_execution_count", "active_execution_count", "strong_execution_count",
        "active_support", "strong_support", "support_class", "median_estimated_excess_pages",
        "p25_estimated_excess_pages", "p75_estimated_excess_pages", "median_estimated_excess_rss_ratio",
        "baseline_complete_count", "process_role_distribution", "identity_confidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "process_role_distribution": json.dumps(row["process_role_distribution"], ensure_ascii=False, sort_keys=True),
            })


def _analysis_markdown(payload: Mapping[str, Any]) -> str:
    readiness = payload["readiness"]
    quality = payload["quality"]
    file_rows = payload["file_support"]
    anon_rows = payload["anon_support"]
    classes = Counter(row["support_class"] for row in file_rows)
    roles: Counter[str] = Counter()
    for row in [*file_rows, *anon_rows]:
        roles.update(row.get("process_role_distribution", {}))
    by_stage_file: dict[str, Counter[str]] = defaultdict(Counter)
    by_stage_anon: dict[str, Counter[str]] = defaultdict(Counter)
    for row in file_rows:
        by_stage_file[row["stage"]][row["support_class"]] += 1
    for row in anon_rows:
        by_stage_anon[row["stage"]][row["support_class"]] += 1
    top_file = sorted(file_rows, key=lambda row: (-float(row["active_support"]), str(row["semantic_file_key"])))[:10]
    lines = [
        "# HarmonyOS WPS operation-VMA analysis",
        "",
        "## Code baseline",
        "",
        "- User-designated code baseline: `lzx/mem/Harmony/v6-Homeny`.",
        "- Zip archive/SHA256: `NOT_PROVIDED`; directory manifest is recorded in the implementation evidence.",
        f"- Generated: `{payload['generated_at']}`.",
        "",
        "## Baseline configuration",
        "",
        f"`{json.dumps(payload['baseline_config'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Stage windows",
        "",
        "Stage-specific actual monotonic windows are retained in each trial `operations.csv`; this aggregate uses only executions whose window quality is `OK`.",
        "",
        "## Baseline completeness",
        "",
        f"- Valid executions: `{quality['valid_execution_count']}`; invalid executions excluded from support denominators: `{quality['invalid_execution_count']}`.",
        "",
        "## PID and role distribution",
        "",
        f"`{dict(sorted(roles.items()))}`",
        "",
        "## New PID without baseline",
        "",
        "Counts are retained per trial in `operations.csv`; such executions are excluded rather than counted inactive.",
        "",
        "## File VMA pairing",
        "",
        f"- Semantic file mappings with calculable support: `{len(file_rows)}`.",
        "",
        "## Anonymous VMA pairing",
        "",
        f"- Anonymous auxiliary mappings with calculable support: `{len(anon_rows)}`.",
        "",
        "## Split/merge",
        "",
        "Split/merge samples use overlap-conserving allocation and retain `VMA_SPLIT_MERGE_APPROXIMATION` in per-trial evidence.",
        "",
        "## Window mismatch",
        "",
        "Mismatched/severely mismatched windows remain quality records and are excluded from valid support denominators.",
        "",
        "## Referenced before and after estimate",
        "",
        "- Referenced subtraction uses `TIME_NORMALIZED_REFERENCED_HEURISTIC`; it is not an exact page-set difference.",
        "- File granularity remains `FILE_VMA_OFFSET_INTERVAL`; no 256 KiB buckets are inferred.",
        "",
        "## Per-operation file activity",
        "",
        f"`{ {stage: dict(counter) for stage, counter in sorted(by_stage_file.items())} }`",
        "",
        "## Per-operation anonymous features",
        "",
        f"`{ {stage: dict(counter) for stage, counter in sorted(by_stage_anon.items())} }`",
        "",
        "## Shared-library top mappings",
        "",
    ]
    lines.extend(
        f"- `{row['stage']}` `{row['semantic_file_key']}`: active support `{float(row['active_support']):.3f}`."
        for row in top_file
    )
    if not top_file:
        lines.append("- No valid file mapping samples.")
    lines.extend([
        "",
        "## Current-document top mappings",
        "",
        "Current-test-document semantic keys are included in the same support CSV and remain separate from exact device/inode identity.",
        "",
        "## Semantic file support",
        "",
        f"- Rows: `{len(file_rows)}`; class distribution: `{dict(sorted(classes.items()))}`.",
        "",
        "## Anonymous auxiliary support",
        "",
        f"- Rows: `{len(anon_rows)}`; anonymous keys never include PID or virtual address.",
        "",
        "## Support class distribution",
        "",
        f"`{dict(sorted(classes.items()))}`",
        "",
        "## File mapping suitability",
        "",
        f"- `ready_for_file_vma_mapping = {str(readiness['ready_for_file_vma_mapping']).lower()}`.",
        "",
        "## Operation recognition suitability",
        "",
        "- `ready_for_operation_recognition = false`; this task does not train a classifier.",
        "",
        "## Readiness",
        "",
    ])
    for key, value in readiness.items():
        lines.append(f"- `{key} = {str(value).lower()}`")
    lines.extend(["", "## Current limitations", "", "- Anonymous VMAs are auxiliary operation features only.", "- Semantic file keys support cross-trial statistics but do not replace device/inode/file-offset identity.", "- Operation recognition and apply remain disabled.", ""])
    return "\n".join(lines)


def analyze(
    session_root: Path,
    expected_repeats: int,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    session_root = session_root.resolve()
    config = load_config(config_path)
    trials = sorted(path for path in session_root.glob("trial_*") if path.is_dir())
    valid_trials_by_stage: dict[str, set[str]] = defaultdict(set)
    operation_count = 0
    invalid_count = 0
    file_records: list[dict[str, Any]] = []
    anon_records: list[dict[str, Any]] = []
    errors: list[str] = []

    for trial in trials:
        operations_path = trial / "operations.csv"
        if operations_path.is_file():
            with operations_path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    stage = row.get("stage", "")
                    if not stage or not stage.startswith("0"):
                        continue
                    operation_count += 1
                    if _valid_operation(row):
                        valid_trials_by_stage[stage].add(trial.name)
                    else:
                        invalid_count += 1
        else:
            errors.append(f"{trial.name}: missing operations.csv")
        try:
            for item in _read_jsonl(trial / "vma_mapping" / "operation_file_vma_samples.jsonl"):
                file_records.append({"trial": trial.name, **item})
            for item in _read_jsonl(trial / "vma_mapping" / "operation_anon_vma_samples.jsonl"):
                anon_records.append({"trial": trial.name, **item})
        except (OSError, ValueError) as exc:
            errors.append(str(exc))

    file_support = _support_rows(
        records=file_records,
        key_field="semantic_file_key",
        valid_trials_by_stage=valid_trials_by_stage,
        config=config,
    )
    anon_support = _support_rows(
        records=anon_records,
        key_field="anonymous_auxiliary_key",
        valid_trials_by_stage=valid_trials_by_stage,
        config=config,
    )
    valid_count = sum(len(items) for items in valid_trials_by_stage.values())
    valid_file_records = [
        item for item in file_records
        if str(item.get("trial", "")) in valid_trials_by_stage.get(str(item.get("stage", "")), set())
    ]
    valid_anon_records = [
        item for item in anon_records
        if str(item.get("trial", "")) in valid_trials_by_stage.get(str(item.get("stage", "")), set())
    ]
    file_identity_complete = bool(valid_file_records) and all(
        item.get("file_instance_key")
        and item.get("semantic_file_key")
        and item.get("granularity") == "FILE_VMA_OFFSET_INTERVAL"
        and item.get("protection_eligible") is False
        for item in valid_file_records
    )
    anon_identity_safe = bool(valid_anon_records) and all(
        item.get("anonymous_auxiliary_key")
        and item.get("long_term_page_mapping") is False
        and item.get("protection_eligible") is False
        and item.get("prefetch_eligible") is False
        for item in valid_anon_records
    )
    readiness = {
        "ready_for_idle_baseline_collection": valid_count > 0,
        "ready_for_file_vma_mapping": valid_count > 0 and bool(file_support) and file_identity_complete,
        "ready_for_anon_aux_features": valid_count > 0 and bool(anon_support) and anon_identity_safe,
        "ready_for_operation_recognition": False,
        "ready_for_apply": False,
    }
    payload: dict[str, Any] = {
        "schema_version": "homeny.operation-vma-analysis.v1",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_root": str(session_root),
        "expected_repeats": expected_repeats,
        "observed_trials": len(trials),
        "baseline_config": config["idle_baseline"],
        "quality": {
            "operation_record_count": operation_count,
            "valid_execution_count": valid_count,
            "invalid_execution_count": invalid_count,
            "analysis_errors": errors,
        },
        "file_support": file_support,
        "anon_support": anon_support,
        "readiness": readiness,
    }

    (session_root / "operation_file_vma_mapping.json").write_text(json.dumps(file_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (session_root / "operation_anon_vma_features.json").write_text(json.dumps(anon_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(session_root / "operation_file_vma_support.csv", file_support, "semantic_file_key")
    _write_csv(session_root / "operation_anon_vma_support.csv", anon_support, "anonymous_auxiliary_key")
    (session_root / "operation_vma_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (session_root / "operation_vma_analysis.md").write_text(_analysis_markdown(payload), encoding="utf-8")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--vma-mapping-config", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.repeats < 1:
            raise ValueError("--repeats must be >= 1")
        result = analyze(args.session_root, args.repeats, args.vma_mapping_config)
        print(json.dumps({
            "session_root": result["session_root"],
            "observed_trials": result["observed_trials"],
            "quality": result["quality"],
            "readiness": result["readiness"],
        }, ensure_ascii=False, indent=2))
        return 0 if not result["quality"]["analysis_errors"] else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
