#!/usr/bin/env python3
"""Build one 56-dimensional workload vector from one operation's PID reports.

The input reports are the Markdown files emitted by ``mem_analyze-v6`` with
``--with-vma``.  All reports passed to one invocation must belong to the same
operation; their additive fields are summed across PID and their ratio fields
are recomputed from the sums.  The seven logical segments and eight fields per
segment intentionally match the workload-vector package supplied with the
experiment.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


LOGICAL_SEGMENTS: "OrderedDict[str, tuple[str, ...]]" = OrderedDict(
    [
        ("runtime_heap", ("ark ts heap",)),
        ("native_heap", ("native heap",)),
        ("anon_other", ("AnonPage other",)),
        ("stack", ("stack",)),
        ("file_data", ("FilePage other", ".hap", ".ttf")),
        ("shared_lib", (".so",)),
        ("graphics_device", ("GL", "Graph", "dev")),
    ]
)

FEATURE_FIELDS = (
    "vma_count",
    "size_kib",
    "rss_kib",
    "pss_kib",
    "referenced_kib",
    "swap_kib",
    "referenced_size_ratio",
    "referenced_rss_ratio",
)
FEATURE_ORDER = tuple(
    f"{segment}__{field}" for segment in LOGICAL_SEGMENTS for field in FEATURE_FIELDS
)
ADDITIVE_FIELDS = ("vma_count", "size_kib", "rss_kib", "pss_kib", "referenced_kib", "swap_kib")


class ReportFormatError(ValueError):
    """A report does not satisfy the v6 Markdown contract."""


@dataclass
class SegmentMetrics:
    vma_count: int = 0
    size_kib: int = 0
    rss_kib: int = 0
    pss_kib: int = 0
    referenced_kib: int = 0
    swap_kib: int = 0

    def add(self, other: "SegmentMetrics") -> None:
        for field in ADDITIVE_FIELDS:
            setattr(self, field, getattr(self, field) + getattr(other, field))

    def to_dict(self) -> dict[str, int | float]:
        referenced_size_ratio = self.referenced_kib / self.size_kib if self.size_kib else 0.0
        referenced_rss_ratio = self.referenced_kib / self.rss_kib if self.rss_kib else 0.0
        return {
            "vma_count": self.vma_count,
            "size_kib": self.size_kib,
            "rss_kib": self.rss_kib,
            "pss_kib": self.pss_kib,
            "referenced_kib": self.referenced_kib,
            "swap_kib": self.swap_kib,
            "referenced_size_ratio": referenced_size_ratio,
            "referenced_rss_ratio": referenced_rss_ratio,
        }


def _cell(text: str) -> str:
    return text.strip().strip("`").strip()


def _cells(line: str) -> list[str]:
    return [_cell(item) for item in line.strip().strip("|").split("|")]


def _integer(text: str, field: str) -> int:
    match = re.search(r"-?\d[\d,]*", text)
    if not match:
        raise ReportFormatError(f"无法解析 {field}: {text!r}")
    return int(match.group(0).replace(",", ""))


def _kib(text: str, field: str) -> int:
    match = re.search(r"(-?\d[\d,]*)\s*KiB", text, re.IGNORECASE)
    if not match:
        raise ReportFormatError(f"无法解析 {field} KiB: {text!r}")
    return int(match.group(1).replace(",", ""))


def _metadata(lines: list[str], source: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        if line.startswith("## Referenced 段汇总"):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) == 2 and cells[0] not in {"项目", "---"} and set(cells[0]) != {"-"}:
            result[cells[0]] = cells[1]
    required = ["PID", "进程名", "可执行文件", "页大小", "VMA 数", "Size", "Rss", "Pss", "Referenced", "Swap"]
    missing = [field for field in required if field not in result]
    if missing:
        raise ReportFormatError(f"{source}: 缺少元数据字段 {missing}")
    return result


def _segments(lines: list[str], source: Path) -> dict[str, SegmentMetrics]:
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("## Referenced 段汇总"))
    except StopIteration as exc:
        raise ReportFormatError(f"{source}: 缺少 Referenced 段汇总") from exc
    table: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            table.append(line)
    if len(table) < 3:
        raise ReportFormatError(f"{source}: Referenced 段表为空")
    expected = ["一级段", "VMA 数", "Size", "Rss", "Pss", "Referenced", "Swap", "Referenced/Size", "Referenced/Rss"]
    if _cells(table[0]) != expected:
        raise ReportFormatError(f"{source}: 段表头不匹配: {_cells(table[0])}")
    result: dict[str, SegmentMetrics] = {}
    for line in table[2:]:
        cells = _cells(line)
        if len(cells) != len(expected):
            raise ReportFormatError(f"{source}: 段表行格式错误: {line}")
        name = cells[0]
        if not name:
            continue
        if name in result:
            raise ReportFormatError(f"{source}: 重复一级段 {name!r}")
        result[name] = SegmentMetrics(
            vma_count=_integer(cells[1], "VMA 数"),
            size_kib=_kib(cells[2], "Size"),
            rss_kib=_kib(cells[3], "Rss"),
            pss_kib=_kib(cells[4], "Pss"),
            referenced_kib=_kib(cells[5], "Referenced"),
            swap_kib=_kib(cells[6], "Swap"),
        )
    return result


def parse_report(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    meta = _metadata(lines, path)
    segments = _segments(lines, path)
    return {
        "source_file": str(path.resolve()),
        "pid": str(_integer(meta["PID"], "PID")),
        "process_name": _cell(meta["进程名"]),
        "executable": _cell(meta["可执行文件"]),
        "page_size_bytes": _integer(meta["页大小"], "页大小"),
        "vma_count": _integer(meta["VMA 数"], "VMA 数"),
        "size_kib": _kib(meta["Size"], "Size"),
        "rss_kib": _kib(meta["Rss"], "Rss"),
        "pss_kib": _kib(meta["Pss"], "Pss"),
        "referenced_kib": _kib(meta["Referenced"], "Referenced"),
        "swap_kib": _kib(meta["Swap"], "Swap"),
        "raw_segments": segments,
    }


def build_vector(reports: Iterable[dict[str, object]], *, allow_duplicate_pid: bool = False) -> dict[str, object]:
    report_list = list(reports)
    if not report_list:
        raise ReportFormatError("至少需要一份 PID 报告")
    pids = [str(item["pid"]) for item in report_list]
    if not allow_duplicate_pid and len(pids) != len(set(pids)):
        duplicates = sorted({pid for pid in pids if pids.count(pid) > 1})
        raise ReportFormatError(f"同一操作中出现重复 PID，拒绝重复计数: {duplicates}")
    page_sizes = {int(item["page_size_bytes"]) for item in report_list}
    if len(page_sizes) != 1:
        raise ReportFormatError(f"输入报告页大小不一致: {sorted(page_sizes)}")

    logical = {name: SegmentMetrics() for name in LOGICAL_SEGMENTS}
    excluded: dict[str, SegmentMetrics] = defaultdict(SegmentMetrics)
    overall = SegmentMetrics()
    raw_to_logical = {raw: logical_name for logical_name, raws in LOGICAL_SEGMENTS.items() for raw in raws}

    for report in report_list:
        overall.add(
            SegmentMetrics(
                vma_count=int(report["vma_count"]),
                size_kib=int(report["size_kib"]),
                rss_kib=int(report["rss_kib"]),
                pss_kib=int(report["pss_kib"]),
                referenced_kib=int(report["referenced_kib"]),
                swap_kib=int(report["swap_kib"]),
            )
        )
        for raw_name, metrics in report["raw_segments"].items():
            destination = logical.get(raw_to_logical.get(raw_name, ""))
            if destination is None:
                excluded[raw_name].add(metrics)
            else:
                destination.add(metrics)

    raw_vector: OrderedDict[str, int | float] = OrderedDict()
    for segment_name in LOGICAL_SEGMENTS:
        for field, value in logical[segment_name].to_dict().items():
            raw_vector[f"{segment_name}__{field}"] = value
    log1p_vector: OrderedDict[str, float] = OrderedDict()
    for name, value in raw_vector.items():
        if name.endswith("__referenced_size_ratio") or name.endswith("__referenced_rss_ratio"):
            log1p_vector[name] = float(value)
        else:
            numeric = float(value)
            log1p_vector[name] = math.copysign(math.log1p(abs(numeric)), numeric)
    return {
        "reports": report_list,
        "feature_order": list(FEATURE_ORDER),
        "feature_dimension": len(FEATURE_ORDER),
        "raw_vector": raw_vector,
        "log1p_vector": log1p_vector,
        "logical_segments": {name: metrics.to_dict() for name, metrics in logical.items()},
        "excluded_segments": {name: metrics.to_dict() for name, metrics in excluded.items()},
        "overall_report_totals": overall.to_dict(),
        "field_semantics": {
            "vma_count": "操作后绝对值",
            "size_kib": "操作后绝对快照，不是增量",
            "rss_kib": "操作后绝对快照，不是增量",
            "pss_kib": "操作后绝对快照，不是增量",
            "referenced_kib": "clear_refs 后观察窗口内访问过的驻留页规模",
            "swap_kib": "操作后绝对快照，不是增量",
            "referenced_size_ratio": "聚合 Referenced / 聚合 Size",
            "referenced_rss_ratio": "聚合 Referenced / 聚合 RSS",
        },
    }


def _write_one_row(path: Path, row: Mapping[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _json_report(report: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in report.items()
        if key != "raw_segments"
    } | {
        "raw_segments": {
            name: metrics.to_dict() for name, metrics in report["raw_segments"].items()
        }
    }


def write_sample(output_dir: Path, workload_id: str, report_paths: list[Path]) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = build_vector([parse_report(path) for path in report_paths])
    raw_path = output_dir / "workload_vector_raw_56d.csv"
    log1p_path = output_dir / "workload_vector_log1p_56d.csv"
    json_path = output_dir / "workload_vector.json"
    _write_one_row(raw_path, {"workload_id": workload_id, **result["raw_vector"]})
    _write_one_row(log1p_path, {"workload_id": workload_id, **result["log1p_vector"]})
    payload = {
        "schema_version": 1,
        "workload_id": workload_id,
        "sample_semantics": "one operation-level sample aggregated from all input process reports",
        **{key: value for key, value in result.items() if key != "reports"},
        "input_reports": [_json_report(report) for report in result["reports"]],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"raw_csv": str(raw_path), "log1p_csv": str(log1p_path), "json": str(json_path), **result}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--workload-id", default="WORKLOAD_SAMPLE")
    parser.add_argument("--output-dir", type=Path, default=Path("workload_vector_output"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = write_sample(args.output_dir, args.workload_id, args.reports)
        print(json.dumps({
            "status": "PASS",
            "workload_id": args.workload_id,
            "input_report_count": len(args.reports),
            "feature_dimension": result["feature_dimension"],
            "output_dir": str(args.output_dir.resolve()),
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ReportFormatError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
