#!/usr/bin/env python3
"""Run Douyu operation-VMA trials and export a compact core dataset."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

from build_douyu_vma_dataset import build_dataset, map_fixed_window_sequence
from douyu_v6_session import DouyuSession, HdcError, now_iso
from export_douyu_vma_dataset_core import export_dataset


def _safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _load_catalog(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    operations = value.get("operations")
    if not isinstance(operations, list) or len(operations) < 1:
        raise ValueError("斗鱼操作目录至少需要 1 个操作")
    labels = [item.get("label") for item in operations]
    ids = [item.get("label_id") for item in operations]
    if len(labels) != len(set(labels)) or len(ids) != len(set(ids)):
        raise ValueError("斗鱼操作目录存在重复 label 或 label_id")
    return value


def _session_args(args: argparse.Namespace, trial_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        target=args.target,
        out=trial_dir,
        device_dir=args.device_dir,
        no_build=args.no_build,
        launch_wait_s=args.launch_wait_s,
        ui_wait_s=args.ui_wait_s,
        room_wait_s=args.room_wait_s,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        search_term=args.search_term,
        second_search_term=args.second_search_term,
        baseline_window_count=args.baseline_window_count,
        baseline_window_s=args.baseline_window_s,
        action_window_s=args.action_window_s,
        post_window_s=args.post_window_s,
    )


def _ensure_home(session: DouyuSession) -> None:
    if session.state == "background":
        session.restore_app()
    if session.state in {"room", "results"}:
        session.back_to_home()
    if session.state not in {"home"}:
        session.reset_home()


def _ensure_results(session: DouyuSession) -> None:
    _ensure_home(session)
    session.search_live_room()


def _ensure_room(session: DouyuSession) -> None:
    if session.state == "background":
        session.restore_app()
    if session.state == "home":
        session.search_live_room()
    if session.state == "results":
        session.enter_live_room()
    if session.state != "room":
        session.reset_home()
        session.search_live_room()
        session.enter_live_room()


def _prepare(session: DouyuSession, label: str) -> None:
    if label == "SEARCH_LIVE_ROOM":
        _ensure_home(session)
    elif label == "ENTER_LIVE_ROOM":
        _ensure_results(session)
    elif label in {"SWITCH_VIDEO_TAB", "SWITCH_CHAT_TAB", "PLAY_PAUSE_VIDEO", "SCROLL_LIVE_ROOM"}:
        _ensure_room(session)
    elif label == "BACK_TO_HOME":
        _ensure_room(session)
    elif label == "BACKGROUND_APP":
        _ensure_home(session)
    elif label == "RESTORE_APP":
        _ensure_home(session)
        session.background_app()
    elif label == "RESTART_APP":
        _ensure_home(session)
    elif label == "SWITCH_LIVE_ROOM":
        _ensure_room(session)
    else:
        raise ValueError(f"未定义的斗鱼操作: {label}")


def _action(session: DouyuSession, label: str) -> Callable[[], dict[str, Any]]:
    actions: dict[str, Callable[[], dict[str, Any]]] = {
        "SEARCH_LIVE_ROOM": session.search_live_room,
        "ENTER_LIVE_ROOM": session.enter_live_room,
        "SWITCH_VIDEO_TAB": session.switch_video_tab,
        "SWITCH_CHAT_TAB": session.switch_chat_tab,
        "PLAY_PAUSE_VIDEO": session.play_pause_video,
        "SCROLL_LIVE_ROOM": session.scroll_live_room,
        "BACK_TO_HOME": session.back_to_home,
        "BACKGROUND_APP": session.background_app,
        "RESTORE_APP": session.restore_app,
        "RESTART_APP": session.restart_app,
        "SWITCH_LIVE_ROOM": session.switch_live_room,
    }
    return actions[label]


def _append_sequence(root: Path, sample: dict[str, Any]) -> None:
    path = root / "operation_window_sequences.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_safe(sample), ensure_ascii=False, sort_keys=True) + "\n")


def _run_trial(args: argparse.Namespace, root: Path, trial_number: int, catalog: dict[str, Any]) -> dict[str, Any]:
    trial_id = f"trial_{trial_number:03d}"
    trial_dir = root / "temporary_raw" / trial_id
    trial_dir.mkdir(parents=True, exist_ok=False)
    session_id = f"douyu_vma_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{trial_number:03d}"
    record: dict[str, Any] = {
        "trial_id": trial_id,
        "trial_dir": str(Path("temporary_raw") / trial_id),
        "session_id": session_id,
        "status": "failed",
        "started_at": now_iso(),
        "operation_samples": [],
    }
    session: DouyuSession | None = None
    try:
        session = DouyuSession(_session_args(args, trial_dir), trial_dir, session_id)
        session.verify_access()
        session.build_and_push()
        session.reset_home()
        record.update({
            "device_target": session.device.target,
            "startup_state": session.state,
            "expected_sample_count": len(catalog["operations"]),
        })
        catalog_by_label = {str(item["label"]): item for item in catalog["operations"]}
        for item in catalog["operations"]:
            label = str(item["label"])
            _prepare(session, label)
            sample = session.collect_labeled_operation(
                trial_id=trial_id,
                label_id=int(item["label_id"]),
                operation_label=label,
                family=str(item.get("family", "")),
                precondition=str(item.get("precondition", "")),
                action=_action(session, label),
            )
            sample["trial_dir"] = record["trial_dir"]
            sample["catalog_description"] = item.get("description", "")
            sample["sequence"] = map_fixed_window_sequence(
                operation_execution_id=sample["execution_id"],
                operation_id=label,
                baseline_group_id=f"{sample['execution_id']}_baseline",
                baseline_windows=sample["baseline_windows"],
                operation_windows=sample["operation_windows"],
            )
            _append_sequence(root, sample)
            record["operation_samples"].append(sample["sample_id"])
        record.update({
            "status": "success",
            "ended_at": now_iso(),
            "actual_sample_count": len(record["operation_samples"]),
        })
        return record
    except Exception as exc:
        record.update({
            "status": "failed",
            "ended_at": now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
        })
        (trial_dir / "trial_failure.json").write_text(
            json.dumps(_safe(record), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record
    finally:
        if session is not None:
            session.close()


def _write_failures(root: Path, records: list[dict[str, Any]]) -> None:
    failures = [record for record in records if record.get("status") != "success"]
    if not failures:
        return
    fields = ["trial_id", "session_id", "status", "started_at", "ended_at", "error"]
    with (root / "trial_failures.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(failures)


def _cleanup_intermediate(root: Path, core_dir: Path, zip_path: Path) -> None:
    for path in list(root.iterdir()):
        if path == core_dir or path == zip_path or path.name == "run_summary.json":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-Target", "--target", default="")
    parser.add_argument("-Trials", "--trials", type=int, default=1)
    parser.add_argument("-Out", "--out", type=Path, default=None)
    parser.add_argument("-NoBuild", "--no-build", action="store_true")
    parser.add_argument("--keep-raw", action="store_true", help="保留原始 VMA 报告，默认清理")
    parser.add_argument("--device-dir", default="/data/local/tmp/mem_analyze_v6")
    parser.add_argument("--launch-wait-s", type=float, default=5.0)
    parser.add_argument("--ui-wait-s", type=float, default=2.0)
    parser.add_argument("--room-wait-s", type=float, default=4.0)
    parser.add_argument("--screen-width", type=int, default=3120)
    parser.add_argument("--screen-height", type=int, default=2080)
    parser.add_argument("--search-term", default="pubg")
    parser.add_argument("--second-search-term", default="music")
    parser.add_argument("--baseline-window-count", type=int, default=2)
    parser.add_argument("--baseline-window-s", type=float, default=2.0)
    parser.add_argument("--action-window-s", type=float, default=8.0)
    parser.add_argument("--post-window-s", type=float, default=5.0)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).with_name("douyu_operation_catalog.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.trials < 1:
        raise SystemExit("-Trials 必须大于等于 1")
    catalog_path = args.catalog.resolve()
    catalog = _load_catalog(catalog_path)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = (args.out or Path.cwd() / f"douyu_vma_run_{timestamp}").resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"输出目录非空，为避免覆盖而停止: {root}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(catalog_path, root / "douyu_operation_catalog.json")
    shutil.copy2(catalog_path, root / "operation_catalog.json")
    records: list[dict[str, Any]] = []
    for trial_number in range(1, args.trials + 1):
        print(f"[douyu-vma] trial {trial_number}/{args.trials}: trial_{trial_number:03d}", flush=True)
        record = _run_trial(args, root, trial_number, catalog)
        records.append(record)
        if record.get("status") == "success":
            print(f"[douyu-vma] {record['trial_id']}: success", flush=True)
        else:
            print(f"[douyu-vma] {record['trial_id']}: failed | {record.get('error', '')}", flush=True)
    _write_failures(root, records)
    success_count = sum(record.get("status") == "success" for record in records)
    if not (root / "operation_window_sequences.jsonl").is_file():
        raise SystemExit("没有任何成功样本，未生成核心数据集")
    build_dataset(root, catalog_path)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    core_dir = root / f"douyu_vma_dataset_core_{timestamp}"
    zip_path = core_dir.with_suffix(".zip")
    exported = export_dataset(argparse.Namespace(
        root=root,
        output_dir=core_dir,
        zip_path=zip_path,
        catalog=catalog_path,
        expected_label_count=len(catalog["operations"]),
        allow_incomplete_trials=False,
        include_raw_vector=True,
        no_zip=False,
    ))
    core_dir = Path(exported["output_dir"])
    zip_path = Path(exported["zip_path"])
    if not args.keep_raw:
        _cleanup_intermediate(root, core_dir, zip_path)
    summary = {
        "app_id": "douyu_pc",
        "trials_requested": args.trials,
        "trials_completed": success_count,
        "core_dataset_dir": str(core_dir),
        "core_dataset_zip": str(zip_path),
        "raw_reports_retained": bool(args.keep_raw),
        "catalog_operation_count": len(catalog["operations"]),
    }
    (root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if success_count else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HdcError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"[douyu-vma] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
