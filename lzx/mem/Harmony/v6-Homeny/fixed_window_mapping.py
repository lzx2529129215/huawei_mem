#!/usr/bin/env python3
"""Pure fixed-window quality, VMA mapping, support, and similarity helpers."""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from operation_vma_mapping import classify_activity, map_operation_stage


PRIMARY_ESTIMATION_METHOD = "FIXED_WINDOW_BASELINE_MEDIAN"
COMPATIBILITY_ESTIMATION_METHOD = "TIME_NORMALIZED_REFERENCED_HEURISTIC"


def fixed_window_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the validated fixed-window section with backward-compatible defaults."""
    defaults = {
        "enabled": True,
        "target_window_s": 5.0,
        "ok_tolerance_s": 0.5,
        "minor_tolerance_s": 1.0,
        "baseline_window_count": 2,
        "use_baseline_median": True,
        "exclude_partial_windows_from_support": True,
        "exclude_overrun_windows_from_support": True,
        "max_action_overrun_s": 1.0,
        "collect_after_each_window": True,
    }
    result = {**defaults, **dict(config.get("fixed_windows", {}))}
    if float(result["target_window_s"]) <= 0:
        raise ValueError("fixed_windows.target_window_s must be > 0")
    if float(result["ok_tolerance_s"]) < 0:
        raise ValueError("fixed_windows.ok_tolerance_s must be >= 0")
    if float(result["minor_tolerance_s"]) < float(result["ok_tolerance_s"]):
        raise ValueError("fixed_windows.minor_tolerance_s must be >= ok_tolerance_s")
    if int(result["baseline_window_count"]) < 1:
        raise ValueError("fixed_windows.baseline_window_count must be >= 1")
    return result


def classify_fixed_window(actual_window_s: float, config: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one clear_refs-complete to collection-start observation window."""
    cfg = fixed_window_config(config)
    target = float(cfg["target_window_s"])
    actual = float(actual_window_s)
    error = actual - target
    absolute_error = abs(error)
    ok = float(cfg["ok_tolerance_s"])
    minor = float(cfg["minor_tolerance_s"])
    severe_boundary = max(minor, float(cfg["max_action_overrun_s"]))
    partial = error < -minor
    severe = error > severe_boundary
    overrun = error > minor
    if partial:
        quality = "PARTIAL_WINDOW"
    elif severe:
        quality = "SEVERE_OVERRUN"
    elif overrun:
        quality = "OVERRUN_WINDOW"
    elif absolute_error <= ok:
        quality = "OK"
    else:
        quality = "MINOR_MISMATCH"

    excluded = (
        partial and bool(cfg["exclude_partial_windows_from_support"])
    ) or (
        (overrun or severe) and bool(cfg["exclude_overrun_windows_from_support"])
    )
    reason = ""
    if excluded:
        reason = quality
    return {
        "target_window_s": target,
        "actual_window_s": actual,
        "duration_error_s": error,
        "partial_window": partial,
        "overrun_window": overrun or severe,
        "window_quality": quality,
        "support_eligible": not excluded,
        "support_exclusion_reason": reason,
    }


def normalize_segment_label(label: str) -> str:
    value = str(label)
    if re.fullmatch(r"EDIT_BATCH_\d+_CHUNK_\d+", value):
        return "EDIT_BATCH"
    for prefix in ("EDIT_BATCH", "WRITE_METADATA", "EDIT_AFTER_REOPEN"):
        if re.fullmatch(rf"{prefix}_\d+", value):
            return prefix
    return value


def _median(values: Iterable[float]) -> float:
    materialized = [float(value) for value in values]
    return float(statistics.median(materialized)) if materialized else 0.0


def _vma_baseline_key(vma: Mapping[str, Any]) -> tuple[Any, ...]:
    pid = int(vma.get("pid", -1))
    mapping_type = str(vma.get("mapping_type", "UNKNOWN"))
    inode = vma.get("inode")
    if inode not in (None, 0):
        return (
            "FILE", pid, vma.get("dev_major"), vma.get("dev_minor"), inode,
            vma.get("permissions"), vma.get("file_offset_bytes"), vma.get("file_offset_end_bytes"),
        )
    return (
        "ANON", pid, vma.get("start_address"), vma.get("end_address"),
        vma.get("normalized_path") or vma.get("path") or "", vma.get("permissions"),
        vma.get("segment"), mapping_type,
    )


def median_baseline_vmas(
    baseline_windows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], float, str, list[Mapping[str, Any]]]:
    """Build a per-VMA median baseline from support-eligible baseline windows."""
    valid = [
        window for window in baseline_windows
        if bool(window.get("support_eligible"))
        and str(window.get("collection_quality", "OK")) == "OK"
        and window.get("vmas") is not None
    ]
    if not valid:
        return [], 0.0, "NO_VALID_BASELINE_WINDOWS", []
    quality = "OK" if len(valid) >= 2 else "SINGLE_BASELINE_WINDOW"
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for window in valid:
        for vma in window.get("vmas", []):
            groups[_vma_baseline_key(vma)].append(vma)
    median_fields = (
        "referenced_pages", "referenced_kib", "rss_kib", "pss_kib", "swap_kib",
        "referenced_size_ratio", "referenced_rss_ratio",
    )
    result: list[dict[str, Any]] = []
    for records in groups.values():
        row = dict(records[0])
        for field in median_fields:
            numeric = [item[field] for item in records if isinstance(item.get(field), (int, float))]
            if numeric:
                row[field] = _median(numeric)
        row["baseline_observation_count"] = len(records)
        row["baseline_estimation_method"] = PRIMARY_ESTIMATION_METHOD
        result.append(row)
    median_duration = _median(float(window["actual_window_s"]) for window in valid)
    return result, median_duration, quality, valid


def _apply_fixed_estimate(
    sample: dict[str, Any], baseline_window_s: float, operation_window_s: float,
    config: Mapping[str, Any],
) -> None:
    baseline_pages = float(sample.get("allocated_baseline_referenced_pages") or 0.0)
    operation_vma = sample["operation_vma"]
    operation_pages = float(operation_vma.get("referenced_pages") or 0.0)
    primary_excess = max(0.0, operation_pages - baseline_pages)
    baseline_rate = baseline_pages / baseline_window_s if baseline_window_s > 0 else 0.0
    normalized_background = baseline_rate * operation_window_s
    normalized_excess = max(0.0, operation_pages - normalized_background)
    page_size_kib = float(operation_vma.get("page_size_bytes") or 4096) / 1024.0
    excess_kib = primary_excess * page_size_kib
    rss_kib = max(float(operation_vma.get("rss_kib") or 0.0), page_size_kib)
    excess_ratio = excess_kib / rss_kib
    sample.update({
        "median_baseline_referenced_pages": baseline_pages,
        "operation_referenced_pages": operation_pages,
        "estimated_excess_pages": primary_excess,
        "estimated_excess_referenced_pages": primary_excess,
        "estimated_excess_referenced_kib": excess_kib,
        "estimated_excess_rss_ratio": excess_ratio,
        "baseline_rate_pages_per_s": baseline_rate,
        "time_normalized_background_pages": normalized_background,
        "time_normalized_estimated_excess_pages": normalized_excess,
        "primary_estimation_method": PRIMARY_ESTIMATION_METHOD,
        "compatibility_estimation_method": COMPATIBILITY_ESTIMATION_METHOD,
        "estimation_method": PRIMARY_ESTIMATION_METHOD,
        "activity_level": classify_activity(primary_excess, excess_ratio, config),
    })


def _compact_window_sample(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a pair while retaining auditable VMA identity/interval evidence."""
    fields = {
        "window_id", "operation_execution_id", "operation_id", "segment_index", "segment_label",
        "normalized_segment_label", "baseline_group_id", "support_eligible", "support_exclusion_reason",
        "pid", "process_role", "process_match_quality", "collection_quality", "baseline_quality",
        "vma_match_quality", "window_quality", "activity_quality", "identity_confidence",
        "baseline_vma_count", "file_overlap_bytes", "virtual_overlap_bytes",
        "median_baseline_referenced_pages", "operation_referenced_pages", "estimated_excess_pages",
        "estimated_excess_referenced_kib", "estimated_excess_rss_ratio",
        "time_normalized_estimated_excess_pages", "activity_level",
        "primary_estimation_method", "compatibility_estimation_method",
        "file_instance_key", "semantic_file_key", "granularity", "identity_scope",
        "anonymous_auxiliary_key", "anon_type", "anon_name", "vma_size_bucket", "usage",
        "long_term_page_mapping", "protection_eligible", "prefetch_eligible",
    }
    result = {key: sample[key] for key in fields if key in sample}
    operation = sample.get("operation_vma", {})
    result.update({
        "operation_vma_start": operation.get("start_address"),
        "operation_vma_end": operation.get("end_address"),
        "operation_file_offset_start": operation.get("file_offset_bytes"),
        "operation_file_offset_end": operation.get("file_offset_end_bytes"),
        "operation_device": operation.get("device"),
        "operation_dev_major": operation.get("dev_major"),
        "operation_dev_minor": operation.get("dev_minor"),
        "operation_inode": operation.get("inode"),
        "operation_permissions": operation.get("permissions"),
        "operation_mapping_type": operation.get("mapping_type"),
        "operation_path": operation.get("normalized_path") or operation.get("path") or "",
        "operation_rss_kib": operation.get("rss_kib"),
    })
    result["baseline_vma_intervals"] = [{
        "start_address": item.get("start_address"), "end_address": item.get("end_address"),
        "file_offset_bytes": item.get("file_offset_bytes"),
        "file_offset_end_bytes": item.get("file_offset_end_bytes"),
        "dev_major": item.get("dev_major"), "dev_minor": item.get("dev_minor"),
        "inode": item.get("inode"), "permissions": item.get("permissions"),
        "mapping_type": item.get("mapping_type"),
        "referenced_pages": item.get("referenced_pages"),
    } for item in sample.get("baseline_vmas", [])]
    return result


def _pair_reference(sample: Mapping[str, Any], sample_kind: str) -> dict[str, Any]:
    fields = (
        "window_id", "operation_execution_id", "operation_id", "segment_index", "segment_label",
        "normalized_segment_label", "baseline_group_id", "support_eligible", "support_exclusion_reason",
        "pid", "process_role", "process_match_quality", "vma_match_quality", "baseline_vma_count",
        "file_overlap_bytes", "virtual_overlap_bytes", "operation_vma_start", "operation_vma_end",
        "operation_file_offset_start", "operation_file_offset_end", "operation_dev_major",
        "operation_dev_minor", "operation_inode", "operation_permissions", "operation_mapping_type",
        "baseline_vma_intervals",
    )
    return {"sample_kind": sample_kind, **{key: sample.get(key) for key in fields if key in sample}}


def map_fixed_window(
    *,
    baseline_windows: Sequence[Mapping[str, Any]],
    operation_window: Mapping[str, Any],
    app_id: str,
    config: Mapping[str, Any],
    session_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one operation window against the median of its valid baselines."""
    baseline_vmas, baseline_duration, baseline_quality, valid = median_baseline_vmas(baseline_windows)
    common = {
        "window_id": operation_window.get("window_id"),
        "operation_execution_id": operation_window.get("operation_execution_id"),
        "operation_id": operation_window.get("operation_id"),
        "segment_index": operation_window.get("segment_index"),
        "segment_label": operation_window.get("segment_label"),
        "normalized_segment_label": normalize_segment_label(str(operation_window.get("segment_label", ""))),
        "baseline_group_id": operation_window.get("baseline_group_id"),
    }
    if baseline_quality == "NO_VALID_BASELINE_WINDOWS":
        return {
            **common,
            "baseline_quality": baseline_quality,
            "support_eligible": False,
            "support_exclusion_reason": baseline_quality,
            "process_pairing": {"pairs": [], "new_processes": [], "exited_processes": [], "pid_reused": []},
            "paired_vmas": [], "file_samples": [], "anonymous_samples": [],
            "summary": {"paired_process_count": 0, "paired_vma_count": 0},
            "vma_mapping_status": "DEGRADED", "vma_mapping_error": baseline_quality,
        }
    result = map_operation_stage(
        stage=str(operation_window.get("operation_id", "")),
        baseline_processes=valid[-1].get("processes", []),
        operation_processes=operation_window.get("processes", []),
        baseline_vmas=baseline_vmas,
        operation_vmas=operation_window.get("vmas", []),
        baseline_window_s=baseline_duration,
        operation_window_s=float(operation_window.get("actual_window_s") or 0.0),
        app_id=app_id,
        config=config,
        session_context=session_context,
    )
    # Raw VMA evidence remains in the collector JSONL referenced by each
    # window. Repeating both full snapshots in every sequence result creates
    # quadratic multi-gigabyte output without adding evidence.
    result.pop("raw_baseline_vmas", None)
    result.pop("raw_operation_vmas", None)
    window_eligible = bool(operation_window.get("support_eligible"))
    collection_ok = str(operation_window.get("collection_quality", "OK")) == "OK"
    process_ok = not result["process_pairing"].get("pid_reused")
    eligible = window_eligible and collection_ok and process_ok
    exclusion = str(operation_window.get("support_exclusion_reason") or "")
    if not collection_ok:
        exclusion = "COLLECTION_QUALITY"
    elif not process_ok:
        exclusion = "PID_REUSED"
    for key in ("paired_vmas", "file_samples", "anonymous_samples"):
        for sample in result[key]:
            _apply_fixed_estimate(sample, baseline_duration, float(operation_window["actual_window_s"]), config)
            sample.update(common)
            sample.update({
                "baseline_quality": baseline_quality,
                "window_quality": operation_window.get("window_quality"),
                "support_eligible": eligible,
                "support_exclusion_reason": exclusion,
            })
    compact_file = [_compact_window_sample(item) for item in result["file_samples"]]
    compact_anon = [_compact_window_sample(item) for item in result["anonymous_samples"]]
    result["paired_vmas"] = (
        [_pair_reference(item, "FILE") for item in compact_file]
        + [_pair_reference(item, "ANON") for item in compact_anon]
    )
    result["file_samples"] = [
        {key: value for key, value in item.items() if key != "baseline_vma_intervals"}
        for item in compact_file
    ]
    result["anonymous_samples"] = [
        {key: value for key, value in item.items() if key != "baseline_vma_intervals"}
        for item in compact_anon
    ]
    result.update(common)
    result.update({
        "baseline_quality": baseline_quality,
        "baseline_valid_window_count": len(valid),
        "median_baseline_window_s": baseline_duration,
        "support_eligible": eligible,
        "support_exclusion_reason": exclusion,
        "schema_version": "homeny.operation-window-vma.v1",
    })
    return result


def aggregate_execution(window_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate valid window samples without claiming a unique page set."""
    eligible = [item for item in window_results if bool(item.get("support_eligible"))]
    by_key: dict[str, dict[str, Any]] = {}
    for result in eligible:
        for sample in list(result.get("file_samples", [])) + list(result.get("anonymous_samples", [])):
            key = str(sample.get("semantic_file_key") or sample.get("anonymous_auxiliary_key") or "")
            if not key:
                continue
            row = by_key.setdefault(key, {
                "feature_key": key, "sum_estimated_excess_vma_pages": 0.0,
                "max_estimated_excess_pages": 0.0, "active_window_count": 0,
                "window_count": 0,
            })
            value = float(sample.get("estimated_excess_pages") or 0.0)
            row["sum_estimated_excess_vma_pages"] += value
            row["max_estimated_excess_pages"] = max(row["max_estimated_excess_pages"], value)
            row["window_count"] += 1
            if str(sample.get("activity_level")) in {"WEAK", "STRONG"}:
                row["active_window_count"] += 1
    return {
        "aggregation_semantics": "SUM_OF_VMA_WINDOW_SAMPLES_NOT_UNIQUE_PAGE_SET",
        "eligible_window_count": len(eligible),
        "feature_aggregates": sorted(by_key.values(), key=lambda item: item["feature_key"]),
        "sum_estimated_excess_vma_pages": sum(
            float(item["sum_estimated_excess_vma_pages"]) for item in by_key.values()
        ),
    }


def weighted_jaccard(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(float(left.get(key, 0.0)), float(right.get(key, 0.0))) for key in keys)
    if denominator == 0:
        return 1.0
    return sum(min(float(left.get(key, 0.0)), float(right.get(key, 0.0))) for key in keys) / denominator


def cosine_similarity(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    left_norm = math.sqrt(sum(float(left.get(key, 0.0)) ** 2 for key in keys))
    right_norm = math.sqrt(sum(float(right.get(key, 0.0)) ** 2 for key in keys))
    if left_norm == 0 and right_norm == 0:
        return 1.0
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(float(left.get(key, 0.0)) * float(right.get(key, 0.0)) for key in keys) / (left_norm * right_norm)


def top_k_overlap(left: Mapping[str, float], right: Mapping[str, float], k: int = 10) -> float:
    if k < 1:
        raise ValueError("k must be >= 1")
    left_keys = {key for key, _ in sorted(left.items(), key=lambda item: (-float(item[1]), item[0]))[:k]}
    right_keys = {key for key, _ in sorted(right.items(), key=lambda item: (-float(item[1]), item[0]))[:k]}
    denominator = max(len(left_keys), len(right_keys))
    return len(left_keys & right_keys) / denominator if denominator else 1.0


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
