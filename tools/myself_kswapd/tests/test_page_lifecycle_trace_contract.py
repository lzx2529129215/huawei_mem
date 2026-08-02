#!/usr/bin/env python3
"""检查 L0.3A trace 字段、producer 参数和 L0.2 文本 ABI。"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from test_trace_event_arg_limits import events, parenthesized


L02_EVENTS = (
    "myself_kswapd_request_begin",
    "myself_kswapd_priority_round",
    "myself_kswapd_request_end",
    "lruvec_snapshot",
)
PAGE_EVENT = "myself_kswapd_page_lifecycle"
PAGE_FIELDS = {
    "transition_seq", "action", "page_id", "lifecycle_gen", "order",
    "nr_pages", "page_type", "from_state", "to_state", "lru_class",
    "mode", "memcg_id", "nid", "request_id", "priority_seq", "scan_seq",
    "reclaim_source", "reason", "flags",
}


def event_blocks(text: str) -> dict[str, str]:
    blocks = {}
    for match in re.finditer(r"\bTRACE_EVENT\((\w+),", text):
        open_index = text.index("(", match.start())
        blocks[match.group(1)] = parenthesized(text, open_index)
    return blocks


def field_names(block: str) -> set[str]:
    return set(re.findall(r"__field\([^,]+,\s*(\w+)\s*\)", block))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header", type=pathlib.Path)
    parser.add_argument("--baseline", type=pathlib.Path)
    args = parser.parse_args()

    text = args.header.read_text(encoding="utf-8")
    blocks = event_blocks(text)
    failures = []
    parsed_events = {name: (proto, event_args)
                     for name, proto, event_args in events(text)}
    if PAGE_EVENT not in blocks:
        failures.append(f"missing TRACE_EVENT({PAGE_EVENT})")
    else:
        proto, event_args = parsed_events[PAGE_EVENT]
        if len(proto) > 12:
            failures.append(f"page event producer args={len(proto)} > 12")
        if len(proto) != 1 or event_args != ["record"]:
            failures.append("page event must use one record pointer producer arg")
        missing = PAGE_FIELDS - field_names(blocks[PAGE_EVENT])
        if missing:
            failures.append("missing page fields: " + ",".join(sorted(missing)))
        for field in PAGE_FIELDS:
            if f"{field}=" not in blocks[PAGE_EVENT]:
                failures.append(f"TP_printk missing {field}")

    if args.baseline:
        baseline = event_blocks(args.baseline.read_text(encoding="utf-8"))
        for name in L02_EVENTS:
            if blocks.get(name) != baseline.get(name):
                failures.append(f"L0.2 ABI block changed: {name}")

    if failures:
        print("FAIL", *failures, sep="\n", file=sys.stderr)
        return 1
    print("PASS: L0.3A trace contract and L0.2 ABI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
