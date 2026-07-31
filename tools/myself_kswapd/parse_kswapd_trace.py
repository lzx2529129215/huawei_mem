#!/usr/bin/env python3
"""解析 myself_kswapd trace-cmd 文本并生成 CSV。"""

import argparse
import csv
import sys
from pathlib import Path

from ftrace_events import EVENT_ALIASES, extract_event

# lzx--------------------------- 解析器核心 ---------------------------
REQUEST_EVENT_ALIASES = {
    alias: canonical for alias, canonical in EVENT_ALIASES.items()
    if canonical in {"request_begin", "priority_round", "request_end"}
}
EXIT_REASONS = {
    0: "ALREADY_BALANCED",
    1: "BALANCED",
    2: "KTHREAD_STOP",
    3: "FROZEN",
    4: "BOOST_NO_PROGRESS",
    5: "PRIORITY_EXHAUSTED",
    6: "UNKNOWN",
}

REQUEST_FIELDS = [
    "request_id", "nid", "requested_order", "highest_zoneidx", "gfp_mask",
    "initial_boost_pages", "boosted", "final_order", "final_priority",
    "final_balanced", "boost_active", "stop_requested", "was_frozen",
    "order_dropped", "pass_count", "round_count", "total_main_scanned",
    "total_soft_scanned", "total_scanned", "total_main_reclaimed",
    "total_soft_reclaimed", "total_reclaimed", "boost_restart_count",
    "cache_trim_restart_count", "exit_reason", "elapsed_ns", "validation_flags",
    "complete", "completeness_errors", "overall_efficiency",
]
ROUND_FIELDS = [
    "request_id", "pass_seq", "round_seq", "nid", "order", "priority",
    "reclaim_idx", "nr_to_reclaim", "main_scanned", "soft_scanned",
    "total_scanned", "main_reclaimed", "soft_reclaimed", "reclaimed_delta",
    "balanced_before", "boost_active", "raise_priority",
    "priority_decremented", "may_swap", "may_unmap", "may_writepage",
    "may_deactivate", "stop_requested", "was_frozen", "boost_no_progress",
    "elapsed_ns", "validation_flags",
]


def parse_value(value):
    """按 tracepoint 的无符号/布尔打印形式解析字段。"""
    try:
        return int(value, 0)
    except ValueError:
        return value


def parse_fields(text):
    """解析 key=value 序列，忽略 trace-cmd 可能附加的空白。"""
    fields = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = parse_value(value)
    return fields


def read_events(path):
    """读取三类事件，保留原始行号用于诊断。"""
    events = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            event = extract_event(line, REQUEST_EVENT_ALIASES)
            if event:
                event_name, payload = event
                fields = parse_fields(payload)
                fields["_line"] = line_number
                events.append((event_name, fields))
    return events


def number(record, key, default=0):
    """读取数值字段，缺失值统一转换为默认值。"""
    value = record.get(key, default)
    return value if isinstance(value, int) else default


def validate_request(request):
    """校验请求边界、round 序列和聚合总量。"""
    errors = list(request["errors"])
    rounds = request["rounds"]
    begin = request.get("begin")
    end = request.get("end")
    if begin is None:
        errors.append("missing_begin")
    if end is None:
        errors.append("missing_end")
    expected_round = 0
    for round_record in rounds:
        if number(round_record, "round_seq") != expected_round:
            errors.append("round_seq_noncontinuous")
            expected_round = number(round_record, "round_seq")
        expected_round += 1
        if number(round_record, "reclaimed_delta") != (
                number(round_record, "main_reclaimed") +
                number(round_record, "soft_reclaimed")):
            errors.append("round_reclaim_total_mismatch")
        if number(round_record, "total_scanned") != (
                number(round_record, "main_scanned") +
                number(round_record, "soft_scanned")):
            errors.append("round_scan_total_mismatch")
        if number(round_record, "validation_flags"):
            errors.append("round_validation_flags")
    if end is not None:
        if number(end, "round_count") != len(rounds):
            errors.append("round_count_mismatch")
        if number(end, "pass_count") != (number(end, "boost_restart_count") +
                                          number(end, "cache_trim_restart_count") + 1):
            errors.append("pass_count_mismatch")
        if number(end, "total_scanned") != (
                number(end, "total_main_scanned") +
                number(end, "total_soft_scanned")):
            errors.append("request_scan_total_mismatch")
        if number(end, "total_reclaimed") != (
                number(end, "total_main_reclaimed") +
                number(end, "total_soft_reclaimed")):
            errors.append("request_reclaim_total_mismatch")
        if number(end, "validation_flags"):
            errors.append("request_validation_flags")
    request["errors"] = list(dict.fromkeys(errors))
    request["complete"] = not request["errors"]


def build_requests(events):
    """按 request_id 组织事件，并显式保留不完整请求。"""
    requests = {}
    anonymous = []
    for event_name, fields in events:
        request_id = fields.get("request_id")
        if not isinstance(request_id, int):
            anonymous.append((event_name, fields.get("_line", 0)))
            continue
        request = requests.setdefault(request_id, {
            "begin": None, "end": None, "rounds": [], "errors": [],
        })
        if event_name == "request_begin":
            if request["begin"] is not None:
                request["errors"].append("duplicate_begin")
            request["begin"] = fields
        elif event_name == "priority_round":
            request["rounds"].append(fields)
        elif event_name == "request_end":
            if request["end"] is not None:
                request["errors"].append("duplicate_end")
            request["end"] = fields
    if anonymous:
        requests[-1] = {"begin": None, "end": None, "rounds": [],
                        "errors": ["missing_request_id"]}
    for request in requests.values():
        validate_request(request)
    return requests


def row_for_request(request_id, request):
    """拼接请求 CSV 行；不完整请求不参与效率统计。"""
    row = {field: "" for field in REQUEST_FIELDS}
    begin = request["begin"] or {}
    end = request["end"] or {}
    for field in REQUEST_FIELDS:
        if field in begin:
            row[field] = begin[field]
        if field in end:
            row[field] = end[field]
    row["request_id"] = request_id
    row["exit_reason"] = EXIT_REASONS.get(number(end, "exit_reason"), "UNKNOWN")
    row["complete"] = int(request["complete"])
    row["completeness_errors"] = ";".join(request["errors"])
    scanned = number(end, "total_scanned")
    row["overall_efficiency"] = (
        number(end, "total_reclaimed") / scanned if request["complete"] and scanned else ""
    )
    return row


def write_csv(path, fields, rows):
    """以稳定列顺序写出 CSV。"""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def convert(input_path, output_dir):
    """完成 trace 文本到三个 CSV 的转换并返回不完整请求数。"""
    events = read_events(input_path)
    requests = build_requests(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    request_rows = [row_for_request(request_id, request)
                    for request_id, request in sorted(requests.items())]
    round_rows = []
    efficiency_rows = []
    for request_id, request in sorted(requests.items()):
        for round_record in request["rounds"]:
            row = {field: round_record.get(field, "") for field in ROUND_FIELDS}
            round_rows.append(row)
        if request["complete"]:
            end = request["end"] or {}
            scanned = number(end, "total_scanned")
            if scanned:
                efficiency_rows.append({
                    "request_id": request_id,
                    "reclaimed_total": number(end, "total_reclaimed"),
                    "total_scanned": scanned,
                    "overall_efficiency": number(end, "total_reclaimed") / scanned,
                })
    write_csv(output_dir / "kswapd_requests.csv", REQUEST_FIELDS, request_rows)
    write_csv(output_dir / "kswapd_rounds.csv", ROUND_FIELDS, round_rows)
    write_csv(output_dir / "kswapd_efficiency.csv",
              ["request_id", "reclaimed_total", "total_scanned", "overall_efficiency"],
              efficiency_rows)
    return sum(not request["complete"] for request in requests.values()), len(events)


def main(argv=None):
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="解析 myself_kswapd trace-cmd 输出")
    parser.add_argument("input", type=Path, help="trace-cmd report 文本或保存的 trace 文件")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="CSV 输出目录，默认当前目录")
    args = parser.parse_args(argv)
    incomplete, event_count = convert(args.input, args.output_dir)
    print(f"events={event_count} incomplete_requests={incomplete}")
    return 0 if incomplete == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
# lzx--------------------------- 解析器核心结束 ---------------------------
