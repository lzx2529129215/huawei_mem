#!/usr/bin/env python3
"""Export a Bilibili 4-order operation Markov transition table."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


input_path = "op_events_bilibili_fsm.csv"
output_path = "zb/MGLRU/generated/cache_ext_markov_transition.csv"
app_id = 4
order = 4

APP_NAME = "哔哩哔哩"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_input_path(root: Path) -> Path:
    candidates = [
        root / input_path,
        root / "zb" / "operation_predictor" / "data" / "raw" / input_path,
    ]
    for path in candidates:
        if path.is_file():
            return path
    fail(f"input CSV not found: {input_path}")


def find_op_vocab_path(root: Path) -> Path:
    candidates = [
        root / "zb" / "operation_predictor" / "data" / "processed" / "op_vocab.json",
        root / "zb" / "operation_predictor" / "data" / "op_vocab.json",
        root / "zb" / "operation_predictor" / "data" / "vocab" / "op_vocab.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = sorted((root / "zb" / "operation_predictor").rglob("op_vocab.json"))
    if matches:
        return matches[0]
    fail("op_vocab not found; please provide an op_vocab.json path")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def app_name_from_app_vocab(root: Path) -> str | None:
    path = root / "zb" / "operation_predictor" / "data" / "vocab" / "app_vocab.json"
    if not path.is_file():
        return None
    app_vocab = load_json(path)
    for name, value in app_vocab.items():
        if int(value) == app_id:
            return name
    return None


def operation_vocab_for_app(root: Path, op_vocab: dict) -> tuple[str, dict[str, int]]:
    app_name = app_name_from_app_vocab(root) or APP_NAME
    app_ops = op_vocab.get(app_name)
    if isinstance(app_ops, dict):
        return app_name, {str(name): int(op_id) for name, op_id in app_ops.items()}

    app_ops = op_vocab.get(APP_NAME)
    if isinstance(app_ops, dict):
        return APP_NAME, {str(name): int(op_id) for name, op_id in app_ops.items()}

    fail(f"op_vocab does not contain app_id={app_id} ({APP_NAME})")


def read_events(csv_path: Path, app_name: str, op_map: dict[str, int]) -> tuple[int, int, int, dict[str, list[tuple[str, int]]]]:
    loaded = 0
    used = 0
    skipped = 0
    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"user_id", "timestamp", "operation"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            fail(f"input CSV missing required fields: {', '.join(sorted(missing))}")

        for row in reader:
            loaded += 1
            if "app" in row and row.get("app") != app_name:
                continue

            operation = row.get("operation", "")
            if operation not in op_map:
                print(f"warning: operation not in op_vocab, skipped: {operation}", file=sys.stderr)
                skipped += 1
                continue

            user_id = row.get("user_id", "")
            timestamp = row.get("timestamp", "")
            if not user_id or not timestamp:
                skipped += 1
                continue

            grouped[user_id].append((timestamp, op_map[operation]))
            used += 1

    return loaded, used, skipped, grouped


def build_transitions(grouped: dict[str, list[tuple[str, int]]]) -> tuple[int, dict[tuple[int, ...], Counter[int]]]:
    valid_sequences = 0
    transitions: dict[tuple[int, ...], Counter[int]] = defaultdict(Counter)

    for events in grouped.values():
        events.sort(key=lambda item: item[0])
        ops = [op_id for _, op_id in events]
        if len(ops) < order + 1:
            continue

        valid_sequences += 1
        for idx in range(0, len(ops) - order):
            context = tuple(ops[idx : idx + order])
            next_op = ops[idx + order]
            transitions[context][next_op] += 1

    return valid_sequences, transitions


def write_transitions(path: Path, transitions: dict[tuple[int, ...], Counter[int]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["app_id", "order", "ctx0", "ctx1", "ctx2", "ctx3", "next_op", "count", "prob"]

    exported = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for context in sorted(transitions):
            next_counts = transitions[context]
            total = sum(next_counts.values())
            for next_op, count in sorted(next_counts.items(), key=lambda item: (-item[1], item[0])):
                writer.writerow(
                    {
                        "app_id": app_id,
                        "order": order,
                        "ctx0": context[0],
                        "ctx1": context[1],
                        "ctx2": context[2],
                        "ctx3": context[3],
                        "next_op": next_op,
                        "count": count,
                        "prob": f"{count / total:.6f}",
                    }
                )
                exported += 1

    return exported


def main() -> None:
    root = repo_root()
    csv_path = resolve_input_path(root)
    op_vocab_path = find_op_vocab_path(root)
    op_vocab = load_json(op_vocab_path)
    app_name, op_map = operation_vocab_for_app(root, op_vocab)

    loaded, used, skipped, grouped = read_events(csv_path, app_name, op_map)
    if used == 0:
        fail("no data left after app filtering and op_vocab mapping")

    valid_sequences, transitions = build_transitions(grouped)
    if valid_sequences == 0:
        fail("valid user sequences are insufficient")
    if not transitions:
        fail("no 4-order transitions generated")

    out_path = root / output_path
    exported = write_transitions(out_path, transitions)

    print(f"Loaded rows: {loaded}")
    print(f"Used rows: {used}")
    print(f"Skipped rows: {skipped}")
    print(f"Valid user sequences: {valid_sequences}")
    print(f"Exported 4-order transitions: {exported}")
    print(f"Output CSV: {output_path}")


if __name__ == "__main__":
    main()
