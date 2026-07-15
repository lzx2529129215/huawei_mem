#!/usr/bin/env python3
"""Turn repeated WPS sessions into operation -> workload-vector mappings."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from build_workload_feature_vector import FEATURE_ORDER, build_vector, parse_report


EXPECTED_STAGES = (
    "01_open_wps",
    "02_new_word",
    "03_write_metadata",
    "04_heavy_edit_scroll",
    "05_save_document",
    "06_background",
    "07_foreground",
    "08_reopen_saved_document",
    "09_reopen_edit_scroll",
)


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _session_id(trial_dir: Path) -> str:
    path = trial_dir / "session_metadata.json"
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("session_id")
            if value:
                return str(value)
        except (OSError, json.JSONDecodeError):
            pass
    return trial_dir.name


def _trial_index(trial_dir: Path, fallback: int) -> int:
    try:
        return int(trial_dir.name.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        return fallback


def _report_paths(trial_dir: Path, operation: dict[str, str]) -> list[Path]:
    paths: list[Path] = []
    for raw in (operation.get("report") or "").split(";"):
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            path = trial_dir / path.name
        if path.is_file() and path not in paths:
            paths.append(path)
    return paths


def _json_report(report: dict[str, object]) -> dict[str, object]:
    return {
        "source_file": report["source_file"],
        "pid": report["pid"],
        "process_name": report["process_name"],
        "executable": report["executable"],
        "page_size_bytes": report["page_size_bytes"],
        "vma_count": report["vma_count"],
        "size_kib": report["size_kib"],
        "rss_kib": report["rss_kib"],
        "pss_kib": report["pss_kib"],
        "referenced_kib": report["referenced_kib"],
        "swap_kib": report["swap_kib"],
        "raw_segments": {name: metrics.to_dict() for name, metrics in report["raw_segments"].items()},
    }


def _load_sample(trial_dir: Path, stage: str, operation: dict[str, str], trial_index: int) -> dict[str, object]:
    report_paths = _report_paths(trial_dir, operation)
    if not report_paths:
        raise ValueError(f"{trial_dir.name}/{stage}: operations.csv 没有可用报告路径")
    reports = [parse_report(path) for path in report_paths]
    result = build_vector(reports)
    workload_id = f"WPS_{stage}_R{trial_index:02d}"
    vector_dir = trial_dir.parent / "operation_workload_vectors"
    vector_dir.mkdir(parents=True, exist_ok=True)
    vector_path = vector_dir / f"{stage}_repeat_{trial_index:02d}.json"
    payload = {
        "schema_version": 1,
        "workload_id": workload_id,
        "operation": stage,
        "repeat": trial_index,
        "session_id": _session_id(trial_dir),
        "feature_dimension": result["feature_dimension"],
        "feature_order": result["feature_order"],
        "input_reports": [_json_report(report) for report in reports],
        "raw_vector": result["raw_vector"],
        "log1p_vector": result["log1p_vector"],
        "logical_segments": result["logical_segments"],
        "excluded_segments": result["excluded_segments"],
        "overall_report_totals": result["overall_report_totals"],
        "field_semantics": result["field_semantics"],
    }
    vector_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "trial": trial_index,
        "trial_dir": str(trial_dir),
        "session_id": _session_id(trial_dir),
        "stage": stage,
        "workload_id": workload_id,
        "report_count": len(report_paths),
        "report_paths": [str(path) for path in report_paths],
        "vector_json": str(vector_path),
        "raw_vector": result["raw_vector"],
        "log1p_vector": result["log1p_vector"],
        "overall_report_totals": result["overall_report_totals"],
    }


def _stability(samples: list[dict[str, object]], tolerance: float) -> dict[str, object]:
    values_by_feature: dict[str, list[float]] = {
        field: [_float(sample["raw_vector"][field]) for sample in samples] for field in FEATURE_ORDER
    }
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    ranges: dict[str, float] = {}
    relative_ranges: dict[str, float] = {}
    relative_cvs: dict[str, float] = {}
    for field, values in values_by_feature.items():
        mean = statistics.fmean(values)
        std = statistics.pstdev(values) if len(values) > 1 else 0.0
        value_range = max(values) - min(values)
        denominator = max(abs(mean), 1.0)
        means[field] = mean
        stds[field] = std
        ranges[field] = value_range
        relative_ranges[field] = value_range / denominator
        relative_cvs[field] = std / denominator

    exact_fixed = all(
        all(value == values[0] for value in values)
        for values in values_by_feature.values()
    )
    max_relative_range_feature = max(relative_ranges, key=relative_ranges.get)
    max_relative_cv_feature = max(relative_cvs, key=relative_cvs.get)
    center = [means[field] for field in FEATURE_ORDER]
    center_norm = max(math.sqrt(sum(value * value for value in center)), 1.0)
    distances = []
    for sample in samples:
        vector = [_float(sample["raw_vector"][field]) for field in FEATURE_ORDER]
        distances.append(math.sqrt(sum((a - b) ** 2 for a, b in zip(vector, center))) / center_norm)
    return {
        "sample_count": len(samples),
        "exact_fixed": exact_fixed,
        "stable_within_tolerance": len(samples) >= 2 and max(relative_ranges.values()) <= tolerance,
        "tolerance": tolerance,
        "max_relative_range": relative_ranges[max_relative_range_feature],
        "max_relative_range_feature": max_relative_range_feature,
        "max_relative_cv": relative_cvs[max_relative_cv_feature],
        "max_relative_cv_feature": max_relative_cv_feature,
        "mean_relative_l2_distance": statistics.fmean(distances) if distances else 0.0,
        "max_absolute_range": max(ranges.values()) if ranges else 0.0,
        "mean_vector": means,
        "std_vector": stds,
        "range_vector": ranges,
        "relative_range_vector": relative_ranges,
        "relative_cv_vector": relative_cvs,
        "status": "fixed" if exact_fixed else "stable_within_tolerance" if len(samples) >= 2 and max(relative_ranges.values()) <= tolerance else "variable",
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _summary_markdown(
    root: Path,
    expected_repeats: int,
    tolerance: float,
    mapping: dict[str, dict[str, object]],
    errors: list[str],
) -> str:
    lines = [
        "# WPS 操作—workload 特征向量稳定性分析",
        "",
        f"- 实验目录：`{root}`",
        f"- 期望重复次数：`{expected_repeats}`；稳定性容差：`{tolerance:.1%}`（逐维相对范围）",
        "- 向量定义：7 个逻辑段 × 8 个字段 = 56 维；同一操作涉及的所有 WPS PID 先聚合，再生成一条操作级向量。",
        "- Size/RSS/PSS/Swap 是操作后绝对快照；Referenced 是 clear_refs 后观察窗口内访问过的驻留页，不等同于内存增量。",
        "",
        "## 操作—向量映射",
        "",
        "| 操作 | 观测次数 | 精确相同 | 容差内 | 最大逐维相对范围 | 最不稳定维度 | 结论 |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for stage in EXPECTED_STAGES:
        item = mapping.get(stage, {})
        samples = item.get("samples", [])
        stability = item.get("stability") or {}
        lines.append(
            f"| `{stage}` | {len(samples)} / {expected_repeats} | "
            f"{'是' if stability.get('exact_fixed') else '否'} | "
            f"{'是' if stability.get('stable_within_tolerance') else '否'} | "
            f"{float(stability.get('max_relative_range', 0.0)):.2%} | "
            f"`{stability.get('max_relative_range_feature', '')}` | `{stability.get('status', 'missing')}` |"
        )
    lines.extend([
        "",
        "## 如何读取结果",
        "",
        "- `fixed`：三次原始 56 维数值逐维完全相同。",
        f"- `stable_within_tolerance`：三次都有样本，且所有维度的相对范围不超过 {tolerance:.1%}。",
        "- `variable`：向量不是固定值，或至少一个维度跨重复变化超过容差；应继续区分冷启动、缓存状态、PID 集合和操作前文档状态。",
        "- `operation_workload_mapping.json` 保存每个操作每次重复的完整 raw/log1p 向量；`workload_vectors_raw_56d.csv` 便于直接导入聚类或分类程序。",
        "",
        "## 输入会话",
        "",
    ])
    trial_dirs = sorted(path for path in root.glob("trial_*") if path.is_dir())
    for trial in trial_dirs:
        metadata = trial / "session_metadata.json"
        status = "存在" if metadata.is_file() else "缺失 session_metadata.json"
        lines.append(f"- `{trial.name}`：{status}。")
    if errors:
        lines.extend(["", "## 分析错误", "", *[f"- {error}" for error in errors]])
    return "\n".join(lines) + "\n"


def analyze(session_root: Path, expected_repeats: int, tolerance: float) -> dict[str, object]:
    session_root.mkdir(parents=True, exist_ok=True)
    trial_dirs = sorted(path for path in session_root.glob("trial_*") if path.is_dir())
    mapping: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    raw_rows: list[dict[str, object]] = []
    log1p_rows: list[dict[str, object]] = []
    mapping_rows: list[dict[str, object]] = []

    for fallback, trial_dir in enumerate(trial_dirs, start=1):
        trial_index = _trial_index(trial_dir, fallback)
        operations_path = trial_dir / "operations.csv"
        if not operations_path.is_file():
            errors.append(f"{trial_dir.name}: 缺少 operations.csv")
            continue
        with operations_path.open(encoding="utf-8", newline="") as handle:
            rows = {row.get("stage", ""): row for row in csv.DictReader(handle)}
        for stage in EXPECTED_STAGES:
            operation = rows.get(stage)
            if not operation:
                errors.append(f"{trial_dir.name}/{stage}: 缺少操作记录")
                continue
            if operation.get("success") != "true":
                errors.append(f"{trial_dir.name}/{stage}: 操作记录为失败，跳过向量")
                continue
            try:
                sample = _load_sample(trial_dir, stage, operation, trial_index)
            except (OSError, ValueError, KeyError) as exc:
                errors.append(f"{trial_dir.name}/{stage}: {exc}")
                continue
            mapping.setdefault(stage, {"operation": stage, "samples": []})["samples"].append(sample)
            raw_rows.append({
                "trial": sample["trial"],
                "trial_dir": sample["trial_dir"],
                "session_id": sample["session_id"],
                "stage": stage,
                "workload_id": sample["workload_id"],
                "report_count": sample["report_count"],
                **sample["raw_vector"],
            })
            log1p_rows.append({
                "trial": sample["trial"],
                "trial_dir": sample["trial_dir"],
                "session_id": sample["session_id"],
                "stage": stage,
                "workload_id": sample["workload_id"],
                "report_count": sample["report_count"],
                **sample["log1p_vector"],
            })
            mapping_rows.append({
                "stage": stage,
                "trial": sample["trial"],
                "session_id": sample["session_id"],
                "workload_id": sample["workload_id"],
                "report_count": sample["report_count"],
                "vector_json": sample["vector_json"],
            })

    for stage in EXPECTED_STAGES:
        item = mapping.setdefault(stage, {"operation": stage, "samples": []})
        item["stability"] = _stability(item["samples"], tolerance) if item["samples"] else {
            "sample_count": 0,
            "exact_fixed": False,
            "stable_within_tolerance": False,
            "status": "missing",
        }

    raw_path = session_root / "workload_vectors_raw_56d.csv"
    log1p_path = session_root / "workload_vectors_log1p_56d.csv"
    mapping_csv_path = session_root / "operation_workload_mapping.csv"
    mapping_json_path = session_root / "operation_workload_mapping.json"
    summary_csv_path = session_root / "operation_workload_summary.csv"
    summary_md_path = session_root / "workload_stability.md"
    common_fields = ["trial", "trial_dir", "session_id", "stage", "workload_id", "report_count"]
    _write_csv(raw_path, common_fields + list(FEATURE_ORDER), raw_rows)
    _write_csv(log1p_path, common_fields + list(FEATURE_ORDER), log1p_rows)
    _write_csv(mapping_csv_path, ["stage", "trial", "session_id", "workload_id", "report_count", "vector_json"], mapping_rows)

    summary_rows = []
    for stage in EXPECTED_STAGES:
        stability = mapping[stage]["stability"]
        summary_rows.append({
            "stage": stage,
            "expected_repeats": expected_repeats,
            "observed_repeats": stability.get("sample_count", 0),
            "complete": str(stability.get("sample_count", 0) == expected_repeats).lower(),
            "exact_fixed": str(bool(stability.get("exact_fixed", False))).lower(),
            "stable_within_tolerance": str(bool(stability.get("stable_within_tolerance", False))).lower(),
            "status": stability.get("status", "missing"),
            "tolerance": tolerance,
            "max_relative_range": stability.get("max_relative_range", ""),
            "max_relative_range_feature": stability.get("max_relative_range_feature", ""),
            "max_relative_cv": stability.get("max_relative_cv", ""),
            "mean_relative_l2_distance": stability.get("mean_relative_l2_distance", ""),
            "max_absolute_range": stability.get("max_absolute_range", ""),
        })
    _write_csv(summary_csv_path, list(summary_rows[0]) if summary_rows else ["stage"], summary_rows)

    mapping_payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_root": str(session_root.resolve()),
        "expected_repeats": expected_repeats,
        "tolerance": tolerance,
        "feature_dimension": len(FEATURE_ORDER),
        "feature_order": list(FEATURE_ORDER),
        "operation_order": list(EXPECTED_STAGES),
        "operations": mapping,
        "analysis_errors": errors,
    }
    mapping_json_path.write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_md_path.write_text(_summary_markdown(session_root, expected_repeats, tolerance, mapping, errors), encoding="utf-8")
    return {
        "session_root": str(session_root.resolve()),
        "trial_count": len(trial_dirs),
        "sample_count": len(raw_rows),
        "feature_dimension": len(FEATURE_ORDER),
        "mapping_json": str(mapping_json_path.resolve()),
        "summary_csv": str(summary_csv_path.resolve()),
        "summary_md": str(summary_md_path.resolve()),
        "analysis_errors": errors,
        "operations": {stage: mapping[stage]["stability"] for stage in EXPECTED_STAGES},
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tolerance", type=float, default=0.05, help="逐维相对范围容差，默认 0.05")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.repeats < 1 or args.tolerance < 0:
            raise ValueError("repeats 必须 >= 1，tolerance 必须 >= 0")
        result = analyze(args.session_root, args.repeats, args.tolerance)
        compact = {
            key: result[key]
            for key in ("session_root", "trial_count", "sample_count", "feature_dimension", "mapping_json", "summary_csv", "summary_md", "analysis_errors")
        }
        compact["operations"] = {
            stage: {
                key: value
                for key, value in details.items()
                if key in ("sample_count", "exact_fixed", "stable_within_tolerance", "status", "max_relative_range", "max_relative_range_feature")
            }
            for stage, details in result["operations"].items()
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
