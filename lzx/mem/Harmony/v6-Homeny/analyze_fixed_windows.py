#!/usr/bin/env python3
"""Analyze cross-trial fixed-window support and sparse-signature similarity."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping

from fixed_window_mapping import (
    cosine_similarity,
    normalize_segment_label,
    percentile,
    top_k_overlap,
    weighted_jaccard,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def iter_jsonl_paths(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def discover_trials(root: Path) -> list[Path]:
    manifest = root / "fixed_window_trials.json"
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(item).expanduser().resolve() for item in payload["trials"]]
    direct = root / "vma_mapping" / "operation_window_samples.jsonl"
    if direct.is_file():
        return [root]
    return sorted({path.parent.parent for path in root.rglob("vma_mapping/operation_window_samples.jsonl")})


def _active(sample: Mapping[str, Any]) -> bool:
    return bool(sample.get("support_eligible")) and str(sample.get("activity_level")) in {"WEAK", "STRONG"}


def support_rows(
    windows: Iterable[Mapping[str, Any]], samples: Iterable[Mapping[str, Any]], feature_field: str,
) -> list[dict[str, Any]]:
    valid_windows = [
        item for item in windows
        if bool(item.get("support_eligible")) and item.get("window_kind") != "BASELINE"
    ]
    segment_denominators: dict[tuple[str, str], set[str]] = defaultdict(set)
    operation_denominators: dict[str, set[str]] = defaultdict(set)
    for window in valid_windows:
        execution = str(window.get("operation_execution_id", ""))
        operation = str(window.get("operation_id", ""))
        segment = normalize_segment_label(str(window.get("segment_label", "")))
        if execution:
            segment_denominators[(operation, segment)].add(execution)
            operation_denominators[operation].add(execution)

    segment_active: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    operation_active: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sample in samples:
        if not _active(sample):
            continue
        feature = str(sample.get(feature_field, ""))
        execution = str(sample.get("operation_execution_id", ""))
        operation = str(sample.get("operation_id", ""))
        segment = normalize_segment_label(str(sample.get("segment_label", "")))
        if feature and execution:
            segment_active[(operation, segment, feature)].add(execution)
            operation_active[(operation, feature)].add(execution)

    rows: list[dict[str, Any]] = []
    for (operation, segment, feature), active in sorted(segment_active.items()):
        denominator = len(segment_denominators[(operation, segment)])
        rows.append({
            "support_level": "SEGMENT", "operation_id": operation,
            "normalized_segment_label": segment, "feature_key": feature,
            "active_execution_count": len(active), "valid_execution_count": denominator,
            "support": len(active) / denominator if denominator else "",
        })
    for (operation, feature), active in sorted(operation_active.items()):
        denominator = len(operation_denominators[operation])
        rows.append({
            "support_level": "OPERATION", "operation_id": operation,
            "normalized_segment_label": "", "feature_key": feature,
            "active_execution_count": len(active), "valid_execution_count": denominator,
            "support": len(active) / denominator if denominator else "",
        })
    return rows


def _vectors(samples: Iterable[Mapping[str, Any]], key_field: str, prefix: str = "") -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for sample in samples:
        if not bool(sample.get("support_eligible")):
            continue
        window_id = str(sample.get("window_id", ""))
        key = str(sample.get(key_field, ""))
        value = float(sample.get("estimated_excess_pages") or 0.0)
        if window_id and key and value > 0:
            result[window_id][prefix + key] += value
    return {window: dict(values) for window, values in result.items()}


def similarity_rows(
    windows: list[Mapping[str, Any]], file_samples: Iterable[Mapping[str, Any]],
    anon_samples: Iterable[Mapping[str, Any]],
    top_k: int = 10,
) -> list[dict[str, Any]]:
    metadata = {
        str(item["window_id"]): item for item in windows
        if bool(item.get("support_eligible")) and item.get("window_kind") != "BASELINE"
    }
    file_vectors = _vectors(file_samples, "semantic_file_key", "FILE:")
    anon_vectors = _vectors(anon_samples, "anonymous_auxiliary_key", "ANON:")
    rows: list[dict[str, Any]] = []
    for left_id, right_id in combinations(sorted(metadata), 2):
        left_meta, right_meta = metadata[left_id], metadata[right_id]
        left_segment = normalize_segment_label(str(left_meta.get("segment_label", "")))
        right_segment = normalize_segment_label(str(right_meta.get("segment_label", "")))
        if left_segment == right_segment:
            relation = "SAME_SEGMENT"
        elif left_meta.get("operation_id") == right_meta.get("operation_id"):
            relation = "SAME_OPERATION"
        else:
            relation = "DIFFERENT_OPERATION"
        for mode in ("FILE_ONLY", "ANON_ONLY", "FILE_ANON"):
            left: dict[str, float] = {}
            right: dict[str, float] = {}
            if mode in {"FILE_ONLY", "FILE_ANON"}:
                left.update(file_vectors.get(left_id, {})); right.update(file_vectors.get(right_id, {}))
            if mode in {"ANON_ONLY", "FILE_ANON"}:
                left.update(anon_vectors.get(left_id, {})); right.update(anon_vectors.get(right_id, {}))
            rows.append({
                "left_window_id": left_id, "right_window_id": right_id,
                "left_operation_id": left_meta.get("operation_id", ""),
                "right_operation_id": right_meta.get("operation_id", ""),
                "left_segment_label": left_segment, "right_segment_label": right_segment,
                "relation": relation, "feature_mode": mode,
                "weighted_jaccard": weighted_jaccard(left, right),
                "cosine_similarity": cosine_similarity(left, right),
                "top_k_overlap": top_k_overlap(left, right, top_k),
            })
    return rows


def summarize_similarity(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        for metric in ("weighted_jaccard", "cosine_similarity", "top_k_overlap"):
            groups[(str(row["relation"]), str(row["feature_mode"]), metric)].append(float(row[metric]))
    result: dict[str, Any] = {}
    for (relation, mode, metric), values in sorted(groups.items()):
        result.setdefault(relation, {}).setdefault(mode, {})[metric] = {
            "mean": statistics.fmean(values), "median": statistics.median(values),
            "p25": percentile(values, .25), "p75": percentile(values, .75),
            "sample_count": len(values),
        }
    return result


def _segment_family(label: str) -> str:
    value = normalize_segment_label(label)
    if value == "EDIT_BATCH" or value.startswith("EDIT_AFTER_REOPEN"):
        return "EDIT"
    if value.startswith("SCROLL"):
        return "SCROLL"
    if value.startswith("WRITE_METADATA"):
        return "WRITE_METADATA"
    return value


def summarize_family_pairs(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        pair = "__".join(sorted((
            _segment_family(str(row["left_segment_label"])),
            _segment_family(str(row["right_segment_label"])),
        )))
        mode = str(row["feature_mode"])
        for metric in ("weighted_jaccard", "cosine_similarity", "top_k_overlap"):
            groups[(pair, mode, metric)].append(float(row[metric]))
    result: dict[str, Any] = {}
    for (pair, mode, metric), values in sorted(groups.items()):
        result.setdefault(pair, {}).setdefault(mode, {})[metric] = {
            "mean": statistics.fmean(values), "median": statistics.median(values),
            "p25": percentile(values, .25), "p75": percentile(values, .75),
            "sample_count": len(values),
        }
    return result


def write_csv(path: Path, rows: list[Mapping[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def analyze(root: Path) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    file_paths: list[Path] = []
    anon_paths: list[Path] = []
    trials = discover_trials(root)
    for trial in trials:
        mapping = trial / "vma_mapping"
        windows.extend(read_jsonl(mapping / "operation_window_samples.jsonl"))
        file_paths.append(mapping / "operation_window_file_vma_samples.jsonl")
        anon_paths.append(mapping / "operation_window_anon_vma_samples.jsonl")
    file_support = support_rows(windows, iter_jsonl_paths(file_paths), "semantic_file_key")
    anon_support = support_rows(windows, iter_jsonl_paths(anon_paths), "anonymous_auxiliary_key")
    similarities = similarity_rows(
        windows, iter_jsonl_paths(file_paths), iter_jsonl_paths(anon_paths)
    )
    stability = {
        "schema_version": "homeny.fixed-window-stability.v1",
        "trial_count": len(trials), "window_count": len(windows),
        "support_eligible_window_count": sum(
            bool(item.get("support_eligible")) and item.get("window_kind") != "BASELINE" for item in windows
        ),
        "similarity": summarize_similarity(similarities),
        "family_pair_similarity": summarize_family_pairs(similarities),
        "ready_for_operation_recognition": False, "ready_for_apply": False,
    }
    support_fields = ["support_level", "operation_id", "normalized_segment_label", "feature_key",
                      "active_execution_count", "valid_execution_count", "support"]
    similarity_fields = ["left_window_id", "right_window_id", "left_operation_id", "right_operation_id",
                         "left_segment_label", "right_segment_label", "relation", "feature_mode",
                         "weighted_jaccard", "cosine_similarity", "top_k_overlap"]
    write_csv(root / "fixed_window_operation_file_support.csv", file_support, support_fields)
    write_csv(root / "fixed_window_operation_anon_support.csv", anon_support, support_fields)
    write_csv(root / "fixed_window_similarity.csv", similarities, similarity_fields)
    (root / "fixed_window_stability.json").write_text(
        json.dumps(stability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Fixed-window analysis", "", f"- Trials: `{len(trials)}`",
             f"- Windows: `{len(windows)}`", f"- Eligible windows: `{stability['support_eligible_window_count']}`",
             "", "## Similarity summaries", "", "```json",
             json.dumps(stability["similarity"], ensure_ascii=False, indent=2), "```", "",
             "This report describes sparse-signature overlap only; it does not claim classifier readiness.",
             "`ready_for_operation_recognition=false`; `ready_for_apply=false`."]
    (root / "fixed_window_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return stability


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.session_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
