#!/usr/bin/env python3
"""Build V3 next-app data aligned to app_lstm_next splits."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_FILE = ROOT / "data" / "raw" / "lsapp" / "app_events.csv"
DEFAULT_NEXT_DATASET_DIR = ROOT / "app_lstm_next" / "data" / "processed" / "app_lstm_next"
DEFAULT_TARGET_VOCAB = ROOT / "app_lstm_next" / "data" / "vocab" / "target_app_vocab.json"
DEFAULT_LEGACY_TARGET_VOCAB = ROOT / "app_lstm_next" / "data" / "vocab" / "app_vocab_next.json"
DEFAULT_APP_VOCAB = ROOT / "app_lstm_next" / "data" / "vocab" / "app_vocab_next.json"
DEFAULT_GROUP_VOCAB = ROOT / "data" / "vocab" / "user_group_vocab.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "processed" / "v3_next_app_aligned"
PAD_TOKEN = "<PAD>"
UNKNOWN_TOKEN = "<UNKNOWN>"
SPECIAL_TARGET_TOKENS = {PAD_TOKEN, UNKNOWN_TOKEN, "<SOS>", "<EOS>"}
UNKNOWN_VALUES = {"", "UNKNOWN", "None", "none", "null", "NULL"}
DEFAULT_GROUP = "閫氱敤鐢ㄦ埛"
SPLITS = ["train", "val", "test"]


def parse_time(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: str | Path) -> dict[str, int]:
    return {str(key): int(value) for key, value in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def split_pipe(value: str | None) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def build_target_vocab_from_next_train(next_dataset_dir: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in load_csv(next_dataset_dir / "train.csv"):
        target = row.get("target_app", "").strip()
        if target and target not in SPECIAL_TARGET_TOKENS:
            counts[target] += 1
    if not counts:
        raise ValueError("cannot build target_app_vocab: app_lstm_next train.csv has no real targets")
    return {app: idx for idx, (app, _count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])))}


def split_opened(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").replace("|", ";").split(";") if item.strip()]


def normalize_app(value: str | None) -> str:
    app = (value or "").strip()
    return UNKNOWN_TOKEN if app in UNKNOWN_VALUES else app


def sample_id_for(user_id: str, target_ts: datetime, target_app: str, history_ts: datetime, history_apps: list[str]) -> str:
    raw = "|".join([user_id, format_time(target_ts), target_app, format_time(history_ts), "\x1f".join(history_apps)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def signature(history_apps: list[str], target_app: str) -> tuple[str, str]:
    return "|".join(history_apps), target_app


def multihot(apps: list[str], app_vocab: dict[str, int]) -> str:
    vec = ["0"] * len(app_vocab)
    for app in apps:
        if app in {PAD_TOKEN, UNKNOWN_TOKEN}:
            continue
        app_id = app_vocab.get(app)
        if app_id is not None:
            vec[app_id] = "1"
    return "|".join(vec)


def read_events(path: Path) -> tuple[dict[str, list[dict[str, Any]]], int]:
    required = {"user_id", "timestamp", "foreground_app"}
    bad_rows = 0
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or required - set(reader.fieldnames):
            raise ValueError(f"missing required fields in {path}; required={sorted(required)}")
        for row in reader:
            user_id = (row.get("user_id") or "").strip()
            try:
                ts = parse_time(row.get("timestamp") or "")
            except ValueError:
                bad_rows += 1
                continue
            if not user_id:
                bad_rows += 1
                continue
            grouped[user_id].append(
                {
                    "user_id": user_id,
                    "timestamp": ts,
                    "foreground_app": normalize_app(row.get("foreground_app")),
                    "opened_apps": [normalize_app(app) for app in split_opened(row.get("opened_apps"))],
                    "user_group": row.get("user_group") or DEFAULT_GROUP,
                }
            )
    for rows in grouped.values():
        rows.sort(key=lambda item: item["timestamp"])
    return grouped, bad_rows


def split_users(
    users: list[str],
    train_user_ratio: float,
    val_user_ratio_within_train: float,
    seed: int,
) -> tuple[set[str], set[str], set[str]]:
    rng = random.Random(seed)
    shuffled = users[:]
    rng.shuffle(shuffled)
    test_count = max(1, int(round(len(shuffled) * (1.0 - train_user_ratio))))
    if test_count >= len(shuffled):
        test_count = len(shuffled) - 1
    test_users = set(shuffled[:test_count])
    train_pool = shuffled[test_count:]
    val_count = max(1, int(round(len(train_pool) * val_user_ratio_within_train))) if len(train_pool) > 1 else 0
    if val_count >= len(train_pool):
        val_count = len(train_pool) - 1
    val_users = set(train_pool[:val_count])
    train_users = set(train_pool[val_count:])
    return train_users, val_users, test_users


def history_durations(history_events: list[dict[str, Any]], target_ts: datetime) -> list[str]:
    durations: list[str] = []
    for idx, event in enumerate(history_events):
        next_ts = history_events[idx + 1]["timestamp"] if idx + 1 < len(history_events) else target_ts
        seconds = max(0.0, (next_ts - event["timestamp"]).total_seconds())
        durations.append(str(int(seconds)) if float(seconds).is_integer() else f"{seconds:.3f}".rstrip("0").rstrip("."))
    return durations


def pad_v3_history(
    history_apps: list[str],
    durations: list[str],
    app_vocab: dict[str, int],
    history_len: int,
) -> tuple[list[str], list[str], list[str]]:
    history_apps = [app if app in app_vocab else UNKNOWN_TOKEN for app in history_apps][-history_len:]
    durations = durations[-history_len:]
    if len(history_apps) != len(durations):
        raise ValueError("history app and duration lengths differ")
    pad = max(0, history_len - len(history_apps))
    return [PAD_TOKEN] * pad + history_apps, ["0"] * pad + durations, ["0"] * pad + ["1"] * len(history_apps)


def build_samples_by_user(
    events_by_user: dict[str, list[dict[str, Any]]],
    app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    group_vocab: dict[str, int],
    history_len: int,
    window_seconds: int,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]], Counter[str]]:
    samples_by_user: dict[str, list[dict[str, str]]] = {}
    report: list[dict[str, str]] = []
    reasons: Counter[str] = Counter()
    for user_id, events in events_by_user.items():
        samples: list[dict[str, str]] = []
        history_window: deque[dict[str, Any]] = deque()
        idx = 0
        while idx < len(events):
            target_ts = events[idx]["timestamp"]
            while history_window and (target_ts - history_window[0]["timestamp"]).total_seconds() > window_seconds:
                history_window.popleft()
            same_time: list[dict[str, Any]] = []
            while idx < len(events) and events[idx]["timestamp"] == target_ts:
                same_time.append(events[idx])
                idx += 1
            history_events = list(history_window)[-history_len:]
            for target_event in same_time:
                target_app = target_event["foreground_app"]
                history_apps_raw = [event["foreground_app"] for event in history_events]
                history_ts = history_events[-1]["timestamp"] if history_events else target_ts
                sample_id = sample_id_for(user_id, target_ts, target_app, history_ts, history_apps_raw)
                status = "aligned"
                reason = ""
                if not history_events:
                    status, reason = "invalid_history", "empty history"
                elif any(event["timestamp"] >= target_ts for event in history_events):
                    status, reason = "future_leakage", "history timestamp is not earlier than target"
                elif target_app not in target_app_vocab:
                    status, reason = "target_not_in_vocab", "target app missing from shared target vocab"
                elif target_app in SPECIAL_TARGET_TOKENS:
                    status, reason = "target_not_in_vocab", "target app is a special token"
                group_id = group_vocab.get(target_event.get("user_group") or DEFAULT_GROUP, group_vocab.get(DEFAULT_GROUP, 0))
                opened_apps = [app if app in app_vocab else UNKNOWN_TOKEN for app in target_event.get("opened_apps", [])]
                durations = history_durations(history_events, target_ts) if history_events else []
                padded_apps, padded_durations, mask = (
                    pad_v3_history(history_apps_raw, durations, app_vocab, history_len)
                    if history_events
                    else ([PAD_TOKEN] * history_len, ["0"] * history_len, ["0"] * history_len)
                )
                report.append(
                    {
                        "sample_id": sample_id,
                        "split": "",
                        "status": status,
                        "reason": reason,
                        "target_app": target_app,
                        "v3_features_available": "1" if status == "aligned" else "0",
                    }
                )
                if status != "aligned":
                    reasons[status] += 1
                    continue
                samples.append(
                    {
                        "sample_id": sample_id,
                        "user_id": user_id,
                        "target_timestamp": format_time(target_ts),
                        "history_endpoint_timestamp": format_time(history_ts),
                        "target_app": target_app,
                        "next_app_target": str(target_app_vocab[target_app]),
                        "history_apps_raw": "|".join(history_apps_raw),
                        "history_apps": "|".join(padded_apps),
                        "history_durations_s": "|".join(padded_durations),
                        "history_mask": "|".join(mask),
                        "opened_apps": "|".join(opened_apps),
                        "opened_apps_multihot": multihot(opened_apps, app_vocab),
                        "user_group": str(int(group_id)),
                        "user_group_name": target_event.get("user_group") or DEFAULT_GROUP,
                    }
                )
            history_window.extend(same_time)
        if samples:
            samples_by_user[user_id] = samples
    return samples_by_user, report, reasons


def flatten(samples_by_user: dict[str, list[dict[str, str]]], users: set[str], split: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for user_id in sorted(users):
        for row in samples_by_user.get(user_id, []):
            item = dict(row)
            item["split"] = split
            rows.append(item)
    return rows


def compare_with_next_split(
    rows: list[dict[str, str]],
    next_rows: list[dict[str, str]],
    target_app_vocab: dict[str, int],
    history_len: int,
    split: str,
) -> None:
    comparable_next_rows = [
        row for row in next_rows
        if row.get("target_app", "") in target_app_vocab and row.get("target_app", "") not in SPECIAL_TARGET_TOKENS
    ]
    if len(rows) != len(comparable_next_rows):
        print(
            f"WARNING: {split} aligned rows={len(rows)} differs from comparable "
            f"app_lstm_next rows={len(comparable_next_rows)}"
        )
    mismatches = 0
    for row, next_row in zip(rows, comparable_next_rows):
        expected = signature(split_pipe(next_row.get("history_apps"))[-history_len:], next_row.get("target_app", ""))
        actual = signature(split_pipe(row["history_apps_raw"])[-history_len:], row["target_app"])
        mismatches += int(expected != actual)
    if mismatches:
        print(f"WARNING: {split} sample signature mismatches with app_lstm_next: {mismatches}")
    else:
        print(f"{split} sample signatures match comparable app_lstm_next rows: {min(len(rows), len(comparable_next_rows))}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fieldnames} for row in rows])


def write_ids(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text("\n".join(row["sample_id"] for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V3 next-app data aligned to app_lstm_next.")
    parser.add_argument("--raw-file", default=str(DEFAULT_RAW_FILE))
    parser.add_argument("--next-dataset-dir", default=str(DEFAULT_NEXT_DATASET_DIR))
    parser.add_argument("--app-vocab", default=str(DEFAULT_APP_VOCAB))
    parser.add_argument("--target-app-vocab", default=str(DEFAULT_TARGET_VOCAB))
    parser.add_argument("--group-vocab", default=str(DEFAULT_GROUP_VOCAB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--history-len", type=int, default=23)
    parser.add_argument("--window-seconds", type=int, default=3600)
    parser.add_argument("--train-user-ratio", type=float, default=0.90)
    parser.add_argument("--val-user-ratio-within-train", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_vocab_path = Path(args.target_app_vocab)
    next_dataset_dir = Path(args.next_dataset_dir)
    if not target_vocab_path.exists():
        target_app_vocab = build_target_vocab_from_next_train(next_dataset_dir)
        target_vocab_path.parent.mkdir(parents=True, exist_ok=True)
        target_vocab_path.write_text(json.dumps(target_app_vocab, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"target_app_vocab built from app_lstm_next train split: {target_vocab_path}")
    else:
        target_app_vocab = load_json(target_vocab_path)
    app_vocab = load_json(args.app_vocab)
    group_vocab = load_json(args.group_vocab)
    special = SPECIAL_TARGET_TOKENS & set(target_app_vocab)
    if special:
        raise ValueError(f"target_app_vocab must not contain special tokens: {sorted(special)}")
    events_by_user, bad_rows = read_events(Path(args.raw_file))
    samples_by_user, report_rows, reasons = build_samples_by_user(
        events_by_user,
        app_vocab,
        target_app_vocab,
        group_vocab,
        args.history_len,
        args.window_seconds,
    )
    train_users, val_users, test_users = split_users(
        sorted(samples_by_user),
        args.train_user_ratio,
        args.val_user_ratio_within_train,
        args.seed,
    )
    split_rows = {
        "train": flatten(samples_by_user, train_users, "train"),
        "val": flatten(samples_by_user, val_users, "val"),
        "test": flatten(samples_by_user, test_users, "test"),
    }
    sample_to_split = {row["sample_id"]: split for split, rows in split_rows.items() for row in rows}
    for row in report_rows:
        row["split"] = sample_to_split.get(row["sample_id"], row["split"])

    for split in SPLITS:
        next_path = next_dataset_dir / f"{split}.csv"
        if next_path.exists():
            compare_with_next_split(split_rows[split], load_csv(next_path), target_app_vocab, args.history_len, split)
        else:
            print(f"WARNING: app_lstm_next split not found for comparison: {next_path}")

    output_dir = Path(args.output_dir)
    fields = [
        "sample_id", "split", "user_id", "target_timestamp", "history_endpoint_timestamp",
        "target_app", "next_app_target", "history_apps_raw", "history_apps",
        "history_durations_s", "history_mask", "opened_apps", "opened_apps_multihot",
        "user_group", "user_group_name",
    ]
    for split, rows in split_rows.items():
        write_csv(output_dir / f"{split}.csv", fields, rows)
        write_ids(output_dir / f"aligned_{split}_sample_ids.txt", rows)
    write_csv(
        output_dir / "alignment_report.csv",
        ["sample_id", "split", "status", "reason", "target_app", "v3_features_available"],
        report_rows,
    )
    meta = {
        "dataset": "v3_next_app_aligned",
        "raw_file": str(Path(args.raw_file)),
        "next_dataset_dir": str(next_dataset_dir),
        "input_app_vocab_path": str(Path(args.app_vocab)),
        "target_app_vocab_path": str(target_vocab_path),
        "group_vocab_path": str(Path(args.group_vocab)),
        "history_len": args.history_len,
        "window_seconds": args.window_seconds,
        "bad_raw_rows": bad_rows,
        "train_samples": len(split_rows["train"]),
        "val_samples": len(split_rows["val"]),
        "test_samples": len(split_rows["test"]),
        "excluded_sample_count": sum(reasons.values()),
        "excluded_reasons": dict(reasons),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dataset_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"aligned train/val/test: {len(split_rows['train'])}/{len(split_rows['val'])}/{len(split_rows['test'])}")
    print(f"excluded reasons: {dict(reasons)}")
    print(f"saved to: {output_dir}")


if __name__ == "__main__":
    main()
