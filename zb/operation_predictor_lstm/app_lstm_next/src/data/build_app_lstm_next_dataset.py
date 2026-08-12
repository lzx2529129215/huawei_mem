#!/usr/bin/env python3
"""Build variable-length WhatsNextApp next-app LSTM datasets.

Only foreground_app is used as the model signal. user_id and timestamp are
used for ordering, user-level splitting, and 1-hour history windows.  When a
user has multiple foreground changes in the same second, the input CSV row
order is treated as the authoritative order.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable


APP_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = APP_ROOT / "data" / "raw" / "app_events"
FALLBACK_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "app_events"
FALLBACK_RAW_FILE = PROJECT_ROOT / "data" / "raw" / "lsapp" / "app_events.csv"
DEFAULT_OUTPUT_DIR = APP_ROOT / "data" / "processed" / "app_lstm_next"
DEFAULT_VOCAB_DIR = APP_ROOT / "data" / "vocab"
DEFAULT_VOCAB_PATH = DEFAULT_VOCAB_DIR / "app_vocab_next.json"
DEFAULT_INPUT_VOCAB_PATH = DEFAULT_VOCAB_DIR / "input_app_vocab.json"
DEFAULT_TARGET_VOCAB_PATH = DEFAULT_VOCAB_DIR / "target_app_vocab.json"
TIME_WINDOW_SECONDS = 3600
HISTORY_LEN = 23
CSV_FIELDS = ["user_id", "target_timestamp", "history_apps", "target_app"]
PAD_TOKEN = "<PAD>"
UNKNOWN_TOKEN = "<UNKNOWN>"
UNKNOWN_VALUES = {"", "UNKNOWN", "None", "none", "null", "NULL"}
SPECIAL_TARGET_TOKENS = {PAD_TOKEN, UNKNOWN_TOKEN, "<SOS>", "<EOS>"}


@dataclass(frozen=True)
class AppEvent:
    timestamp: datetime
    app: str
    source_row_index: int


def parse_time(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def input_files(raw_dir: Path, input_file: str | None) -> list[Path]:
    if input_file:
        path = Path(input_file)
        if not path.exists():
            raise FileNotFoundError(f"input file not found: {path}")
        return [path]
    files = sorted(raw_dir.glob("*.csv"))
    if files:
        return files
    fallback_files = sorted(FALLBACK_RAW_DIR.glob("*.csv"))
    if fallback_files:
        return fallback_files
    if FALLBACK_RAW_FILE.exists():
        return [FALLBACK_RAW_FILE]
    raise FileNotFoundError(
        f"no CSV files found in {raw_dir}, {FALLBACK_RAW_DIR}, and fallback missing: {FALLBACK_RAW_FILE}"
    )


def read_events(paths: Iterable[Path]) -> tuple[dict[str, list[AppEvent]], dict[str, int]]:
    sequences: dict[str, list[AppEvent]] = defaultdict(list)
    stats = {
        "raw_input_rows": 0,
        "events_before_cleaning": 0,
        "valid_input_events": 0,
        "bad_rows_skipped": 0,
        "empty_user_id_rows_skipped": 0,
        "invalid_timestamp_rows_skipped": 0,
        "empty_foreground_app_rows_skipped": 0,
        "num_users_total": 0,
    }
    required = {"user_id", "timestamp", "foreground_app"}
    source_row_index = 0
    for path in paths:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or required - set(reader.fieldnames):
                raise ValueError(f"missing required fields in {path}; required={sorted(required)}")
            for row in reader:
                current_row_index = source_row_index
                source_row_index += 1
                stats["raw_input_rows"] += 1
                user_id = (row.get("user_id") or "").strip()
                app = (row.get("foreground_app") or "").strip()
                if not user_id:
                    stats["empty_user_id_rows_skipped"] += 1
                    stats["bad_rows_skipped"] += 1
                    continue
                try:
                    ts = parse_time(row.get("timestamp") or "")
                except ValueError:
                    stats["invalid_timestamp_rows_skipped"] += 1
                    stats["bad_rows_skipped"] += 1
                    continue
                if not app:
                    stats["empty_foreground_app_rows_skipped"] += 1
                    stats["bad_rows_skipped"] += 1
                    continue
                if app in UNKNOWN_VALUES:
                    app = UNKNOWN_TOKEN
                sequences[user_id].append(AppEvent(ts, app, current_row_index))
                stats["events_before_cleaning"] += 1
                stats["valid_input_events"] += 1
    for rows in sequences.values():
        rows.sort(key=lambda item: (item.timestamp, item.source_row_index))
    stats["num_users_total"] = len(sequences)
    return sequences, stats


def ordered_unique_count(apps: Iterable[str]) -> int:
    seen: list[str] = []
    count = 0
    for app in apps:
        if app in seen:
            continue
        seen.append(app)
        count += 1
    return count


def clean_same_timestamp_events(
    sequences: dict[str, list[AppEvent]],
) -> tuple[dict[str, list[AppEvent]], dict[str, int]]:
    cleaned: dict[str, list[AppEvent]] = {}
    stats = {
        "same_timestamp_groups_total": 0,
        "same_timestamp_single_app_groups": 0,
        "same_timestamp_duplicate_groups": 0,
        "same_timestamp_duplicate_events_removed": 0,
        "same_timestamp_multi_app_groups": 0,
        "same_timestamp_multi_app_original_events": 0,
        "same_timestamp_multi_app_events_retained": 0,
        "legacy_ambiguous_same_timestamp_groups_would_drop": 0,
        "legacy_ambiguous_same_timestamp_events_would_drop": 0,
        "ambiguous_same_timestamp_groups_dropped": 0,
        "ambiguous_same_timestamp_events_dropped": 0,
        "same_timestamp_order_anomaly_count": 0,
        "events_after_same_timestamp_cleaning": 0,
    }
    for user_id, rows in sequences.items():
        ordered_rows = sorted(rows, key=lambda item: (item.timestamp, item.source_row_index))
        user_cleaned: list[AppEvent] = []
        group: list[AppEvent] = []

        def flush_group(items: list[AppEvent]) -> None:
            if not items:
                return
            stats["same_timestamp_groups_total"] += 1
            if any(items[idx].source_row_index <= items[idx - 1].source_row_index for idx in range(1, len(items))):
                stats["same_timestamp_order_anomaly_count"] += 1

            distinct_app_count = ordered_unique_count(event.app for event in items)
            if distinct_app_count == 1:
                stats["same_timestamp_single_app_groups"] += 1
                if len(items) > 1:
                    stats["same_timestamp_duplicate_groups"] += 1
                    stats["same_timestamp_duplicate_events_removed"] += len(items) - 1
                user_cleaned.append(items[0])
                return

            # Same-second events can represent real ordered switches.  Keep the
            # CSV row order and only fold adjacent duplicate app observations
            # inside that ordered same-second run.
            stats["same_timestamp_multi_app_groups"] += 1
            stats["same_timestamp_multi_app_original_events"] += len(items)
            stats["legacy_ambiguous_same_timestamp_groups_would_drop"] += 1
            stats["legacy_ambiguous_same_timestamp_events_would_drop"] += len(items)
            previous_app: str | None = None
            retained = 0
            for event in items:
                if event.app == previous_app:
                    stats["same_timestamp_duplicate_events_removed"] += 1
                    continue
                user_cleaned.append(event)
                retained += 1
                previous_app = event.app
            stats["same_timestamp_multi_app_events_retained"] += retained

        for event in ordered_rows:
            if group and event.timestamp != group[-1].timestamp:
                flush_group(group)
                group = []
            group.append(event)
        flush_group(group)

        if user_cleaned:
            cleaned[user_id] = user_cleaned
            stats["events_after_same_timestamp_cleaning"] += len(user_cleaned)
    return cleaned, stats


def collapse_consecutive_apps(
    sequences: dict[str, list[AppEvent]],
) -> tuple[dict[str, list[AppEvent]], dict[str, int]]:
    collapsed: dict[str, list[AppEvent]] = {}
    stats = {
        "consecutive_duplicate_events_collapsed": 0,
        "events_after_consecutive_collapse": 0,
    }
    for user_id, rows in sequences.items():
        user_collapsed: list[AppEvent] = []
        previous_app: str | None = None
        for event in sorted(rows, key=lambda item: (item.timestamp, item.source_row_index)):
            if event.app == previous_app:
                stats["consecutive_duplicate_events_collapsed"] += 1
                continue
            user_collapsed.append(event)
            previous_app = event.app
        if user_collapsed:
            collapsed[user_id] = user_collapsed
            stats["events_after_consecutive_collapse"] += len(user_collapsed)
    return collapsed, stats


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def build_input_vocab(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(app for app in split_pipe(row["history_apps"]) if app not in {PAD_TOKEN, "<SOS>", "<EOS>"})
    vocab = {PAD_TOKEN: 0, UNKNOWN_TOKEN: 1}
    for app, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if app not in vocab:
            vocab[app] = len(vocab)
    return vocab


def build_target_vocab(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        target = row["target_app"]
        if target and target not in SPECIAL_TARGET_TOKENS:
            counts[target] += 1
    return {app: idx for idx, (app, _count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])))}


def make_user_samples(
    sequences: dict[str, list[AppEvent]],
    time_window_seconds: int,
    history_len: int,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    samples_by_user: dict[str, list[dict[str, str]]] = {}
    stats = {
        "target_events_skipped_empty_history": 0,
        "target_events_skipped_special_target": 0,
        "history_truncated_samples": 0,
        "samples_with_last_history_app_equal_target": 0,
    }
    for user_id, rows in sequences.items():
        samples: list[dict[str, str]] = []
        history_window: deque[AppEvent] = deque()
        for target in sorted(rows, key=lambda item: (item.timestamp, item.source_row_index)):
            while history_window and (target.timestamp - history_window[0].timestamp).total_seconds() > time_window_seconds:
                history_window.popleft()

            # The deque already contains only events that precede this target in
            # the ordered event stream.  Same-second earlier CSV rows therefore
            # become valid history for later same-second targets.
            full_history = [event.app for event in history_window]
            history = full_history[-history_len:]
            if not history:
                stats["target_events_skipped_empty_history"] += 1
            elif target.app in SPECIAL_TARGET_TOKENS:
                stats["target_events_skipped_special_target"] += 1
            else:
                if len(full_history) > history_len:
                    stats["history_truncated_samples"] += 1
                if history[-1] == target.app:
                    stats["samples_with_last_history_app_equal_target"] += 1
                    raise RuntimeError(
                        f"last history app equals target_app for user={user_id}, "
                        f"timestamp={format_time(target.timestamp)}, source_row_index={target.source_row_index}"
                    )
                samples.append(
                    {
                        "user_id": user_id,
                        "target_timestamp": format_time(target.timestamp),
                        "history_apps": "|".join(history),
                        "target_app": target.app,
                    }
                )
            history_window.append(target)

        if samples:
            samples_by_user[user_id] = samples
    return samples_by_user, stats


def split_users(
    users: list[str],
    train_user_ratio: float,
    val_user_ratio_within_train: float,
    seed: int,
) -> tuple[set[str], set[str], set[str]]:
    if len(users) < 2:
        raise ValueError("at least two users with samples are required for user-level train/test split")
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


def flatten(samples_by_user: dict[str, list[dict[str, str]]], users: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for user_id in sorted(users):
        rows.extend(samples_by_user.get(user_id, []))
    return rows


def count_filtered_targets(rows: list[dict[str, str]], target_app_vocab: dict[str, int]) -> int:
    return sum(1 for row in rows if row.get("target_app") not in target_app_vocab)


def history_lengths(rows: Iterable[dict[str, str]]) -> list[int]:
    return [len(split_pipe(row["history_apps"])) for row in rows]


def sample_signature(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("user_id", ""),
        row.get("target_timestamp", ""),
        row.get("history_apps", ""),
        row.get("target_app", ""),
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != CSV_FIELDS:
            raise RuntimeError(f"{path} header mismatch: {reader.fieldnames} != {CSV_FIELDS}")
        return list(reader)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_generated_dataset(
    paths: dict[str, Path],
    input_app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    meta: dict,
    history_len: int,
) -> dict[str, int]:
    rows_by_split = {split: read_csv_rows(paths[f"{split}.csv"]) for split in ("train", "val", "test")}
    for split, rows in rows_by_split.items():
        if not rows:
            raise RuntimeError(f"{split}.csv must be non-empty")

    users_by_split: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    last_equals_target = 0
    for split, rows in rows_by_split.items():
        users: set[str] = set()
        seen_samples: set[tuple[str, str, str, str]] = set()
        for line_no, row in enumerate(rows, start=2):
            user_id = (row.get("user_id") or "").strip()
            target_timestamp = (row.get("target_timestamp") or "").strip()
            history_apps = (row.get("history_apps") or "").strip()
            target_app = (row.get("target_app") or "").strip()
            if not user_id:
                raise RuntimeError(f"{split}:{line_no} user_id is empty")
            try:
                parse_time(target_timestamp)
            except ValueError as exc:
                raise RuntimeError(f"{split}:{line_no} target_timestamp is invalid: {target_timestamp}") from exc
            if not history_apps:
                raise RuntimeError(f"{split}:{line_no} history_apps is empty")
            if not target_app:
                raise RuntimeError(f"{split}:{line_no} target_app is empty")
            if target_app in SPECIAL_TARGET_TOKENS:
                raise RuntimeError(f"{split}:{line_no} target_app is a special token: {target_app}")

            history = split_pipe(history_apps)
            if not (1 <= len(history) <= history_len):
                raise RuntimeError(f"{split}:{line_no} history length out of bounds: {len(history)}")
            if any(app in {PAD_TOKEN, "<SOS>", "<EOS>"} for app in history):
                raise RuntimeError(f"{split}:{line_no} history_apps contains a forbidden special token")
            if any(history[idx] == history[idx - 1] for idx in range(1, len(history))):
                raise RuntimeError(f"{split}:{line_no} adjacent history apps are equal")
            if history[-1] == target_app:
                last_equals_target += 1
                raise RuntimeError(f"{split}:{line_no} last history app equals target_app")

            signature = sample_signature(row)
            if signature in seen_samples:
                raise RuntimeError(f"{split}:{line_no} duplicate complete sample: {signature}")
            seen_samples.add(signature)
            users.add(user_id)

        users_by_split[split] = users
        counts[f"num_{split}_samples"] = len(rows)
        counts[f"num_{split}_users"] = len(users)

    overlaps = {
        "train_val_user_overlap": len(users_by_split["train"] & users_by_split["val"]),
        "train_test_user_overlap": len(users_by_split["train"] & users_by_split["test"]),
        "val_test_user_overlap": len(users_by_split["val"] & users_by_split["test"]),
    }
    if any(overlaps.values()):
        raise RuntimeError(f"user-level splits overlap: {overlaps}")

    ids = sorted(target_app_vocab.values())
    if ids != list(range(len(ids))):
        raise RuntimeError("target_app_vocab ids must be contiguous from 0")
    if PAD_TOKEN not in input_app_vocab or UNKNOWN_TOKEN not in input_app_vocab:
        raise RuntimeError("input_app_vocab must contain <PAD> and <UNKNOWN>")
    bad_targets = sorted(SPECIAL_TARGET_TOKENS & set(target_app_vocab))
    if bad_targets:
        raise RuntimeError(f"target_app_vocab contains special tokens: {bad_targets}")
    train_missing_targets = sorted({row["target_app"] for row in rows_by_split["train"] if row["target_app"] not in target_app_vocab})
    if train_missing_targets:
        raise RuntimeError(f"train targets missing from target_app_vocab: {train_missing_targets[:10]}")

    for key, actual in counts.items():
        if int(meta.get(key, -1)) != actual:
            raise RuntimeError(f"metadata {key}={meta.get(key)} does not match CSV count {actual}")
    if int(meta.get("samples_with_last_history_app_equal_target", -1)) != last_equals_target:
        raise RuntimeError("metadata samples_with_last_history_app_equal_target mismatch")
    return overlaps


def temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp")


def replace_outputs(temp_paths: dict[str, Path], final_paths: dict[str, Path]) -> None:
    for key, src in temp_paths.items():
        src.replace(final_paths[key])


def cleanup_temp(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WhatsNextApp LSTM next-app dataset.")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--input-file", help="Optional single app_events CSV.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--vocab-path", default=str(DEFAULT_VOCAB_PATH))
    parser.add_argument("--input-vocab-path", default=str(DEFAULT_INPUT_VOCAB_PATH))
    parser.add_argument("--target-vocab-path", default=str(DEFAULT_TARGET_VOCAB_PATH))
    parser.add_argument("--time-window-seconds", type=int, default=TIME_WINDOW_SECONDS)
    parser.add_argument("--window-seconds", type=int, help="Alias for --time-window-seconds.")
    parser.add_argument("--history-len", type=int, default=HISTORY_LEN)
    parser.add_argument("--train-user-ratio", type=float, default=0.90)
    parser.add_argument("--val-user-ratio-within-train", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.window_seconds is not None:
        args.time_window_seconds = args.window_seconds
    if args.time_window_seconds <= 0:
        raise ValueError("time_window_seconds must be positive")
    if args.history_len <= 0:
        raise ValueError("history_len must be positive")

    paths = input_files(Path(args.raw_dir), args.input_file)
    sequences, read_stats = read_events(paths)
    same_time_sequences, same_time_stats = clean_same_timestamp_events(sequences)
    switch_sequences, collapse_stats = collapse_consecutive_apps(same_time_sequences)
    samples_by_user, sample_stats = make_user_samples(switch_sequences, args.time_window_seconds, args.history_len)
    train_users, val_users, test_users = split_users(
        sorted(samples_by_user),
        args.train_user_ratio,
        args.val_user_ratio_within_train,
        args.seed,
    )

    train_rows = flatten(samples_by_user, train_users)
    val_rows = flatten(samples_by_user, val_users)
    test_rows = flatten(samples_by_user, test_users)
    if not train_rows or not val_rows or not test_rows:
        raise ValueError("train, val, and test splits must be non-empty")

    input_app_vocab = build_input_vocab(train_rows)
    target_app_vocab = build_target_vocab(train_rows)
    if not target_app_vocab:
        raise ValueError("target_app_vocab must contain at least one real app")

    excluded_val_targets = count_filtered_targets(val_rows, target_app_vocab)
    excluded_test_targets = count_filtered_targets(test_rows, target_app_vocab)
    lengths = history_lengths(row for rows in samples_by_user.values() for row in rows)
    samples_with_last_equal_target = sample_stats["samples_with_last_history_app_equal_target"]

    output_dir = Path(args.output_dir)
    final_paths = {
        "train.csv": output_dir / "train.csv",
        "val.csv": output_dir / "val.csv",
        "test.csv": output_dir / "test.csv",
        "dataset_meta.json": output_dir / "dataset_meta.json",
        "input_app_vocab.json": Path(args.input_vocab_path),
        "target_app_vocab.json": Path(args.target_vocab_path),
        "app_vocab_next.json": Path(args.vocab_path),
    }
    temp_paths = {key: temp_path(path) for key, path in final_paths.items()}

    meta = {
        "model": "WhatsNextApp_LSTM_next_app",
        "paper": "WhatsNextApp: LSTM-Based Next-App Prediction With App Usage Sequences",
        "task": "predicting_next_distinct_app_switch",
        "target_definition": "the next different foreground app after collapsing consecutive identical foreground app observations",
        "input_columns_used_for_model": ["foreground_app"],
        "columns_used_only_for_sort_split_validation": ["user_id", "timestamp", "source_row_index"],
        "csv_columns": CSV_FIELDS,
        "same_timestamp_rule": (
            "sort by user_id, timestamp, and source_row_index; keep same-second distinct apps in CSV row order; "
            "collapse only adjacent identical app observations"
        ),
        "consecutive_duplicate_rule": "collapse adjacent identical apps and retain the first timestamp as the app switch-in timestamp",
        "history_rule": (
            "earlier events in the ordered switch sequence inside the configured time window, including earlier "
            f"same-second source rows, keeping at most {args.history_len} events"
        ),
        "time_window_minutes": args.time_window_seconds / 60.0,
        "time_window_seconds": args.time_window_seconds,
        "window_seconds": args.time_window_seconds,
        "history_len": args.history_len,
        "sequence_type": "variable_length_distinct_app_switch_sequence",
        "split": "user_level_disjoint_train_val_test",
        "train_user_ratio": args.train_user_ratio,
        "val_user_ratio_within_train": args.val_user_ratio_within_train,
        "seed": args.seed,
        "source_files": [str(path) for path in paths],
        **read_stats,
        **same_time_stats,
        **collapse_stats,
        **sample_stats,
        "same_timestamp_multi_app_groups_dropped": 0,
        "same_timestamp_multi_app_events_dropped": 0,
        "new_logic_same_timestamp_multi_app_events_retained": same_time_stats["same_timestamp_multi_app_events_retained"],
        "num_users_with_samples": len(samples_by_user),
        "num_train_users": len(train_users),
        "num_val_users": len(val_users),
        "num_test_users": len(test_users),
        "num_input_tokens": len(input_app_vocab),
        "num_target_apps": len(target_app_vocab),
        "num_train_samples": len(train_rows),
        "num_val_samples": len(val_rows),
        "num_test_samples": len(test_rows),
        "excluded_val_targets_not_in_train_vocab": excluded_val_targets,
        "excluded_test_targets_not_in_train_vocab": excluded_test_targets,
        "min_history_length": min(lengths) if lengths else 0,
        "median_history_length": median(lengths) if lengths else 0,
        "max_history_length": max(lengths) if lengths else 0,
        "sample_format": "user_id,target_timestamp,history_apps,target_app",
        "history_separator": "|",
        "pad_token": PAD_TOKEN,
        "pad_id": input_app_vocab[PAD_TOKEN],
        "unknown_token": UNKNOWN_TOKEN,
        "unknown_id": input_app_vocab[UNKNOWN_TOKEN],
        "input_app_vocab_path": str(Path(args.input_vocab_path)),
        "target_app_vocab_path": str(Path(args.target_vocab_path)),
    }

    try:
        cleanup_temp(temp_paths.values())
        write_csv(temp_paths["train.csv"], train_rows)
        write_csv(temp_paths["val.csv"], val_rows)
        write_csv(temp_paths["test.csv"], test_rows)
        write_json(temp_paths["input_app_vocab.json"], input_app_vocab)
        write_json(temp_paths["target_app_vocab.json"], target_app_vocab)
        write_json(temp_paths["app_vocab_next.json"], input_app_vocab)
        write_json(temp_paths["dataset_meta.json"], meta)

        overlaps = validate_generated_dataset(
            {
                "train.csv": temp_paths["train.csv"],
                "val.csv": temp_paths["val.csv"],
                "test.csv": temp_paths["test.csv"],
            },
            input_app_vocab,
            target_app_vocab,
            meta,
            args.history_len,
        )
        replace_outputs(temp_paths, final_paths)
        final_overlaps = validate_generated_dataset(
            {
                "train.csv": final_paths["train.csv"],
                "val.csv": final_paths["val.csv"],
                "test.csv": final_paths["test.csv"],
            },
            input_app_vocab,
            target_app_vocab,
            meta,
            args.history_len,
        )
        if final_overlaps != overlaps:
            raise RuntimeError("final output validation disagrees with temporary output validation")
    except Exception:
        cleanup_temp(temp_paths.values())
        raise

    print(f"source files: {len(paths)}")
    print(f"raw input rows: {read_stats['raw_input_rows']}")
    print(f"raw users: {read_stats['num_users_total']}")
    print(f"bad rows skipped: {read_stats['bad_rows_skipped']}")
    print(f"empty user_id rows skipped: {read_stats['empty_user_id_rows_skipped']}")
    print(f"invalid timestamp rows skipped: {read_stats['invalid_timestamp_rows_skipped']}")
    print(f"empty foreground_app rows skipped: {read_stats['empty_foreground_app_rows_skipped']}")
    print(f"events before cleaning: {read_stats['events_before_cleaning']}")
    print(f"valid input events: {read_stats['valid_input_events']}")
    print(f"same timestamp groups total: {same_time_stats['same_timestamp_groups_total']}")
    print(f"same timestamp single app groups: {same_time_stats['same_timestamp_single_app_groups']}")
    print(f"same timestamp duplicate groups: {same_time_stats['same_timestamp_duplicate_groups']}")
    print(f"same timestamp duplicate events removed: {same_time_stats['same_timestamp_duplicate_events_removed']}")
    print(f"same timestamp multi-app groups: {same_time_stats['same_timestamp_multi_app_groups']}")
    print(f"same timestamp multi-app original events: {same_time_stats['same_timestamp_multi_app_original_events']}")
    print(f"legacy ambiguous same timestamp groups would drop: {same_time_stats['legacy_ambiguous_same_timestamp_groups_would_drop']}")
    print(f"legacy ambiguous same timestamp events would drop: {same_time_stats['legacy_ambiguous_same_timestamp_events_would_drop']}")
    print(f"same timestamp multi-app groups dropped: 0")
    print(f"same timestamp multi-app events retained by new logic: {same_time_stats['same_timestamp_multi_app_events_retained']}")
    print(f"same timestamp order anomaly count: {same_time_stats['same_timestamp_order_anomaly_count']}")
    print(f"events after same timestamp cleaning: {same_time_stats['events_after_same_timestamp_cleaning']}")
    print(f"consecutive duplicate events collapsed: {collapse_stats['consecutive_duplicate_events_collapsed']}")
    print(f"events after consecutive collapse: {collapse_stats['events_after_consecutive_collapse']}")
    print(f"target events skipped due to empty history: {sample_stats['target_events_skipped_empty_history']}")
    print(f"history truncated samples: {sample_stats['history_truncated_samples']}")
    print(f"users with samples: {len(samples_by_user)}")
    print(f"train/val/test users: {len(train_users)}/{len(val_users)}/{len(test_users)}")
    print(f"train/val/test samples: {len(train_rows)}/{len(val_rows)}/{len(test_rows)}")
    print(f"history length min/median/max: {meta['min_history_length']}/{meta['median_history_length']}/{meta['max_history_length']}")
    print(f"user overlaps train-val/train-test/val-test: {overlaps['train_val_user_overlap']}/{overlaps['train_test_user_overlap']}/{overlaps['val_test_user_overlap']}")
    print(f"last history app equals target samples: {samples_with_last_equal_target}")
    print(f"excluded val/test targets not in train vocab: {excluded_val_targets}/{excluded_test_targets}")
    print(f"time window seconds: {args.time_window_seconds}")
    print(f"history len: {args.history_len}")
    print(f"input vocab saved: {final_paths['input_app_vocab.json']}")
    print(f"target vocab saved: {final_paths['target_app_vocab.json']}")
    print(f"legacy input vocab saved: {final_paths['app_vocab_next.json']}")
    print(f"dataset saved: {output_dir}")
    print("validation: passed")


if __name__ == "__main__":
    main()
