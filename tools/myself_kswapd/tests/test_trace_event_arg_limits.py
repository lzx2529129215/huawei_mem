#!/usr/bin/env python3
"""Validate custom TRACE_EVENT producer argument limits without dependencies."""

from __future__ import annotations

import pathlib
import re
import sys


def parenthesized(text: str, open_index: int) -> str:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index]
    raise ValueError("unbalanced parentheses")


def split_top_level(text: str) -> list[str]:
    values: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            values.append(text[start:index].strip())
            start = index + 1
    values.append(text[start:].strip())
    return [value for value in values if value]


def macro_body(event: str, name: str) -> str:
    match = re.search(rf"\b{name}\(", event)
    if match is None:
        raise ValueError(f"missing {name}")
    return parenthesized(event, match.end() - 1)


def parameter_name(declaration: str) -> str:
    normalized = re.sub(r"\s+", " ", declaration).strip()
    return normalized.split()[-1].lstrip("*")


def events(text: str) -> list[tuple[str, list[str], list[str]]]:
    found: list[tuple[str, list[str], list[str]]] = []
    for match in re.finditer(r"\bTRACE_EVENT\((\w+),", text):
        event = parenthesized(text, text.index("(", match.start()))
        proto = split_top_level(macro_body(event, "TP_PROTO"))
        args = split_top_level(macro_body(event, "TP_ARGS"))
        found.append((match.group(1), proto, args))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} TRACE_HEADER", file=sys.stderr)
        return 2
    header = pathlib.Path(argv[1])
    failures: list[str] = []
    for name, proto, args in events(header.read_text(encoding="utf-8")):
        proto_names = [parameter_name(item) for item in proto]
        print(f"{name}: proto={len(proto)} args={len(args)}")
        if len(proto) != len(args):
            failures.append(f"{name}: proto/args count mismatch")
        if proto_names != args:
            failures.append(f"{name}: proto/args names or order mismatch")
        if len(proto) > 12:
            failures.append(f"{name}: producer args {len(proto)} exceed BPF limit 12")
    if failures:
        print("FAIL:", *failures, sep="\n", file=sys.stderr)
        return 1
    print("PASS: all custom trace events have <= 12 producer arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
