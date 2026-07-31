#!/usr/bin/env python3
"""Generate app_events.csv from Excel app_vocab_mapping app sequences.

The Excel workbook already contains the authoritative app_vocab_mapping value
for each app operation. App switches are therefore decided only by comparing
the current valid app with the previous valid app for the same user. data_event
is used only to maintain the opened_apps background list; process_name is kept
for diagnostics but never decides app switches or opened_apps state.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXCEL = ROOT / "data" / "vocab" / "大学生-100-interaction-jank.xlsx"
DEFAULT_APP_VOCAB = ROOT / "data" / "vocab" / "app_vocab.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "app_events.csv"
DEFAULT_USER_GROUP = "大学生"

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SPECIAL_TOKENS = {"<PAD>", "<UNKNOWN>", "<UNK>", "<SOS>", "<EOS>"}
NULL_MAPPING_VALUES = {"", "NULL", "NONE", "NAN", "N/A", "NA"}
OPEN_EVENTS = {"APP_START", "PROCESS_START", "OPEN", "START", "OPENED", "LAUNCHER_APP_LAUNCH_FROM_DOCK"}
CLOSE_EVENTS = {"PROCESS_EXIT", "APP_CLOSE", "CLOSE", "EXIT", "CLOSED"}
REQUIRED_COLUMNS = {"timestamp_s", "app_vocab_mapping"}
OUTPUT_FIELDS = ["user_id", "timestamp", "foreground_app", "opened_apps", "user_group"]


@dataclass(frozen=True)
class SheetInfo:
    path: str
    header: list[str]
    data_rows: int


@dataclass(frozen=True)
class AppMappingResult:
    status: str
    app: str = ""


def col_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise ValueError(f"bad cell reference: {cell_ref}")
    out = 0
    for char in match.group(1):
        out = out * 26 + ord(char) - ord("A") + 1
    return out - 1


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(text.text or "" for text in item.findall(".//a:t", NS)) for item in root.findall("a:si", NS)]


def cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    if cell_type == "s" and value is not None:
        return shared[int(value.text or "0")]
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", NS))
    return "" if value is None or value.text is None else value.text


def worksheet_paths(zf: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in zf.namelist()
        if name.startswith("xl/worksheets/") and name.endswith(".xml") and "/_rels/" not in name
    )


def sheet_header_and_count(zf: zipfile.ZipFile, shared: list[str], sheet_path: str) -> SheetInfo:
    header: list[str] = []
    data_rows = 0
    with zf.open(sheet_path) as sheet:
        for _event, row in ET.iterparse(sheet, events=("end",)):
            if not row.tag.endswith("}row"):
                continue
            cells = {
                col_index(cell.attrib["r"]): cell_value(cell, shared)
                for cell in row.findall("a:c", NS)
                if "r" in cell.attrib
            }
            row_num = int(row.attrib.get("r", "0"))
            if row_num == 1:
                header = [cells.get(i, "") for i in range(max(cells) + 1)] if cells else []
            elif cells:
                data_rows += 1
            row.clear()
    return SheetInfo(path=sheet_path, header=header, data_rows=data_rows)


def select_worksheet(path: Path) -> SheetInfo:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sheets = [sheet_header_and_count(zf, shared, sheet_path) for sheet_path in worksheet_paths(zf)]
    candidates = [sheet for sheet in sheets if REQUIRED_COLUMNS.issubset(set(sheet.header))]
    if candidates:
        return max(candidates, key=lambda sheet: sheet.data_rows)

    details = "\n".join(f"- {sheet.path}: {sheet.header}" for sheet in sheets)
    required = ", ".join(sorted(REQUIRED_COLUMNS))
    raise ValueError(f"no worksheet contains all required fields ({required}). Actual worksheet fields:\n{details}")


def iter_xlsx_rows(path: Path, sheet_path: str) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        header: list[str] | None = None
        with zf.open(sheet_path) as sheet:
            for _event, row in ET.iterparse(sheet, events=("end",)):
                if not row.tag.endswith("}row"):
                    continue
                cells = {
                    col_index(cell.attrib["r"]): cell_value(cell, shared)
                    for cell in row.findall("a:c", NS)
                    if "r" in cell.attrib
                }
                row_num = int(row.attrib.get("r", "0"))
                if row_num == 1:
                    header = [cells.get(i, "") for i in range(max(cells) + 1)] if cells else []
                elif header is not None and cells:
                    item = {field: cells.get(i, "") for i, field in enumerate(header)}
                    item["source_row_index"] = str(row_num)
                    yield item
                row.clear()


def parse_excel_time(value: str) -> datetime:
    value = str(value).strip()
    if not value:
        raise ValueError("empty timestamp_s")
    return datetime(1899, 12, 30) + timedelta(days=float(value))


def format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON file: {path}: {exc}") from exc


def extract_vocab(data: Any) -> tuple[dict[str, int], set[str], dict[int, str], str]:
    if isinstance(data, dict):
        structure = "dict_with_apps" if "apps" in data else "dict_app_to_id"
        source = data.get("apps", data)
    elif isinstance(data, list):
        structure = "list"
        source = data
    else:
        raise ValueError("app_vocab.json must be a dict, list, or dict with apps")

    if isinstance(source, dict):
        vocab: dict[str, int] = {}
        next_id = 0
        for key, value in source.items():
            app = str(key).strip()
            if not app:
                continue
            if isinstance(value, int):
                app_id = int(value)
            elif isinstance(value, dict) and isinstance(value.get("id"), int):
                app_id = int(value["id"])
            else:
                app_id = next_id
            vocab[app] = app_id
            next_id = max(next_id, app_id + 1)
    elif isinstance(source, list):
        vocab = {}
        for idx, item in enumerate(source):
            if isinstance(item, str):
                app = item.strip()
            elif isinstance(item, dict):
                app = str(item.get("app") or item.get("name") or item.get("app_name") or "").strip()
            else:
                app = ""
            if app:
                vocab[app] = idx
    else:
        raise ValueError("unsupported apps structure in app_vocab.json")

    if not vocab:
        raise ValueError("app_vocab.json is empty")
    real_apps = {app for app in vocab if app not in SPECIAL_TOKENS}
    if not real_apps:
        raise ValueError("app_vocab.json has no real app names")

    id_to_app: dict[int, str] = {}
    for app, app_id in vocab.items():
        id_to_app.setdefault(app_id, app)
    return vocab, real_apps, id_to_app, structure


def event_action(data_event: str) -> str | None:
    event = str(data_event).strip().upper()
    if event in OPEN_EVENTS:
        return "open"
    if event in CLOSE_EVENTS:
        return "close"
    return None


def normalize_mapping_cell(value: str) -> str:
    normalized = str(value).strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    return normalized


def integer_text(value: str) -> int | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def resolve_app_mapping(raw_value: str, real_apps: set[str], id_to_app: dict[int, str]) -> AppMappingResult:
    value = normalize_mapping_cell(raw_value)
    if value.upper() in NULL_MAPPING_VALUES:
        return AppMappingResult("null")
    if value in SPECIAL_TOKENS:
        return AppMappingResult("special_token", value)
    if value in real_apps:
        return AppMappingResult("valid", value)

    app_id = integer_text(value)
    if app_id is None:
        return AppMappingResult("invalid")
    app = id_to_app.get(app_id)
    if app is None:
        return AppMappingResult("out_of_vocab")
    if app in SPECIAL_TOKENS:
        return AppMappingResult("special_token", app)
    if app not in real_apps:
        return AppMappingResult("out_of_vocab", app)
    return AppMappingResult("valid", app)


def write_counter(path: Path, title: str, counter: Counter[str] | Counter[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as fout:
        if title:
            fout.write(title + "\n")
        for key, count in counter.most_common():
            if isinstance(key, tuple):
                fout.write(" | ".join(key) + f" | {count}\n")
            else:
                fout.write(f"{key} | {count}\n")


def parse_opened_apps(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    return [item for item in value.split(";") if item]


def validate_same_timestamp_order(output_rows: list[dict[str, str]]) -> tuple[bool, int]:
    last_index: dict[tuple[str, str], int] = {}
    violations = 0
    for row in output_rows:
        key = (row["user_id"], row["timestamp"])
        source_idx = int(row["_source_row_index"])
        if key in last_index and source_idx < last_index[key]:
            violations += 1
        last_index[key] = source_idx
    return violations == 0, violations


def validate_output_order(output_rows: list[dict[str, str]]) -> int:
    violations = 0
    previous: tuple[str, str, int] | None = None
    for row in output_rows:
        current = (row["user_id"], row["timestamp"], int(row["_source_row_index"]))
        if previous is not None and current < previous:
            violations += 1
        previous = current
    return violations


def validate_per_user_time_order(output_rows: list[dict[str, str]]) -> int:
    previous_by_user: dict[str, tuple[str, int]] = {}
    violations = 0
    for row in output_rows:
        user_id = row["user_id"]
        current = (row["timestamp"], int(row["_source_row_index"]))
        previous = previous_by_user.get(user_id)
        if previous is not None and current < previous:
            violations += 1
        previous_by_user[user_id] = current
    return violations


def count_adjacent_same_app_violations(output_rows: list[dict[str, str]]) -> int:
    previous_by_user: dict[str, str] = {}
    violations = 0
    for row in output_rows:
        user_id = row["user_id"]
        app = row["foreground_app"]
        if previous_by_user.get(user_id) == app:
            violations += 1
        previous_by_user[user_id] = app
    return violations


def count_duplicate_opened_apps_violations(public_rows: list[dict[str, str]]) -> int:
    violations = 0
    for row in public_rows:
        opened = parse_opened_apps(row["opened_apps"])
        if len(opened) != len(set(opened)):
            violations += 1
    return violations


def count_close_removed_app_violations(output_rows: list[dict[str, str]]) -> int:
    violations = 0
    for row in output_rows:
        if row.get("_data_event", "") in CLOSE_EVENTS and row["foreground_app"] in parse_opened_apps(row["opened_apps"]):
            violations += 1
    return violations


def independent_recount_output_total(event_rows: list[dict[str, Any]]) -> int:
    last_app_by_user: dict[str, str] = {}
    total = 0
    for row in sorted(event_rows, key=lambda item: (item["user_id"], item["timestamp"], item["source_row_index"])):
        user_id = row["user_id"]
        app = row["app"]
        if last_app_by_user.get(user_id) != app:
            total += 1
        last_app_by_user[user_id] = app
    return total


def validate_vocab_bounds(public_rows: list[dict[str, str]], target_vocab: set[str]) -> tuple[list[str], list[str]]:
    foreground_apps = {row["foreground_app"] for row in public_rows if row["foreground_app"]}
    opened_apps = {app for row in public_rows for app in parse_opened_apps(row["opened_apps"])}
    return sorted(foreground_apps - target_vocab), sorted(opened_apps - target_vocab)


def resolve_input_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.exists():
        return path
    if path_text == str(DEFAULT_EXCEL):
        matches = sorted((ROOT / "data" / "vocab").glob("*100-interaction-jank.xlsx"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"input Excel not found: {path}")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fin:
        for chunk in iter(lambda: fin.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(args: argparse.Namespace) -> dict[str, Any]:
    excel_path = resolve_input_path(args.input)
    output_path = Path(args.output)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    target_vocab_data = load_json(Path(args.app_vocab))
    target_vocab_map, target_vocab, id_to_app, vocab_structure = extract_vocab(target_vocab_data)
    selected_sheet = select_worksheet(excel_path)

    user_field = "user_id" if "user_id" in selected_sheet.header else "name"
    if user_field not in selected_sheet.header:
        raise ValueError("selected worksheet is missing user_id/name field")

    stats: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    unknown_event_all: Counter[str] = Counter()
    bad_timestamp: Counter[str] = Counter()
    invalid_mapping: Counter[tuple[str, str]] = Counter()
    top_apps: Counter[str] = Counter()
    event_rows: list[dict[str, Any]] = []
    missing_required_rows = 0
    no_user_rows = 0

    for row in iter_xlsx_rows(excel_path, selected_sheet.path):
        stats["excel_raw_data_rows"] += 1
        event = str(row.get("data_event", "")).strip().upper()
        event_counts[event] += 1
        action = event_action(event)
        if action is None:
            unknown_event_all[event] += 1

        if not row.get("timestamp_s", "").strip():
            missing_required_rows += 1
            continue

        user_id = row.get(user_field, "").strip()
        if not user_id:
            no_user_rows += 1
            continue

        try:
            ts = parse_excel_time(row.get("timestamp_s", ""))
        except Exception:
            bad_timestamp[row.get("timestamp_s", "")] += 1
            continue

        stats["parsed_row_total"] += 1

        mapping_result = resolve_app_mapping(row.get("app_vocab_mapping", ""), target_vocab, id_to_app)
        if mapping_result.status == "null":
            stats["null_app_mapping_row_total"] += 1
            continue
        if mapping_result.status == "invalid":
            stats["invalid_app_mapping_row_total"] += 1
            invalid_mapping[(normalize_mapping_cell(row.get("app_vocab_mapping", "")), row.get("process_name", "").strip())] += 1
            continue
        if mapping_result.status == "special_token":
            stats["special_token_row_total"] += 1
            continue
        if mapping_result.status == "out_of_vocab":
            stats["out_of_vocab_app_mapping_row_total"] += 1
            continue

        app = mapping_result.app
        stats["valid_app_mapping_row_total"] += 1
        stats["candidate_app_event_total"] += 1
        top_apps[app] += 1
        event_rows.append(
            {
                "source_row_index": int(row["source_row_index"]),
                "user_id": user_id,
                "timestamp": ts,
                "process_name": row.get("process_name", "").strip(),
                "data_event": event,
                "app": app,
            }
        )

    event_rows.sort(key=lambda item: (item["user_id"], item["timestamp"], item["source_row_index"]))

    last_app_by_user: dict[str, str] = {}
    opened_apps_by_user: dict[str, list[str]] = defaultdict(list)
    opened_app_sets_by_user: dict[str, set[str]] = defaultdict(set)
    output_rows: list[dict[str, str]] = []

    for row in event_rows:
        app = row["app"]
        user_id = row["user_id"]
        event = row["data_event"]
        previous_app = last_app_by_user.get(user_id)
        is_app_switch = previous_app != app

        opened_apps = opened_apps_by_user[user_id]
        opened_set = opened_app_sets_by_user[user_id]
        if event in OPEN_EVENTS:
            if app not in opened_set:
                opened_set.add(app)
                opened_apps.append(app)
                stats["background_app_added_total"] += 1
            else:
                stats["background_duplicate_open_total"] += 1
        elif event in CLOSE_EVENTS:
            if app in opened_set:
                opened_set.remove(app)
                opened_apps.remove(app)
                stats["background_app_removed_total"] += 1
            else:
                stats["background_close_not_active_total"] += 1

        if is_app_switch:
            output_rows.append(
                {
                    "user_id": user_id,
                    "timestamp": format_time(row["timestamp"]),
                    "foreground_app": app,
                    "opened_apps": ";".join(opened_apps),
                    "user_group": args.user_group,
                    "_source_row_index": str(row["source_row_index"]),
                    "_data_event": event,
                }
            )
            stats["app_switch_event_total"] += 1
            stats["output_event_total"] += 1
        else:
            stats["consecutive_same_app_folded_total"] += 1

        last_app_by_user[user_id] = app

    _order_ok, order_violations = validate_same_timestamp_order(output_rows)
    output_order_violations = validate_output_order(output_rows)
    per_user_time_order_violations = validate_per_user_time_order(output_rows)
    public_rows = [{key: row[key] for key in OUTPUT_FIELDS} for row in output_rows]
    foreground_outside, opened_outside = validate_vocab_bounds(public_rows, target_vocab)
    adjacent_same_app_violations = count_adjacent_same_app_violations(output_rows)
    duplicate_opened_apps_violations = count_duplicate_opened_apps_violations(public_rows)
    close_removed_app_violations = count_close_removed_app_violations(output_rows)
    independent_output_total = independent_recount_output_total(event_rows)

    if output_order_violations:
        raise RuntimeError(f"output order violations: {output_order_violations}")
    if per_user_time_order_violations:
        raise RuntimeError(f"per-user time order violations: {per_user_time_order_violations}")
    if foreground_outside:
        raise RuntimeError(f"foreground_app outside app_vocab.json: {foreground_outside[:20]}")
    if opened_outside:
        raise RuntimeError(f"opened_apps outside app_vocab.json: {opened_outside[:20]}")
    if order_violations:
        raise RuntimeError(f"same timestamp order violations: {order_violations}")
    if adjacent_same_app_violations:
        raise RuntimeError(f"adjacent same-app output violations: {adjacent_same_app_violations}")
    if duplicate_opened_apps_violations:
        raise RuntimeError(f"duplicate opened_apps violations: {duplicate_opened_apps_violations}")
    if close_removed_app_violations:
        raise RuntimeError(f"close removed app violations: {close_removed_app_violations}")
    if independent_output_total != len(output_rows):
        raise RuntimeError(
            f"independent recount mismatch: recount={independent_output_total}, output={len(output_rows)}"
        )
    if stats["candidate_app_event_total"] != stats["consecutive_same_app_folded_total"] + stats["app_switch_event_total"]:
        raise RuntimeError("candidate_app_event_total does not equal folded + app switch totals")
    if stats["app_switch_event_total"] != stats["output_event_total"]:
        raise RuntimeError("app_switch_event_total does not equal output_event_total")
    for row in public_rows:
        opened = parse_opened_apps(row["opened_apps"])
        if len(opened) != len(set(opened)):
            raise RuntimeError(f"duplicate app in opened_apps: {row}")
        if any(app in SPECIAL_TOKENS or app.upper() in NULL_MAPPING_VALUES for app in opened):
            raise RuntimeError(f"invalid opened_apps value: {row}")
        foreground = row["foreground_app"]
        if foreground and (foreground in SPECIAL_TOKENS or foreground.upper() in NULL_MAPPING_VALUES):
            raise RuntimeError(f"invalid foreground_app value: {row}")

    previous_output_sha = hash_file(output_path) if output_path.exists() else ""
    with output_path.open("w", encoding="utf-8-sig", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(public_rows)
    current_output_sha = hash_file(output_path)

    write_counter(output_dir / "event_type_check.txt", "data_event | count", event_counts)
    write_counter(output_dir / "unknown_event.log", "data_event | count", unknown_event_all)
    write_counter(output_dir / "bad_timestamp.log", "timestamp_s | count", bad_timestamp)
    write_counter(output_dir / "invalid_app_vocab_mapping.log", "app_vocab_mapping | process_name | count", invalid_mapping)

    foreground_apps = {row["foreground_app"] for row in public_rows if row["foreground_app"]}
    opened_apps = {app for row in public_rows for app in parse_opened_apps(row["opened_apps"])}
    users = {row["user_id"] for row in public_rows}
    same_timestamp_groups = Counter((row["user_id"], row["timestamp"]) for row in public_rows)

    checks: dict[str, Any] = {
        "app_vocab_json_structure": vocab_structure,
        "selected_worksheet": selected_sheet.path,
        "selected_worksheet_data_rows": selected_sheet.data_rows,
        "excel_raw_data_rows": stats["excel_raw_data_rows"],
        "parsed_row_total": stats["parsed_row_total"],
        "parse_failed_row_total": sum(bad_timestamp.values()),
        "missing_required_row_total": missing_required_rows,
        "no_user_id_row_total": no_user_rows,
        "valid_app_mapping_row_total": stats["valid_app_mapping_row_total"],
        "null_app_mapping_row_total": stats["null_app_mapping_row_total"],
        "invalid_app_mapping_row_total": stats["invalid_app_mapping_row_total"],
        "special_token_row_total": stats["special_token_row_total"],
        "out_of_vocab_app_mapping_row_total": stats["out_of_vocab_app_mapping_row_total"],
        "candidate_app_event_total": stats["candidate_app_event_total"],
        "consecutive_same_app_folded_total": stats["consecutive_same_app_folded_total"],
        "app_switch_event_total": stats["app_switch_event_total"],
        "output_event_total": stats["output_event_total"],
        "background_app_added_total": stats["background_app_added_total"],
        "background_app_removed_total": stats["background_app_removed_total"],
        "background_duplicate_open_total": stats["background_duplicate_open_total"],
        "background_close_not_active_total": stats["background_close_not_active_total"],
        "final_user_total": len(users),
        "foreground_app_total": len(foreground_apps),
        "opened_apps_app_total": len(opened_apps),
        "target_vocab_app_total": len(target_vocab),
        "foreground_app_outside_vocab_total": len(foreground_outside),
        "opened_apps_outside_vocab_total": len(opened_outside),
        "same_timestamp_group_total": sum(1 for count in same_timestamp_groups.values() if count > 1),
        "same_timestamp_order_violation_total": order_violations,
        "per_user_time_order_violation_total": per_user_time_order_violations,
        "adjacent_same_app_violation_total": adjacent_same_app_violations,
        "duplicate_opened_apps_violation_total": duplicate_opened_apps_violations,
        "close_removed_app_violation_total": close_removed_app_violations,
        "independent_recount_output_total": independent_output_total,
        "independent_recount_matches_output": str(independent_output_total == len(output_rows)).lower(),
        "repeat_run_consistency": "true"
        if previous_output_sha and previous_output_sha == current_output_sha
        else ("no_previous_output" if not previous_output_sha else "false"),
        "previous_output_sha256": previous_output_sha,
        "output_sha256": current_output_sha,
        "input": str(excel_path),
        "output": str(output_path),
    }

    with (output_dir / "app_events_check.txt").open("w", encoding="utf-8") as fout:
        for key, value in checks.items():
            fout.write(f"{key}: {value}\n")
        fout.write("\ntop_30_apps:\n")
        for app, count in top_apps.most_common(30):
            fout.write(f"{app} | {count}\n")
        fout.write("\ntop_invalid_app_vocab_mapping_values:\n")
        for (raw_mapping, process_name), count in invalid_mapping.most_common(100):
            fout.write(f"{raw_mapping} | {process_name} | {count}\n")

    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate app_events.csv from Excel app_vocab_mapping values.")
    parser.add_argument("--input", default=str(DEFAULT_EXCEL))
    parser.add_argument("--app-vocab", default=str(DEFAULT_APP_VOCAB))
    parser.add_argument("--duration-vocab", default=str(DEFAULT_APP_VOCAB), help="Deprecated compatibility alias.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--user-group", default=DEFAULT_USER_GROUP)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.app_vocab == str(DEFAULT_APP_VOCAB) and args.duration_vocab != str(DEFAULT_APP_VOCAB):
        args.app_vocab = args.duration_vocab
    checks = generate(args)
    for key, value in checks.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
