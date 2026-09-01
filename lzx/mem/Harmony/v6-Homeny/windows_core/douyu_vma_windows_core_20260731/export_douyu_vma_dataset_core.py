#!/usr/bin/env python3
"""Export a compact, quality-filtered Douyu VMA dataset.

The collection root may contain many raw VMA reports and screenshots.  This
exporter keeps only the rows suitable for PCA/UMAP/clustering, writes an
auditable compact directory, and creates a ZIP without touching the source
directory.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


REQUIRED_INPUTS = ("dataset_manifest.csv", "vma_vectors_l2.csv")
OPTIONAL_INPUTS = (
    "vma_vectors_raw.csv",
    "labels.csv",
    "pairwise_similarity.csv",
    "dataset_summary.json",
    "dataset_analysis.md",
    "operation_catalog.json",
    "trial_failures.csv",
)


def _int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except (TypeError, ValueError):
        return default


def _true(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "pass"}


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _catalog_labels(root: Path, explicit: Path | None) -> list[str]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    candidates.extend((root / "operation_catalog.json", root / "douyu_operation_catalog.json"))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            operations = _load_json(path).get("operations", [])
            labels = [str(item["label"]) for item in operations if item.get("label")]
            if labels:
                return labels
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return []


def _quality_reasons(row: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    if not _true(row.get("support_eligible")):
        reasons.append("support_eligible_not_true")
    if row.get("window_quality", "").strip().lower() != "complete":
        reasons.append("window_not_complete")
    if row.get("collection_quality", "").strip().lower() != "pass":
        reasons.append("collection_quality_not_pass")
    if _int(row.get("hash_mismatch_count")) != 0:
        reasons.append("hash_mismatch")
    if _int(row.get("vector_nonzero_count")) <= 0:
        reasons.append("zero_vector")
    return reasons


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"manifest 没有表头：{path}")
        rows = [dict(row) for row in reader]
    required = {"sample_id", "trial_id", "operation_label"}
    missing = sorted(required - set(rows[0]) if rows else required)
    if missing:
        raise ValueError(f"dataset_manifest.csv 缺少字段：{', '.join(missing)}")
    return rows


def _select_rows(
    rows: list[dict[str, str]],
    expected_labels: list[str],
    allow_incomplete_trials: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Return included rows, excluded rows, and one summary row per trial."""
    expected = set(expected_labels)
    by_trial: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_trial[row.get("trial_id", "").strip()].append(row)

    included: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    trial_summary: list[dict[str, str]] = []
    for trial_id, trial_rows in sorted(by_trial.items()):
        labels = [row.get("operation_label", "").strip() for row in trial_rows]
        label_set = set(labels)
        duplicate_labels = sorted(label for label, count in Counter(labels).items() if count > 1 and label)
        missing_labels = sorted(expected - label_set) if expected else []
        unexpected_labels = sorted(label_set - expected) if expected else []
        trial_reasons: list[str] = []
        if not trial_id:
            trial_reasons.append("missing_trial_id")
        if duplicate_labels:
            trial_reasons.append("duplicate_operation_label")
        if expected and missing_labels:
            trial_reasons.append("missing_operation_label")
        if expected and unexpected_labels:
            trial_reasons.append("unexpected_operation_label")

        row_reasons = {row.get("sample_id", ""): _quality_reasons(row) for row in trial_rows}
        bad_rows = {sample_id: reasons for sample_id, reasons in row_reasons.items() if reasons}
        if bad_rows:
            trial_reasons.append("sample_quality_failed")
        if not allow_incomplete_trials and trial_reasons:
            reason = ";".join(dict.fromkeys(trial_reasons))
            for row in trial_rows:
                reasons = row_reasons.get(row.get("sample_id", ""), [])
                excluded.append(
                    {
                        "sample_id": row.get("sample_id", ""),
                        "trial_id": trial_id,
                        "operation_label": row.get("operation_label", ""),
                        "reason": reason + ("|" + ",".join(reasons) if reasons else ""),
                    }
                )
            selected = False
        else:
            selected = True
            for row in trial_rows:
                reasons = row_reasons.get(row.get("sample_id", ""), [])
                if reasons:
                    excluded.append(
                        {
                            "sample_id": row.get("sample_id", ""),
                            "trial_id": trial_id,
                            "operation_label": row.get("operation_label", ""),
                            "reason": ",".join(reasons),
                        }
                    )
                else:
                    included.append(row)

        trial_summary.append(
            {
                "trial_id": trial_id,
                "source_rows": str(len(trial_rows)),
                "unique_operations": str(len(label_set)),
                "included_samples": str(sum(1 for row in trial_rows if row in included)),
                "selected": str(selected).lower(),
                "reason": ";".join(dict.fromkeys(trial_reasons)),
            }
        )
    return included, excluded, trial_summary


def _write_filtered_csv(
    source: Path,
    destination: Path,
    sample_ids: set[str],
    left_field: str = "sample_id",
    right_field: str | None = None,
) -> tuple[int, set[str]]:
    written = 0
    seen: set[str] = set()
    with source.open("r", encoding="utf-8-sig", newline="") as source_handle, destination.open(
        "w", encoding="utf-8", newline=""
    ) as destination_handle:
        reader = csv.DictReader(source_handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 没有表头：{source}")
        writer = csv.DictWriter(destination_handle, fieldnames=reader.fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            keys = [str(row.get(left_field, ""))]
            if right_field:
                keys.append(str(row.get(right_field, "")))
            if all(key in sample_ids for key in keys):
                writer.writerow(row)
                written += 1
                seen.update(keys)
    return written, seen


def _write_rows(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir.parent))


def export_dataset(args: argparse.Namespace) -> dict:
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"采集目录不存在：{root}")
    for filename in REQUIRED_INPUTS:
        if not (root / filename).is_file():
            raise FileNotFoundError(
                f"缺少 {filename}。请先在 Windows 采集目录运行数据汇总脚本，生成 vma_vectors_l2.csv 和 dataset_manifest.csv。"
            )

    expected_labels = _catalog_labels(root, args.catalog)
    if not expected_labels:
        expected_labels = [f"__label_{index:02d}" for index in range(args.expected_label_count)]
        # When no catalog is present, compare by count rather than placeholder names.
        expected_labels = []
    if not expected_labels and args.expected_label_count < 1:
        raise ValueError("找不到 operation catalog；请使用 --expected-label-count 8 或 --catalog 指定目录")

    manifest_path = root / "dataset_manifest.csv"
    manifest_rows = _read_manifest(manifest_path)
    if not expected_labels and args.expected_label_count:
        # The exact label names are not known, but the trial must contain the configured count.
        expected_labels = []

    # _select_rows uses exact labels when a catalog exists.  Otherwise enforce the count below.
    if expected_labels:
        included, excluded, trial_summary = _select_rows(
            manifest_rows, expected_labels, args.allow_incomplete_trials
        )
    else:
        included, excluded, trial_summary = _select_rows(
            manifest_rows, [], args.allow_incomplete_trials
        )
        if not args.allow_incomplete_trials:
            for summary in trial_summary:
                trial_rows = [row for row in manifest_rows if row.get("trial_id", "") == summary["trial_id"]]
                if int(summary["unique_operations"]) != args.expected_label_count:
                    summary["selected"] = "false"
                    summary["reason"] = "operation_count_not_expected"
                    kept_ids = {row.get("sample_id", "") for row in trial_rows if row in included}
                    for row in trial_rows:
                        if row.get("sample_id", "") in kept_ids:
                            included.remove(row)
                            excluded.append(
                                {
                                    "sample_id": row.get("sample_id", ""),
                                    "trial_id": row.get("trial_id", ""),
                                    "operation_label": row.get("operation_label", ""),
                                    "reason": "operation_count_not_expected",
                                }
                            )
                    summary["included_samples"] = "0"

    sample_ids = {row.get("sample_id", "") for row in included if row.get("sample_id", "")}
    if not sample_ids:
        raise ValueError("没有通过质量筛选的样本；请检查 dataset_manifest.csv 或放宽筛选条件")

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else root / f"douyu_vma_dataset_core_{timestamp}"
    if output_dir.exists():
        raise FileExistsError(f"输出目录已存在，为避免覆盖数据而停止：{output_dir}")
    output_dir.mkdir(parents=True)

    manifest_out = output_dir / "dataset_manifest.csv"
    _write_rows(manifest_out, included, list(manifest_rows[0].keys()))
    labels_source = root / "labels.csv"
    if labels_source.is_file():
        labels_out = output_dir / "labels.csv"
        label_count, label_seen = _write_filtered_csv(labels_source, labels_out, sample_ids)
        if label_seen != sample_ids:
            raise ValueError(f"labels.csv 缺少样本：{sorted(sample_ids - label_seen)[:5]}")
    else:
        label_fields = ["sample_id", "label_id", "operation_label", "trial_id", "session_id"]
        _write_rows(output_dir / "labels.csv", included, label_fields)
        label_count = len(included)

    vector_dim = 0
    summary_path = root / "dataset_summary.json"
    if summary_path.is_file():
        vector_dim = _int(_load_json(summary_path).get("vector_dim"))
    vector_dim = vector_dim or 2048
    vector_count, vector_seen = _write_filtered_csv(root / "vma_vectors_l2.csv", output_dir / "vma_vectors_l2.csv", sample_ids)
    if vector_seen != sample_ids:
        raise ValueError(f"vma_vectors_l2.csv 缺少样本：{sorted(sample_ids - vector_seen)[:5]}")
    if args.include_raw_vector and (root / "vma_vectors_raw.csv").is_file():
        _write_filtered_csv(root / "vma_vectors_raw.csv", output_dir / "vma_vectors_raw.csv", sample_ids)

    pairwise_count = 0
    if (root / "pairwise_similarity.csv").is_file():
        pairwise_count, _ = _write_filtered_csv(
            root / "pairwise_similarity.csv",
            output_dir / "pairwise_similarity.csv",
            sample_ids,
            left_field="sample_id_left",
            right_field="sample_id_right",
        )

    _write_rows(
        output_dir / "excluded_samples.csv",
        excluded,
        ["sample_id", "trial_id", "operation_label", "reason"],
    )
    _write_rows(
        output_dir / "trial_selection.csv",
        trial_summary,
        ["trial_id", "source_rows", "unique_operations", "included_samples", "selected", "reason"],
    )

    copied_files: list[str] = []
    for filename in OPTIONAL_INPUTS:
        source = root / filename
        destination = output_dir / filename
        if source.is_file() and not destination.exists() and filename not in {
            "vma_vectors_raw.csv",
            "labels.csv",
            "pairwise_similarity.csv",
        }:
            shutil.copy2(source, destination)
            copied_files.append(filename)

    summary = {
        "schema_version": "douyu.vma-dataset-core.v1",
        "source_directory_name": root.name,
        "source_directory": str(root),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "selection_rule": {
            "support_eligible": True,
            "window_quality": "complete",
            "collection_quality": "pass",
            "hash_mismatch_count": 0,
            "vector_nonzero_count": "> 0",
            "complete_trial_required": not args.allow_incomplete_trials,
            "expected_operation_count": len(expected_labels) if expected_labels else args.expected_label_count,
        },
        "included_trial_count": sum(1 for row in trial_summary if row["selected"] == "true"),
        "included_sample_count": len(sample_ids),
        "excluded_sample_count": len(excluded),
        "included_label_counts": dict(sorted(Counter(row.get("operation_label", "") for row in included).items())),
        "vector_dim": vector_dim,
        "vector_row_count": vector_count,
        "label_row_count": label_count,
        "pairwise_row_count": pairwise_count,
        "copied_metadata": copied_files,
        "raw_reports_included": False,
    }
    (output_dir / "core_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "README.md").write_text(
        "# 斗鱼鸿蒙电脑 VMA 核心子数据集\n\n"
        "本目录只包含通过质量筛选的向量、标签和审计元数据；原始 VMA 报告仍保留在 Windows 采集目录中。\n\n"
        "- `vma_vectors_l2.csv`：PCA、UMAP 和聚类的主输入。\n"
        "- `labels.csv`：样本标签。\n"
        "- `dataset_manifest.csv`：trial、操作、设备和质量字段。\n"
        "- `excluded_samples.csv`：未进入核心数据集的样本及原因。\n"
        "- `trial_selection.csv`：每个 trial 是否通过完整性筛选。\n"
        "- `core_summary.json`：本次导出摘要。\n"
        "- `trial_failures.csv`：失败 trial 的审计记录（如果存在）。\n",
        encoding="utf-8",
    )

    zip_path = args.zip_path.expanduser().resolve() if args.zip_path else output_dir.with_suffix(".zip")
    if not args.no_zip:
        if zip_path.exists():
            raise FileExistsError(f"ZIP 已存在，为避免覆盖数据而停止：{zip_path}")
        summary["zip_path"] = str(zip_path)
        (output_dir / "core_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _zip_directory(output_dir, zip_path)
    print(json.dumps({"output_dir": str(output_dir), "zip_path": str(zip_path) if not args.no_zip else None, **summary}, ensure_ascii=False, indent=2))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Windows 斗鱼采集输出根目录")
    parser.add_argument("--output-dir", type=Path, default=None, help="核心数据集输出目录；默认自动加时间戳")
    parser.add_argument("--zip-path", type=Path, default=None, help="ZIP 输出路径；默认与核心目录同名")
    parser.add_argument("--catalog", type=Path, default=None, help="可选 operation_catalog.json 路径")
    parser.add_argument("--expected-label-count", type=int, default=8, help="无 catalog 时每个 trial 期望的操作数量")
    parser.add_argument("--allow-incomplete-trials", action="store_true", help="允许只保留合格样本，不要求整个 trial 的操作完整")
    parser.add_argument("--no-raw-vector", dest="include_raw_vector", action="store_false", help="不复制 vma_vectors_raw.csv")
    parser.set_defaults(include_raw_vector=True)
    parser.add_argument("--no-zip", action="store_true", help="只生成目录，不生成 ZIP")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        export_dataset(parse_args())
    except (FileNotFoundError, FileExistsError, ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f"[douyu-core-export] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
