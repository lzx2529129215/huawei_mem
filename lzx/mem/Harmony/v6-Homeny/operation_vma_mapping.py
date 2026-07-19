#!/usr/bin/env python3
"""Pure baseline/operation VMA pairing and activity analysis."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "homeny.vma.v1"
ESTIMATION_METHOD = "TIME_NORMALIZED_REFERENCED_HEURISTIC"
FILE_MAPPING_TYPES = {"FILE", "SHARED_LIBRARY", "HAP_FILE", "FONT_FILE", "DOCUMENT_FILE"}
ANON_MAPPING_TYPES = {"ANON_HEAP", "ANON_STACK", "NAMED_ANON", "ANON_OTHER", "GUARD", "UNKNOWN"}

REQUIRED_VMA_FIELDS = {
    "schema_version",
    "record_type",
    "pid",
    "page_size_bytes",
    "start_address",
    "end_address",
    "address_size_bytes",
    "permissions",
    "file_offset_bytes",
    "file_offset_end_bytes",
    "device",
    "dev_major",
    "dev_minor",
    "inode",
    "path",
    "normalized_path",
    "path_deleted",
    "segment",
    "mapping_type",
    "size_kib",
    "rss_kib",
    "referenced_kib",
    "referenced_pages",
    "referenced_size_ratio",
    "referenced_rss_ratio",
}


class VmaJsonError(ValueError):
    """A JSONL record violates the homeny.vma.v1 contract."""


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else Path(__file__).with_name("vma_mapping_config.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"unsupported config schema: {payload.get('schema_version')!r}")
    return payload


def validate_vma_record(record: Mapping[str, Any], source: str, line_number: int) -> dict[str, Any]:
    missing = sorted(REQUIRED_VMA_FIELDS - record.keys())
    if missing:
        raise VmaJsonError(f"{source}:{line_number}: missing fields {missing}")
    if record.get("schema_version") != SCHEMA_VERSION or record.get("record_type") != "vma":
        raise VmaJsonError(f"{source}:{line_number}: unsupported VMA schema")
    start = record.get("start_address")
    end = record.get("end_address")
    if not isinstance(start, int) or not isinstance(end, int) or end < start:
        raise VmaJsonError(f"{source}:{line_number}: invalid address interval")
    for field in ("referenced_size_ratio", "referenced_rss_ratio"):
        ratio = record.get(field)
        if ratio is not None and (
            not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.0 <= float(ratio) <= 1.0
        ):
            raise VmaJsonError(f"{source}:{line_number}: invalid {field} ratio")
    result = dict(record)
    result["source_jsonl"] = source
    result["source_line"] = line_number
    return result


def load_vma_jsonl(paths: Iterable[Path | str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise VmaJsonError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(parsed, dict):
                raise VmaJsonError(f"{path}:{line_number}: record is not an object")
            records.append(validate_vma_record(parsed, str(path), line_number))
    return records


def _pid(row: Mapping[str, Any]) -> str:
    return str(row.get("pid", ""))


def pair_processes(
    baseline_rows: Iterable[Mapping[str, Any]],
    operation_rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    baseline = {_pid(row): dict(row) for row in baseline_rows if _pid(row)}
    operation = {_pid(row): dict(row) for row in operation_rows if _pid(row)}
    result: dict[str, list[dict[str, Any]]] = {
        "pairs": [],
        "new_processes": [],
        "exited_processes": [],
        "pid_reused": [],
    }
    for pid in sorted(set(baseline) | set(operation), key=lambda value: int(value)):
        before = baseline.get(pid)
        after = operation.get(pid)
        if before is None:
            result["new_processes"].append({"operation": after, "quality": "NEW_PROCESS_NO_BASELINE"})
            continue
        if after is None:
            result["exited_processes"].append({"baseline": before, "quality": "PROCESS_EXITED"})
            continue
        before_available = bool(before.get("starttime_available")) and isinstance(before.get("process_starttime"), int)
        after_available = bool(after.get("starttime_available")) and isinstance(after.get("process_starttime"), int)
        if before_available and after_available and before["process_starttime"] != after["process_starttime"]:
            result["pid_reused"].append({"baseline": before, "operation": after, "quality": "PID_REUSED"})
            continue
        quality = "OK" if before_available and after_available else "PID_ONLY_MATCH"
        result["pairs"].append({"baseline": before, "operation": after, "quality": quality})
    return result


def _overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _referenced_pages(vma: Mapping[str, Any]) -> float:
    value = vma.get("referenced_pages")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _file_identity_matches(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left.get("dev_major") is not None
        and left.get("dev_minor") is not None
        and left.get("inode") not in (None, 0)
        and left.get("dev_major") == right.get("dev_major")
        and left.get("dev_minor") == right.get("dev_minor")
        and left.get("inode") == right.get("inode")
        and left.get("permissions") == right.get("permissions")
    )


def pair_file_vmas(
    baseline_vmas: Sequence[Mapping[str, Any]],
    operation_vmas: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    edges: list[dict[str, Any]] = []
    baseline_degree = [0] * len(baseline_vmas)
    operation_degree = [0] * len(operation_vmas)
    overlap_totals = [0] * len(baseline_vmas)
    operation_groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for operation_index, after in enumerate(operation_vmas):
        operation_groups[
            (after.get("dev_major"), after.get("dev_minor"), after.get("inode"), after.get("permissions"))
        ].append(operation_index)
    for baseline_index, before in enumerate(baseline_vmas):
        key = (before.get("dev_major"), before.get("dev_minor"), before.get("inode"), before.get("permissions"))
        for operation_index in operation_groups.get(key, []):
            after = operation_vmas[operation_index]
            if not _file_identity_matches(before, after):
                continue
            overlap = _overlap(
                int(before["file_offset_bytes"]),
                int(before["file_offset_end_bytes"]),
                int(after["file_offset_bytes"]),
                int(after["file_offset_end_bytes"]),
            )
            if overlap <= 0:
                continue
            edges.append({"baseline_index": baseline_index, "operation_index": operation_index, "overlap": overlap})
            baseline_degree[baseline_index] += 1
            operation_degree[operation_index] += 1
            overlap_totals[baseline_index] += overlap

    grouped: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        before = baseline_vmas[edge["baseline_index"]]
        allocated = _referenced_pages(before) * edge["overlap"] / overlap_totals[edge["baseline_index"]]
        grouped.setdefault(edge["operation_index"], []).append({**edge, "allocated": allocated})

    paired: list[dict[str, Any]] = []
    unpaired_operation: list[dict[str, Any]] = []
    for operation_index, after in enumerate(operation_vmas):
        matches = grouped.get(operation_index, [])
        if not matches:
            unpaired_operation.append({"operation_vma": dict(after), "vma_match_quality": "NO_BASELINE"})
            continue
        split_merge = operation_degree[operation_index] > 1 or any(
            baseline_degree[item["baseline_index"]] > 1 for item in matches
        )
        paired.append(
            {
                "operation_vma": dict(after),
                "baseline_vmas": [dict(baseline_vmas[item["baseline_index"]]) for item in matches],
                "baseline_vma_count": len(matches),
                "file_overlap_bytes": sum(item["overlap"] for item in matches),
                "allocated_baseline_referenced_pages": sum(item["allocated"] for item in matches),
                "vma_match_quality": "VMA_SPLIT_MERGE_APPROXIMATION" if split_merge else "FILE_OFFSET_OVERLAP_MATCH",
            }
        )
    matched_baseline = {edge["baseline_index"] for edge in edges}
    return {
        "paired": paired,
        "unpaired_operation": unpaired_operation,
        "unpaired_baseline": [
            {"baseline_vma": dict(item), "vma_match_quality": "PROCESS_EXITED"}
            for index, item in enumerate(baseline_vmas)
            if index not in matched_baseline
        ],
    }


def _anonymous_identity_matches(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        (left.get("normalized_path") or left.get("path") or "")
        == (right.get("normalized_path") or right.get("path") or "")
        and left.get("permissions") == right.get("permissions")
        and left.get("segment") == right.get("segment")
        and left.get("mapping_type") == right.get("mapping_type")
    )


def pair_anonymous_vmas(
    baseline_vmas: Sequence[Mapping[str, Any]],
    operation_vmas: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    edges: list[dict[str, Any]] = []
    baseline_degree = [0] * len(baseline_vmas)
    operation_degree = [0] * len(operation_vmas)
    overlap_totals = [0] * len(baseline_vmas)
    operation_groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for operation_index, after in enumerate(operation_vmas):
        operation_groups[
            (
                after.get("normalized_path") or after.get("path") or "",
                after.get("permissions"),
                after.get("segment"),
                after.get("mapping_type"),
            )
        ].append(operation_index)
    for baseline_index, before in enumerate(baseline_vmas):
        key = (
            before.get("normalized_path") or before.get("path") or "",
            before.get("permissions"),
            before.get("segment"),
            before.get("mapping_type"),
        )
        for operation_index in operation_groups.get(key, []):
            after = operation_vmas[operation_index]
            if not _anonymous_identity_matches(before, after):
                continue
            overlap = _overlap(
                int(before["start_address"]),
                int(before["end_address"]),
                int(after["start_address"]),
                int(after["end_address"]),
            )
            if overlap <= 0:
                continue
            edges.append({"baseline_index": baseline_index, "operation_index": operation_index, "overlap": overlap})
            baseline_degree[baseline_index] += 1
            operation_degree[operation_index] += 1
            overlap_totals[baseline_index] += overlap

    grouped: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        allocated = (
            _referenced_pages(baseline_vmas[edge["baseline_index"]])
            * edge["overlap"]
            / overlap_totals[edge["baseline_index"]]
        )
        grouped.setdefault(edge["operation_index"], []).append({**edge, "allocated": allocated})

    paired: list[dict[str, Any]] = []
    unpaired_operation: list[dict[str, Any]] = []
    for operation_index, after in enumerate(operation_vmas):
        matches = grouped.get(operation_index, [])
        if not matches:
            unpaired_operation.append({"operation_vma": dict(after), "vma_match_quality": "NO_BASELINE"})
            continue
        split_merge = operation_degree[operation_index] > 1 or any(
            baseline_degree[item["baseline_index"]] > 1 for item in matches
        )
        paired.append(
            {
                "operation_vma": dict(after),
                "baseline_vmas": [dict(baseline_vmas[item["baseline_index"]]) for item in matches],
                "baseline_vma_count": len(matches),
                "virtual_overlap_bytes": sum(item["overlap"] for item in matches),
                "allocated_baseline_referenced_pages": sum(item["allocated"] for item in matches),
                "vma_match_quality": "VMA_SPLIT_MERGE_APPROXIMATION" if split_merge else "ANON_ADDRESS_OVERLAP_MATCH",
            }
        )
    matched_baseline = {edge["baseline_index"] for edge in edges}
    return {
        "paired": paired,
        "unpaired_operation": unpaired_operation,
        "unpaired_baseline": [
            {"baseline_vma": dict(item), "vma_match_quality": "PROCESS_EXITED"}
            for index, item in enumerate(baseline_vmas)
            if index not in matched_baseline
        ],
    }


def window_quality(baseline_window_s: float, operation_window_s: float, config: Mapping[str, Any]) -> str:
    idle = config["idle_baseline"]
    minimum = float(idle["min_valid_window_s"])
    if baseline_window_s < minimum:
        return "BASELINE_WINDOW_TOO_SHORT"
    if operation_window_s < minimum:
        return "OPERATION_WINDOW_TOO_SHORT"
    ratio = operation_window_s / baseline_window_s
    if float(idle["normal_duration_ratio_min"]) <= ratio <= float(idle["normal_duration_ratio_max"]):
        return "OK"
    if float(idle["mismatch_duration_ratio_min"]) <= ratio <= float(idle["mismatch_duration_ratio_max"]):
        return "WINDOW_MISMATCH"
    return "SEVERE_WINDOW_MISMATCH"


def classify_activity(excess_pages: float, excess_rss_ratio: float, config: Mapping[str, Any]) -> str:
    thresholds = config["activity_thresholds"]
    if excess_pages >= float(thresholds["strong_absolute_pages"]):
        return "STRONG"
    if (
        excess_pages >= float(thresholds["strong_min_pages"])
        and excess_rss_ratio >= float(thresholds["strong_excess_rss_ratio"])
    ):
        return "STRONG"
    if (
        excess_pages >= float(thresholds["weak_min_pages"])
        and excess_rss_ratio >= float(thresholds["weak_excess_rss_ratio"])
    ):
        return "WEAK"
    return "INACTIVE"


def estimate_background_activity(
    *,
    baseline_referenced_pages: float,
    operation_referenced_pages: float,
    baseline_window_s: float,
    operation_window_s: float,
    operation_rss_kib: float,
    page_size_bytes: int,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    quality = window_quality(baseline_window_s, operation_window_s, config)
    baseline_rate = baseline_referenced_pages / baseline_window_s if baseline_window_s > 0 else 0.0
    estimated_background = baseline_rate * operation_window_s
    excess_pages = max(0.0, operation_referenced_pages - estimated_background)
    page_size_kib = page_size_bytes / 1024.0
    excess_kib = excess_pages * page_size_kib
    excess_rss_ratio = excess_kib / max(float(operation_rss_kib), page_size_kib)
    return {
        "baseline_referenced_pages": baseline_referenced_pages,
        "operation_referenced_pages": operation_referenced_pages,
        "baseline_rate_pages_per_s": baseline_rate,
        "estimated_background_pages": estimated_background,
        "estimated_excess_referenced_pages": excess_pages,
        "estimated_excess_referenced_kib": excess_kib,
        "estimated_excess_rss_ratio": excess_rss_ratio,
        "baseline_window_s": baseline_window_s,
        "operation_window_s": operation_window_s,
        "window_duration_ratio": operation_window_s / baseline_window_s if baseline_window_s > 0 else None,
        "window_quality": quality,
        "estimation_method": ESTIMATION_METHOD,
        "activity_level": classify_activity(excess_pages, excess_rss_ratio, config),
        "activity_quality": quality,
    }


def _stable_key(namespace: str, components: Mapping[str, Any]) -> str:
    canonical = json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{namespace}:v1:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def exact_file_instance_key(vma: Mapping[str, Any], process_role: str) -> str:
    components = {
        "process_role": process_role,
        "dev_major": vma.get("dev_major"),
        "dev_minor": vma.get("dev_minor"),
        "inode": vma.get("inode"),
        "permissions": vma.get("permissions"),
        "file_offset_start": vma.get("file_offset_bytes"),
        "file_offset_end": vma.get("file_offset_end_bytes"),
    }
    return _stable_key("file-instance", components)


def semantic_file_key(
    vma: Mapping[str, Any],
    process_role: str,
    session_context: Mapping[str, Any],
) -> str:
    mapping_type = str(vma.get("mapping_type", "UNKNOWN"))
    normalized_path = str(vma.get("normalized_path") or vma.get("path") or "")
    if mapping_type == "DOCUMENT_FILE" and session_context.get("current_test_document"):
        semantic_identity = "CURRENT_TEST_DOCUMENT"
    elif mapping_type == "DOCUMENT_FILE":
        semantic_identity = f"DOCUMENT_SUFFIX:{Path(normalized_path).suffix.lower() or 'unknown'}"
    elif mapping_type == "SHARED_LIBRARY":
        semantic_identity = normalized_path or Path(normalized_path).name
    else:
        semantic_identity = normalized_path or Path(normalized_path).name
    components = {
        "process_role": process_role,
        "mapping_type": mapping_type,
        "semantic_identity": semantic_identity,
        "permissions": vma.get("permissions"),
        "relative_file_offset_start": vma.get("file_offset_bytes"),
        "relative_file_offset_end": vma.get("file_offset_end_bytes"),
    }
    return _stable_key("semantic-file", components)


def _size_bucket(size_bytes: int) -> str:
    kib = size_bytes / 1024.0
    boundaries = (
        (64, "0-64KiB"),
        (256, "64-256KiB"),
        (1024, "256KiB-1MiB"),
        (4096, "1-4MiB"),
        (16384, "4-16MiB"),
        (65536, "16-64MiB"),
        (262144, "64-256MiB"),
    )
    for limit, label in boundaries:
        if kib < limit:
            return label
    return "256MiB+"


def anonymous_auxiliary_feature(
    vma: Mapping[str, Any],
    process_role: str,
    app_id: str,
) -> dict[str, Any]:
    anon_name = str(vma.get("normalized_path") or vma.get("path") or "")
    bucket = _size_bucket(int(vma.get("address_size_bytes") or 0))
    components = {
        "app_id": app_id,
        "process_role": process_role,
        "anon_type": vma.get("mapping_type"),
        "anon_name": anon_name,
        "permissions": vma.get("permissions"),
        "vma_size_bucket": bucket,
    }
    return {
        "anonymous_auxiliary_key": _stable_key("anonymous-aux", components),
        **components,
        "usage": "OPERATION_RECOGNITION_AUXILIARY",
        "runtime_instance_only": False,
        "long_term_page_mapping": False,
        "protection_eligible": False,
        "prefetch_eligible": False,
        "identity_confidence": "MEDIUM" if anon_name else "LOW",
        "runtime_vma_start": vma.get("start_address"),
        "runtime_vma_end": vma.get("end_address"),
        "runtime_instance_only_address": True,
    }


def _is_file_vma(vma: Mapping[str, Any]) -> bool:
    return str(vma.get("mapping_type")) in FILE_MAPPING_TYPES and vma.get("inode") not in (None, 0)


def _is_anonymous_vma(vma: Mapping[str, Any]) -> bool:
    return not _is_file_vma(vma) and str(vma.get("mapping_type")) in ANON_MAPPING_TYPES


def _activity_for_pair(
    item: Mapping[str, Any],
    baseline_window_s: float,
    operation_window_s: float,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    operation_vma = item["operation_vma"]
    activity = estimate_background_activity(
        baseline_referenced_pages=float(item["allocated_baseline_referenced_pages"]),
        operation_referenced_pages=_referenced_pages(operation_vma),
        baseline_window_s=baseline_window_s,
        operation_window_s=operation_window_s,
        operation_rss_kib=float(operation_vma.get("rss_kib") or 0),
        page_size_bytes=int(operation_vma.get("page_size_bytes") or 4096),
        config=config,
    )
    return {**dict(item), **activity}


def map_operation_stage(
    *,
    stage: str,
    baseline_processes: Sequence[Mapping[str, Any]],
    operation_processes: Sequence[Mapping[str, Any]],
    baseline_vmas: Sequence[Mapping[str, Any]],
    operation_vmas: Sequence[Mapping[str, Any]],
    baseline_window_s: float,
    operation_window_s: float,
    app_id: str,
    config: Mapping[str, Any] | None = None,
    session_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or load_config())
    context = dict(session_context or {})
    process_result = pair_processes(baseline_processes, operation_processes)
    file_samples: list[dict[str, Any]] = []
    anon_samples: list[dict[str, Any]] = []
    paired_vmas: list[dict[str, Any]] = []

    for process_pair in process_result["pairs"]:
        pid = int(process_pair["operation"]["pid"])
        process_role = str(process_pair["operation"].get("process_role", "WPS_OTHER"))
        before_for_pid = [item for item in baseline_vmas if int(item.get("pid", -1)) == pid]
        after_for_pid = [item for item in operation_vmas if int(item.get("pid", -1)) == pid]
        file_result = pair_file_vmas(
            [item for item in before_for_pid if _is_file_vma(item)],
            [item for item in after_for_pid if _is_file_vma(item)],
        )
        anon_result = pair_anonymous_vmas(
            [item for item in before_for_pid if _is_anonymous_vma(item)],
            [item for item in after_for_pid if _is_anonymous_vma(item)],
        )
        for raw in file_result["paired"]:
            sample = _activity_for_pair(raw, baseline_window_s, operation_window_s, cfg)
            operation_vma = sample["operation_vma"]
            activity_quality = sample["window_quality"]
            if process_pair["quality"] != "OK":
                activity_quality = process_pair["quality"]
            elif sample["vma_match_quality"] == "VMA_SPLIT_MERGE_APPROXIMATION":
                activity_quality = "VMA_SPLIT_MERGE_APPROXIMATION"
            sample.update(
                {
                    "stage": stage,
                    "pid": pid,
                    "process_role": process_role,
                    "process_match_quality": process_pair["quality"],
                    "collection_quality": "OK",
                    "baseline_quality": "OK",
                    "activity_quality": activity_quality,
                    "file_instance_key": exact_file_instance_key(operation_vma, process_role),
                    "semantic_file_key": semantic_file_key(operation_vma, process_role, context),
                    "identity_scope": "SAME_DEVICE_INODE_FILE_INSTANCE",
                    "identity_confidence": "HIGH" if process_pair["quality"] == "OK" else "MEDIUM",
                    "granularity": "FILE_VMA_OFFSET_INTERVAL",
                    "protection_eligible": False,
                    "future_refinement": "DAMON_OR_PAGE_LEVEL_OFFSET_MONITORING",
                }
            )
            file_samples.append(sample)
            paired_vmas.append(sample)
        for raw in anon_result["paired"]:
            sample = _activity_for_pair(raw, baseline_window_s, operation_window_s, cfg)
            operation_vma = sample["operation_vma"]
            activity_quality = sample["window_quality"]
            if process_pair["quality"] != "OK":
                activity_quality = process_pair["quality"]
            elif sample["vma_match_quality"] == "VMA_SPLIT_MERGE_APPROXIMATION":
                activity_quality = "VMA_SPLIT_MERGE_APPROXIMATION"
            sample.update(
                {
                    "stage": stage,
                    "pid": pid,
                    "process_role": process_role,
                    "process_match_quality": process_pair["quality"],
                    "collection_quality": "OK",
                    "baseline_quality": "OK",
                    **anonymous_auxiliary_feature(operation_vma, process_role, app_id),
                    "activity_quality": activity_quality,
                }
            )
            anon_samples.append(sample)
            paired_vmas.append(sample)

    summary = {
        "paired_process_count": len(process_result["pairs"]),
        "paired_vma_count": len(paired_vmas),
        "strong_file_vma_count": sum(item["activity_level"] == "STRONG" for item in file_samples),
        "weak_file_vma_count": sum(item["activity_level"] == "WEAK" for item in file_samples),
        "strong_anon_vma_count": sum(item["activity_level"] == "STRONG" for item in anon_samples),
        "weak_anon_vma_count": sum(item["activity_level"] == "WEAK" for item in anon_samples),
        "new_process_without_baseline_count": len(process_result["new_processes"]),
        "exited_process_count": len(process_result["exited_processes"]),
        "pid_only_match_count": sum(item["quality"] == "PID_ONLY_MATCH" for item in process_result["pairs"]),
        "split_merge_match_count": sum(item["vma_match_quality"] == "VMA_SPLIT_MERGE_APPROXIMATION" for item in paired_vmas),
        "window_mismatch_count": sum(item["window_quality"] != "OK" for item in paired_vmas),
        "low_quality_vma_count": sum(
            item["window_quality"] != "OK" or item["process_match_quality"] != "OK" for item in paired_vmas
        ),
    }
    return {
        "schema_version": "homeny.operation-vma.v1",
        "stage": stage,
        "baseline_window_s": baseline_window_s,
        "operation_window_s": operation_window_s,
        "process_pairing": process_result,
        "paired_vmas": paired_vmas,
        "file_samples": file_samples,
        "anonymous_samples": anon_samples,
        "raw_baseline_vmas": [dict(item) for item in baseline_vmas],
        "raw_operation_vmas": [dict(item) for item in operation_vmas],
        "summary": summary,
        "vma_mapping_status": "OK",
        "vma_mapping_error": "",
    }


def append_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_stage_outputs(output_dir: Path, result: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = str(result["stage"])
    raw_records = [
        {"stage": stage, "sample_kind": "BASELINE", **item} for item in result["raw_baseline_vmas"]
    ] + [{"stage": stage, "sample_kind": "OPERATION", **item} for item in result["raw_operation_vmas"]]
    append_jsonl(output_dir / "raw_vma_samples.jsonl", raw_records)
    append_jsonl(output_dir / "paired_vma_samples.jsonl", result["paired_vmas"])
    append_jsonl(output_dir / "operation_file_vma_samples.jsonl", result["file_samples"])
    append_jsonl(output_dir / "operation_anon_vma_samples.jsonl", result["anonymous_samples"])
    quality_path = output_dir / "operation_vma_quality.json"
    existing: dict[str, Any] = {}
    if quality_path.is_file():
        existing = json.loads(quality_path.read_text(encoding="utf-8"))
    existing[stage] = {
        "summary": result["summary"],
        "vma_mapping_status": result["vma_mapping_status"],
        "vma_mapping_error": result["vma_mapping_error"],
    }
    quality_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = output_dir / "operation_vma_summary.md"
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(f"## {stage}\n\n")
        for key, value in result["summary"].items():
            handle.write(f"- `{key}`: `{value}`\n")
        handle.write("\n")
