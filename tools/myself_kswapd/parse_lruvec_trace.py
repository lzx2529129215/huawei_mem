#!/usr/bin/env python3
"""解析 Linux L0.2 request 与 classic-LRU lruvec trace 文本。"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List

from ftrace_events import EVENT_ALIASES, extract_event


class ErrorCode(Enum):
    MALFORMED_LINE = "malformed_line"
    MISSING_FIELD = "missing_field"
    INVALID_MODE = "invalid_mode"
    INVALID_SOURCE = "invalid_source"
    INVALID_STAGE = "invalid_stage"
    INVALID_SCOPE = "invalid_scope"
    INTEGER_OVERFLOW = "integer_overflow"
    INVALID_VALUE = "invalid_value"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    PROVISIONAL_GAP = "provisional_gap"


@dataclass(frozen=True)
class ParseIssue:
    code: ErrorCode
    line_number: int
    detail: str


@dataclass(frozen=True)
class ParsedEvent:
    event: str
    fields: Dict[str, int]
    line_number: int


@dataclass
class ParseResult:
    events: List[ParsedEvent]
    errors: List[ParseIssue]


LRUVEC_EVENT_ALIASES = {
    alias: canonical for alias, canonical in EVENT_ALIASES.items()
    if canonical in {"request_begin", "lruvec_snapshot"}
}

REQUEST_FIELDS = ("request_id",)
SNAPSHOT_FIELDS = (
    "snapshot_seq", "timestamp_ns", "request_id", "priority_seq",
    "scan_seq", "mode", "memcg_id", "nid", "memcg_css_id",
    "reclaim_source", "stage", "consistency", "priority", "lru_scope",
    "isolated_scope", "inactive_anon", "active_anon", "inactive_file",
    "active_file", "isolated_anon", "isolated_file", "scanned_total",
    "reclaimed_total", "field_valid_mask", "validation_flags",
)
U64_FIELDS = {
    "snapshot_seq", "timestamp_ns", "request_id", "priority_seq",
    "scan_seq", "memcg_id", "field_valid_mask", "validation_flags",
    "inactive_anon", "active_anon", "inactive_file", "active_file",
    "isolated_anon", "isolated_file", "scanned_total", "reclaimed_total",
}
U32_FIELDS = {"memcg_css_id"}
U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1


def _parse_fields(text: str) -> Dict[str, int]:
    fields: Dict[str, int] = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        try:
            fields[key] = int(value, 0)
        except ValueError:
            fields[key] = value  # type: ignore[assignment]
    return fields


def _issue(code: ErrorCode, event: ParsedEvent, detail: str) -> ParseIssue:
    return ParseIssue(code, event.line_number, detail)


def _validate_request(event: ParsedEvent, errors: List[ParseIssue]) -> bool:
    valid = True
    for field in REQUEST_FIELDS:
        if field not in event.fields:
            errors.append(_issue(ErrorCode.MISSING_FIELD, event, field))
            valid = False
    request_id = event.fields.get("request_id")
    if not isinstance(request_id, int) or request_id <= 0:
        errors.append(_issue(ErrorCode.INVALID_VALUE, event, "request_id"))
        valid = False
    return valid


def _validate_snapshot(event: ParsedEvent, errors: List[ParseIssue]) -> bool:
    fields = event.fields
    valid = True
    for field in SNAPSHOT_FIELDS:
        if field not in fields:
            errors.append(_issue(ErrorCode.MISSING_FIELD, event, field))
            valid = False
    if not valid:
        return False

    for field in U64_FIELDS:
        value = fields[field]
        if not isinstance(value, int) or value < 0 or value > U64_MAX:
            errors.append(_issue(ErrorCode.INTEGER_OVERFLOW, event, field))
            valid = False
    for field in U32_FIELDS:
        value = fields[field]
        if not isinstance(value, int) or value < 0 or value > U32_MAX:
            errors.append(_issue(ErrorCode.INTEGER_OVERFLOW, event, field))
            valid = False
    if not isinstance(fields["nid"], int) or fields["nid"] < 0:
        errors.append(_issue(ErrorCode.INVALID_VALUE, event, "nid"))
        valid = False
    if not isinstance(fields["priority"], int):
        errors.append(_issue(ErrorCode.INVALID_VALUE, event, "priority"))
        valid = False

    if fields["mode"] not in (0, 1):
        errors.append(_issue(ErrorCode.INVALID_MODE, event, "mode"))
        valid = False
    if fields["reclaim_source"] not in (0, 1, 2, 3):
        errors.append(_issue(ErrorCode.INVALID_SOURCE, event, "reclaim_source"))
        valid = False
    if fields["stage"] not in (0, 1, 2, 3):
        errors.append(_issue(ErrorCode.INVALID_STAGE, event, "stage"))
        valid = False
    if fields["lru_scope"] not in (1, 2) or fields["isolated_scope"] not in (1, 2):
        errors.append(_issue(ErrorCode.INVALID_SCOPE, event, "scope"))
        valid = False
    elif fields["mode"] == 0 and (
            fields["lru_scope"] != 1 or fields["isolated_scope"] != 2):
        errors.append(_issue(ErrorCode.INVALID_SCOPE, event, "memcg_scope"))
        valid = False
    elif fields["mode"] == 1 and (
            fields["lru_scope"] != 2 or fields["isolated_scope"] != 2):
        errors.append(_issue(ErrorCode.INVALID_SCOPE, event, "global_scope"))
        valid = False

    stage = fields["stage"]
    if stage in (0, 1):
        if (fields["request_id"] <= 0 or fields["priority_seq"] <= 0 or
                fields["scan_seq"] <= 0):
            errors.append(_issue(ErrorCode.INVALID_VALUE, event, "scan_ids"))
            valid = False
    elif (fields["request_id"] != 0 or fields["priority_seq"] != 0 or
          fields["scan_seq"] != 0):
        errors.append(_issue(ErrorCode.INVALID_VALUE, event, "ambient_ids"))
        valid = False
    return valid


def _validate_sequences(snapshots: Iterable[ParsedEvent],
                        errors: List[ParseIssue]) -> None:
    ordered = sorted(snapshots, key=lambda event: event.fields["snapshot_seq"])
    seen = set()
    previous = None
    for event in ordered:
        fields = event.fields
        key = (fields["request_id"], fields["priority_seq"],
               fields["scan_seq"], fields["stage"])
        if key in seen:
            errors.append(_issue(ErrorCode.DUPLICATE_SEQUENCE, event, str(key)))
        seen.add(key)
        sequence = fields["snapshot_seq"]
        if previous is not None and sequence != previous + 1:
            errors.append(_issue(ErrorCode.PROVISIONAL_GAP, event,
                                 f"{previous}->{sequence}"))
        previous = sequence


def parse_trace_text(text: str) -> ParseResult:
    events: List[ParsedEvent] = []
    errors: List[ParseIssue] = []
    snapshots: List[ParsedEvent] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        extracted = extract_event(line, LRUVEC_EVENT_ALIASES)
        if not extracted:
            continue
        event_name, payload = extracted
        event = ParsedEvent(event_name, _parse_fields(payload), line_number)
        if event.event == "request_begin":
            if _validate_request(event, errors):
                events.append(event)
        elif _validate_snapshot(event, errors):
            snapshots.append(event)

    _validate_sequences(snapshots, errors)
    events.extend(sorted(snapshots, key=lambda event: event.fields["snapshot_seq"]))
    return ParseResult(events, errors)


def parse_trace(path: Path) -> ParseResult:
    return parse_trace_text(path.read_text(encoding="utf-8", errors="replace"))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    result = parse_trace(args.trace)
    for issue in result.errors:
        print(f"{issue.line_number}: {issue.code.value}: {issue.detail}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
