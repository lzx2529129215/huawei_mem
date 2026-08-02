#!/usr/bin/env python3
"""解析并独立重放 Linux L0.3A 页生命周期 ftrace 事件。"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, TextIO, Tuple

from ftrace_events import extract_event


class Action(IntEnum):
    DISCOVER = 0
    ADD_LRU = 1
    ACTIVATE = 2
    DEACTIVATE = 3
    ISOLATE = 4
    PUTBACK = 5
    RECLAIMED = 6
    FREE = 7
    MIGRATE = 8
    DOMAIN_CHANGE = 9


class State(IntEnum):
    UNKNOWN = 0
    ON_LRU_INACTIVE = 1
    ON_LRU_ACTIVE = 2
    ISOLATED = 3
    RECLAIMED = 4
    DEAD = 5


class Classification(Enum):
    VALID = "VALID"
    LATE_DISCOVERY = "LATE_DISCOVERY"
    TRACE_TRUNCATION = "TRACE_TRUNCATION"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    DUPLICATE_TERMINAL = "DUPLICATE_TERMINAL"


LATE_DISCOVERY_FLAG = 1 << 0
DUPLICATE_TERMINAL_FLAG = 1 << 2
REUSE_DETECTED_FLAG = 1 << 4

EVENT_ALIASES = {
    "myself_kswapd_page_lifecycle": "page_lifecycle",
    "myself_kswapd:page_lifecycle": "page_lifecycle",
    "myself_kswapd:myself_kswapd_page_lifecycle": "page_lifecycle",
    "page_lifecycle": "page_lifecycle",
}

REQUIRED_FIELDS = (
    "transition_seq", "action", "page_id", "lifecycle_gen", "order",
    "nr_pages", "page_type", "from_state", "to_state", "lru_class",
    "mode", "memcg_id", "nid", "request_id", "priority_seq",
    "scan_seq", "reclaim_source", "reason", "flags",
)

U64_FIELDS = {
    "transition_seq", "page_id", "memcg_id", "request_id", "priority_seq",
    "scan_seq",
}
U32_FIELDS = {"lifecycle_gen", "order", "nr_pages", "reason", "flags"}
U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1

MODE_NAMES = {0: "MEMCG", 1: "GLOBAL"}
SOURCE_NAMES = {0: "KSWAPD", 1: "DIRECT", 2: "MEMCG", 3: "UNKNOWN"}
TERMINAL_STATES = {State.RECLAIMED, State.DEAD}


@dataclass(frozen=True)
class ParseIssue:
    line_number: int
    code: str
    detail: str


@dataclass(frozen=True)
class ParsedEvent:
    fields: Dict[str, int]
    line_number: int

    @property
    def key(self) -> Tuple[int, int]:
        return self.fields["page_id"], self.fields["lifecycle_gen"]


@dataclass
class ParseResult:
    events: List[ParsedEvent]
    issues: List[ParseIssue]


@dataclass(frozen=True)
class Transition:
    transition_seq: int
    page_id: int
    lifecycle_gen: int
    action: str
    from_state: str
    to_state: str
    classification: Classification
    line_number: int
    request_id: int
    priority_seq: int
    scan_seq: int
    memcg_id: int
    nid: int

    def csv_row(self) -> Dict[str, object]:
        row = dict(self.__dict__)
        row["classification"] = self.classification.value
        return row


@dataclass
class ReplayReport:
    summary: Dict[str, object]
    transitions: List[Transition]
    parse_issues: List[ParseIssue]


def _parse_fields(payload: str) -> Dict[str, object]:
    fields: Dict[str, object] = {}
    for token in payload.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        try:
            fields[key] = int(value, 0)
        except ValueError:
            fields[key] = value
    return fields


def _validate_fields(fields: Mapping[str, object], line_number: int) -> List[ParseIssue]:
    issues: List[ParseIssue] = []
    for name in REQUIRED_FIELDS:
        if name not in fields:
            issues.append(ParseIssue(line_number, "MISSING_FIELD", name))
    if issues:
        return issues

    for name in U64_FIELDS:
        value = fields[name]
        if not isinstance(value, int) or value < 0 or value > U64_MAX:
            issues.append(ParseIssue(line_number, "INTEGER_RANGE", name))
    for name in U32_FIELDS:
        value = fields[name]
        if not isinstance(value, int) or value < 0 or value > U32_MAX:
            issues.append(ParseIssue(line_number, "INTEGER_RANGE", name))

    enum_ranges = {
        "action": set(item.value for item in Action),
        "from_state": set(item.value for item in State),
        "to_state": set(item.value for item in State),
        "page_type": {0, 1, 2},
        "lru_class": {0, 1, 2, 3, 4},
        "mode": set(MODE_NAMES),
        "reclaim_source": set(SOURCE_NAMES),
    }
    for name, accepted in enum_ranges.items():
        if fields[name] not in accepted:
            issues.append(ParseIssue(line_number, "INVALID_ENUM", name))

    if not isinstance(fields["nid"], int) or fields["nid"] < 0:
        issues.append(ParseIssue(line_number, "INVALID_VALUE", "nid"))
    if fields["page_id"] == 0 or fields["lifecycle_gen"] == 0:
        issues.append(ParseIssue(line_number, "INVALID_VALUE", "token"))
    if fields["nr_pages"] != 1 << fields["order"]:
        issues.append(ParseIssue(line_number, "INVALID_VALUE", "nr_pages/order"))

    request_id = fields["request_id"]
    priority_seq = fields["priority_seq"]
    scan_seq = fields["scan_seq"]
    source = fields["reclaim_source"]
    if request_id == 0:
        if priority_seq != 0 or scan_seq != 0 or source != 3:
            issues.append(ParseIssue(line_number, "INVALID_CONTEXT", "ambient_ids"))
    elif priority_seq == 0 or scan_seq == 0 or source == 3:
        issues.append(ParseIssue(line_number, "INVALID_CONTEXT", "reclaim_ids"))
    return issues


def parse_trace_text(text: str) -> ParseResult:
    events: List[ParsedEvent] = []
    issues: List[ParseIssue] = []
    seen_sequences = set()
    previous_sequence: Optional[int] = None

    for line_number, line in enumerate(text.splitlines(), 1):
        extracted = extract_event(line, EVENT_ALIASES)
        if not extracted:
            continue
        _, payload = extracted
        raw_fields = _parse_fields(payload)
        line_issues = _validate_fields(raw_fields, line_number)
        if line_issues:
            issues.extend(line_issues)
            continue
        fields = {name: int(raw_fields[name]) for name in REQUIRED_FIELDS}
        sequence = fields["transition_seq"]
        if sequence in seen_sequences:
            issues.append(ParseIssue(line_number, "DUPLICATE_SEQUENCE",
                                     str(sequence)))
            continue
        if previous_sequence is not None and sequence <= previous_sequence:
            issues.append(ParseIssue(line_number, "NON_MONOTONIC_SEQUENCE",
                                     f"{previous_sequence}->{sequence}"))
            continue
        seen_sequences.add(sequence)
        previous_sequence = sequence
        events.append(ParsedEvent(fields, line_number))
    return ParseResult(events, issues)


def _expected_transition(action: Action, current: State,
                         target: State) -> bool:
    if action in (Action.DISCOVER, Action.ADD_LRU):
        return current == State.UNKNOWN and target in (
            State.ON_LRU_INACTIVE, State.ON_LRU_ACTIVE)
    if action == Action.ACTIVATE:
        return current == State.ON_LRU_INACTIVE and target == State.ON_LRU_ACTIVE
    if action == Action.DEACTIVATE:
        return current == State.ON_LRU_ACTIVE and target == State.ON_LRU_INACTIVE
    if action == Action.ISOLATE:
        return current in (State.ON_LRU_INACTIVE, State.ON_LRU_ACTIVE) and \
            target == State.ISOLATED
    if action == Action.PUTBACK:
        return current == State.ISOLATED and target in (
            State.ON_LRU_INACTIVE, State.ON_LRU_ACTIVE)
    if action == Action.RECLAIMED:
        return current == State.ISOLATED and target == State.RECLAIMED
    if action in (Action.FREE, Action.MIGRATE):
        return current not in TERMINAL_STATES and current != State.UNKNOWN and \
            target == State.DEAD
    if action == Action.DOMAIN_CHANGE:
        return current != State.UNKNOWN and target == current
    return False


def _late_transition_allowed(action: Action, reported_from: State,
                             target: State) -> bool:
    if reported_from != State.UNKNOWN:
        return False
    if action in (Action.DISCOVER, Action.ADD_LRU):
        return target in (State.ON_LRU_INACTIVE, State.ON_LRU_ACTIVE)
    if action == Action.ACTIVATE:
        return target == State.ON_LRU_ACTIVE
    if action == Action.DEACTIVATE:
        return target == State.ON_LRU_INACTIVE
    return action == Action.ISOLATE and target == State.ISOLATED


def _counter_dict(counter: Counter) -> Dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=str)}


def replay_events(events: Iterable[ParsedEvent],
                  parse_issues: Optional[List[ParseIssue]] = None) -> ReplayReport:
    states: Dict[Tuple[int, int], State] = {}
    isolate_context: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    lifecycles = set()
    terminal_lifecycles = set()
    transitions: List[Transition] = []
    counts = Counter()
    per_event = Counter()
    per_state = Counter()
    per_mode = Counter()
    per_memcg = Counter()
    per_nid = Counter()
    per_source = Counter()

    event_list = list(events)
    for event in event_list:
        fields = event.fields
        key = event.key
        action = Action(fields["action"])
        reported_from = State(fields["from_state"])
        target = State(fields["to_state"])
        flags = fields["flags"]
        current = states.get(key)
        classification = Classification.VALID
        valid = False

        lifecycles.add(key)
        per_event[action.name] += 1
        per_state[target.name] += 1
        per_mode[MODE_NAMES[fields["mode"]]] += 1
        per_memcg[fields["memcg_id"]] += 1
        per_nid[fields["nid"]] += 1
        per_source[SOURCE_NAMES[fields["reclaim_source"]]] += 1
        if flags & REUSE_DETECTED_FLAG:
            counts["reuse_detected"] += 1

        if current in TERMINAL_STATES or flags & DUPLICATE_TERMINAL_FLAG:
            if action in (Action.RECLAIMED, Action.FREE, Action.MIGRATE):
                classification = Classification.DUPLICATE_TERMINAL
                counts["duplicate_terminal"] += 1
            else:
                classification = Classification.INVALID_TRANSITION
                counts["invalid_transition"] += 1
        elif current is None:
            if (flags & LATE_DISCOVERY_FLAG and
                    _late_transition_allowed(action, reported_from, target)):
                classification = Classification.LATE_DISCOVERY
                counts["late_discovery"] += 1
                valid = True
            elif (reported_from == State.UNKNOWN and
                  _expected_transition(action, State.UNKNOWN, target)):
                valid = True
            else:
                classification = Classification.TRACE_TRUNCATION
                counts["trace_truncation"] += 1
                valid = True
        else:
            context_matches = True
            if action in (Action.PUTBACK, Action.RECLAIMED):
                expected_context = isolate_context.get(key)
                actual_context = (fields["request_id"], fields["priority_seq"],
                                  fields["scan_seq"])
                context_matches = expected_context is None or \
                    expected_context == actual_context
            valid = (reported_from == current and
                     _expected_transition(action, current, target) and
                     context_matches)
            if not valid:
                classification = Classification.INVALID_TRANSITION
                counts["invalid_transition"] += 1

        if action == Action.PUTBACK and current != State.ISOLATED:
            counts["putback_without_isolate"] += 1
            counts["missing_isolate"] += 1
        if action == Action.RECLAIMED and current != State.ISOLATED:
            counts["reclaimed_without_isolate"] += 1
            counts["missing_isolate"] += 1

        if valid:
            states[key] = target
            if action == Action.ISOLATE:
                isolate_context[key] = (
                    fields["request_id"], fields["priority_seq"],
                    fields["scan_seq"])
            elif action in (Action.PUTBACK, Action.RECLAIMED,
                            Action.FREE, Action.MIGRATE):
                isolate_context.pop(key, None)
            if target in TERMINAL_STATES:
                terminal_lifecycles.add(key)

        transitions.append(Transition(
            transition_seq=fields["transition_seq"],
            page_id=fields["page_id"],
            lifecycle_gen=fields["lifecycle_gen"],
            action=action.name,
            from_state=reported_from.name,
            to_state=target.name,
            classification=classification,
            line_number=event.line_number,
            request_id=fields["request_id"],
            priority_seq=fields["priority_seq"],
            scan_seq=fields["scan_seq"],
            memcg_id=fields["memcg_id"],
            nid=fields["nid"],
        ))

    active_end = sum(state not in TERMINAL_STATES and state != State.UNKNOWN
                     for state in states.values())
    summary: Dict[str, object] = {
        "total_events": len(event_list),
        "unique_lifecycles": len(lifecycles),
        "active_entries_at_end": active_end,
        "terminal_entries": len(terminal_lifecycles),
        "late_discovery": counts["late_discovery"],
        "trace_truncation": counts["trace_truncation"],
        "invalid_transition": counts["invalid_transition"],
        "duplicate_terminal": counts["duplicate_terminal"],
        "missing_isolate": counts["missing_isolate"],
        "putback_without_isolate": counts["putback_without_isolate"],
        "reclaimed_without_isolate": counts["reclaimed_without_isolate"],
        "reuse_detected": counts["reuse_detected"],
        "parse_issues": len(parse_issues or []),
        "per_event_count": _counter_dict(per_event),
        "per_state_count": _counter_dict(per_state),
        "per_mode_count": _counter_dict(per_mode),
        "per_memcg_count": _counter_dict(per_memcg),
        "per_nid_count": _counter_dict(per_nid),
        "per_reclaim_source_count": _counter_dict(per_source),
    }
    return ReplayReport(summary, transitions, list(parse_issues or []))


def parse_and_replay_text(text: str) -> ReplayReport:
    parsed = parse_trace_text(text)
    return replay_events(parsed.events, parsed.issues)


def parse_and_replay(path: Path) -> ReplayReport:
    return parse_and_replay_text(path.read_text(encoding="utf-8",
                                                errors="replace"))


def write_transitions_csv(transitions: Iterable[Transition], output: TextIO) -> None:
    fieldnames = list(Transition.__dataclass_fields__)
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for transition in transitions:
        writer.writerow(transition.csv_row())


def format_text_summary(summary: Mapping[str, object]) -> str:
    lines = []
    for key, value in summary.items():
        if isinstance(value, dict):
            rendered = ",".join(f"{name}:{count}"
                                for name, count in value.items())
            lines.append(f"{key}={rendered}")
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--json", action="store_true",
                        help="将 summary 以 JSON 写到标准输出")
    parser.add_argument("--csv", type=Path, metavar="PATH",
                        help="将逐 transition 记录写入 CSV")
    args = parser.parse_args()

    report = parse_and_replay(args.trace)
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", encoding="utf-8", newline="") as output:
            write_transitions_csv(report.transitions, output)
    if args.json:
        print(json.dumps(report.summary, ensure_ascii=False, sort_keys=True))
    else:
        print(format_text_summary(report.summary), end="")
    if report.parse_issues:
        return 1
    return 2 if report.summary["invalid_transition"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
