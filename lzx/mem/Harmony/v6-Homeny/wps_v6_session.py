#!/usr/bin/env python3
"""Run a real HarmonyOS WPS document workload and collect v6 reports.

The runner intentionally keeps the device UI actions and the memory evidence
in one auditable session.  Every measured stage follows the same order:

    before snapshot -> clear_refs -> UI operation -> settle -> after snapshot
    -> collect all WPS PID reports -> pull and hash every report

WPS uses an XComponent editor on this target, so the editor itself is driven
by coordinates and the saved-document/file-system checks are used as the
stronger success evidence.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Mapping

from operation_vma_mapping import (
    VmaJsonError,
    append_jsonl,
    load_config as load_vma_mapping_config,
    load_vma_jsonl,
    map_operation_stage,
    write_stage_outputs,
)
from fixed_window_mapping import (
    aggregate_execution,
    classify_fixed_window,
    fixed_window_config,
    map_fixed_window,
)
from process_role_resolver import enrich_process_rows, parse_proc_stat_starttime


BUNDLE = "cn.wps.office.hap"
ABILITY = "PromeAbility"
MODULE = "prome"
DEFAULT_DEVICE_DIR = "/data/local/tmp/mem_analyze_v6"
DEFAULT_DEVICE_OUT_ROOT = "/data/local/tmp/mem_analyze_v6/wps_reports"
DOCUMENT_ROOT = "/storage/media/100/local/files/Docs"
DESKTOP_ROOT = "/storage/media/100/local/files/Docs/Desktop"
DEFAULT_TEST_SERIAL = "WPS-TEST-0001"

SAMPLE_KINDS = ("BASELINE", "OPERATION", "POST_LAUNCH")

LEGACY_OPERATION_FIELDS = [
    "session_id", "index", "stage", "label", "operation", "success", "status",
    "started_at", "ended_at", "before_pids", "after_pids",
    "operation_started_at", "operation_ended_at", "operation_elapsed_s",
    "settle_wait_s", "observation_wait_s", "clear_refs_elapsed_s",
    "collection_started_at", "collection_ended_at", "collection_elapsed_s",
    "report_pull_started_at", "report_pull_ended_at", "report_pull_elapsed_s",
    "stage_total_elapsed_s", "phase_elapsed_s", "report_count", "report",
    "device_report_count", "local_report_count", "matched_report_count",
    "hash_mismatch_count", "missing_local_count", "missing_device_count",
    "document_path", "document_size_bytes", "document_mtime", "error",
]

NEW_OPERATION_FIELDS = [
    "baseline_enabled", "baseline_status", "baseline_unavailable_reason", "baseline_state",
    "sample_semantics", "baseline_started_at", "baseline_ended_at",
    "baseline_clear_refs_started_at", "baseline_clear_refs_ended_at", "baseline_clear_refs_elapsed_s",
    "baseline_window_started_at", "baseline_window_ended_at", "baseline_window_s",
    "baseline_collection_started_at", "baseline_collection_ended_at", "baseline_collection_elapsed_s",
    "baseline_report_count", "baseline_report", "baseline_jsonl_report",
    "operation_clear_refs_started_at", "operation_clear_refs_ended_at", "operation_clear_refs_elapsed_s",
    "operation_window_started_at", "operation_window_ended_at", "operation_window_s",
    "operation_collection_started_at", "operation_collection_ended_at", "operation_collection_elapsed_s",
    "operation_jsonl_report_count", "operation_jsonl_report", "post_launch_report", "post_launch_jsonl_report",
    "paired_process_count", "paired_vma_count", "strong_file_vma_count", "weak_file_vma_count",
    "strong_anon_vma_count", "weak_anon_vma_count", "new_process_without_baseline_count",
    "exited_process_count", "pid_only_match_count", "split_merge_match_count", "window_mismatch_count",
    "low_quality_vma_count", "collection_quality", "process_match_quality", "vma_match_quality",
    "baseline_quality", "window_quality", "activity_quality", "identity_confidence",
    "vma_mapping_status", "vma_mapping_error",
    "fixed_windows_enabled", "target_window_s", "baseline_window_count",
    "baseline_valid_window_count", "operation_window_count", "operation_valid_window_count",
    "operation_partial_window_count", "operation_overrun_window_count",
    "operation_severe_overrun_count", "window_sequence_path",
    "fixed_window_mapping_status", "fixed_window_error",
]

HASH_FIELDS = [
    "report", "device_path", "local_path", "device_sha256", "local_sha256", "match",
    "sample_kind", "report_format", "stage", "pid",
]

# HarmonyOS key codes used here as individual keys.  A multi-key keyEvent is
# not a chord on this device; Ctrl+N/Ctrl+S therefore is deliberately avoided.
KEY_HOME = "1"
KEY_ENTER = "2054"
KEY_DPAD_LEFT = "2014"
KEY_DPAD_RIGHT = "2015"
UI_TEXT_CHUNK_SIZE = 60
UI_TEXT_SETTLE_S = 0.25
UI_TEXT_BATCH_SIZE = 8

SCREENSHOT_NAMES = (
    "01_open_wps",
    "02_new_word",
    "03_write_metadata",
    "04_heavy_edit_scroll",
    "05_save_document",
    "06_background",
    "07_foreground",
    "08_reopen_saved_document",
    "09_reopen_edit_scroll",
    "close_before_reopen",
    "close_final",
)


class HdcError(RuntimeError):
    """A failed host-to-device command."""


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def q(value: str) -> str:
    return shlex.quote(value)


def find_hdc() -> str:
    value = os.environ.get("HDC", "") or shutil.which("hdc")
    if value:
        return value
    candidates = (
        Path.home() / "Library/OpenHarmony/Sdk/23/toolchains/hdc",
        Path("/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc"),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise HdcError("找不到 hdc；请先 source scripts/setup_env.sh 或设置 HDC")


def run_host(command: list[str], *, check: bool = True, timeout_s: float = 180.0) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise HdcError(f"命令超时: {' '.join(command)}") from exc
    if check and result.returncode != 0:
        raise HdcError(f"命令失败({result.returncode}): {' '.join(command)}\n{result.stdout.strip()}")
    return result


def list_targets(hdc: str) -> list[str]:
    result = run_host([hdc, "list", "targets"])
    targets: list[str] = []
    for line in result.stdout.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token and not token.startswith("[") and token not in targets:
            targets.append(token)
    return targets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Device:
    def __init__(self, hdc: str, target: str):
        self.hdc = hdc
        self.target = target

    def run(self, *args: str, check: bool = True, timeout_s: float = 180.0) -> str:
        result = run_host([self.hdc, "-t", self.target, *args], check=False, timeout_s=timeout_s)
        output = result.stdout.strip()
        lower = output.lower()
        remote_error = any(
            marker in lower
            for marker in ("error code:", "failed to start ability", "[fail]", "no such file")
        )
        if check and (result.returncode != 0 or remote_error):
            raise HdcError(f"设备命令失败({result.returncode}): {output}")
        return output

    def shell(self, command: str, *, check: bool = True, timeout_s: float = 180.0) -> str:
        return self.run("shell", command, check=check, timeout_s=timeout_s)

    def send(self, local: Path, remote: str) -> str:
        return self.run("file", "send", str(local), remote)

    def recv(self, remote: str, local: Path) -> str:
        local.parent.mkdir(parents=True, exist_ok=True)
        return self.run("file", "recv", remote, str(local))


def process_snapshot(device: Device) -> list[dict[str, Any]]:
    output = device.shell("ps -A -o PID,PPID,UID,VSZ,RSS,ARGS", check=False)
    first_line = output.splitlines()[0] if output.splitlines() else ""
    extended_columns = all(name in first_line.split() for name in ("PID", "PPID", "UID", "VSZ", "RSS", "ARGS"))
    if not extended_columns:
        output = device.shell("ps -ef", check=False)
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        if extended_columns:
            fields = line.strip().split(maxsplit=5)
            if len(fields) < 6 or not fields[0].isdigit() or BUNDLE not in fields[5]:
                continue
            pid, ppid, uid, vsz_kb, rss_kb, args = fields
        else:
            fields = line.strip().split(maxsplit=7)
            if len(fields) < 8 or not fields[1].isdigit() or BUNDLE not in fields[7]:
                continue
            uid, pid, ppid, _cpu, _start, _tty, _time, args = fields
            status = device.shell(f"cat /proc/{pid}/status", check=False)
            vsz_match = re.search(r"(?m)^VmSize:\s*(\d+)\s+kB", status)
            rss_match = re.search(r"(?m)^VmRSS:\s*(\d+)\s+kB", status)
            vsz_kb = vsz_match.group(1) if vsz_match else ""
            rss_kb = rss_match.group(1) if rss_match else ""
        stat_text = device.shell(f"cat /proc/{pid}/stat", check=False)
        starttime = parse_proc_stat_starttime(stat_text)
        comm = device.shell(f"cat /proc/{pid}/comm", check=False).strip()
        exe_path = device.shell(f"readlink /proc/{pid}/exe", check=False).strip()
        cmdline = device.shell(f"cat /proc/{pid}/cmdline | tr '\\0' ' '", check=False).strip()
        rows.append({
            "pid": pid,
            "ppid": ppid,
            "uid": uid,
            "vsz_kb": vsz_kb,
            "rss_kb": rss_kb,
            "args": args,
            "cmdline": cmdline or args,
            "comm": comm,
            "exe_path": exe_path,
            "process_starttime": starttime,
            "starttime_available": starttime is not None,
        })
    return enrich_process_rows(rows)


def parse_collector_report_paths(output: str) -> dict[str, list[str]]:
    stable_md: list[str] = []
    stable_jsonl: list[str] = []
    legacy_md: list[str] = []
    for line in output.splitlines():
        if line.startswith("REPORT_MD="):
            value = line.partition("=")[2].strip()
            if value and value not in stable_md:
                stable_md.append(value)
        elif line.startswith("REPORT_JSONL="):
            value = line.partition("=")[2].strip()
            if value and value not in stable_jsonl:
                stable_jsonl.append(value)
        else:
            match = re.search(r"报告已写入:\s*(\S+)$", line)
            if match and match.group(1) not in legacy_md:
                legacy_md.append(match.group(1))
    return {"MARKDOWN": stable_md or legacy_md, "JSONL": stable_jsonl}


def report_directory(session_root: Path, sample_kind: str, stage: str) -> Path:
    roots = {
        "BASELINE": "baseline_reports",
        "OPERATION": "operation_reports",
        "POST_LAUNCH": "post_launch_reports",
    }
    if sample_kind not in roots:
        raise ValueError(f"unsupported sample kind: {sample_kind}")
    return session_root / roots[sample_kind] / stage


def stage_baseline_semantics(stage: str) -> dict[str, str]:
    if stage == "01_open_wps":
        return {
            "baseline_status": "NOT_APPLICABLE",
            "baseline_unavailable_reason": "NO_PREEXISTING_WPS_PROCESS",
            "sample_semantics": "POST_LAUNCH_ACTIVITY",
            "baseline_state": "NO_PREEXISTING_WPS_PROCESS",
        }
    states = {
        "06_background": "FOREGROUND_IDLE",
        "07_foreground": "BACKGROUND_IDLE",
        "08_reopen_saved_document": "POST_LAUNCH_PRE_DOCUMENT_IDLE",
    }
    return {
        "baseline_status": "ENABLED",
        "baseline_unavailable_reason": "",
        "sample_semantics": "BASELINE_SUBTRACTED_OPERATION_ACTIVITY",
        "baseline_state": states.get(stage, "CURRENT_STATE_IDLE"),
    }


def parse_device_documents(output: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for line in output.splitlines():
        path, sep, rest = line.partition("|")
        if not sep:
            continue
        size_text, sep, mtime = rest.partition("|")
        if not sep or not path.lower().endswith((".docx", ".doc", ".wps")):
            continue
        try:
            size = int(size_text)
        except ValueError:
            continue
        documents.append({"path": path, "size_bytes": size, "mtime": mtime})
    return documents


def phase_pids(rows: list[dict[str, str]]) -> list[str]:
    return [row["pid"] for row in rows]


def parse_report_metrics(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def number(pattern: str) -> int:
        match = re.search(pattern, text, re.MULTILINE)
        return int(match.group(1).replace(",", "")) if match else 0

    pid_match = re.search(r"\|\s*PID\s*\|\s*`?(\d+)", text)
    name_match = re.search(r"\|\s*进程名\s*\|\s*`?([^|`\n]+)", text)
    return {
        "pid": pid_match.group(1) if pid_match else "",
        "process_name": name_match.group(1).strip() if name_match else "",
        "rss_kib": number(r"\|\s*Rss\s*\|[^\n]*?([\d,]+)\s*KiB"),
        "pss_kib": number(r"\|\s*Pss\s*\|[^\n]*?([\d,]+)\s*KiB"),
        "referenced_kib": number(r"\|\s*Referenced\s*\|[^\n]*?([\d,]+)\s*KiB"),
        "swap_kib": number(r"\|\s*Swap\s*\|[^\n]*?([\d,]+)\s*KiB"),
    }


class Session:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.hdc = find_hdc()
        targets = list_targets(self.hdc)
        if args.target:
            if args.target not in targets:
                raise HdcError(f"指定设备不在线: {args.target}; 当前设备: {targets}")
            target = args.target
        elif len(targets) == 1:
            target = targets[0]
        elif not targets:
            raise HdcError("hdc list targets 为空")
        else:
            raise HdcError(f"检测到多个设备，请用 --target 指定: {targets}")
        self.device = Device(self.hdc, target)
        self.session_timestamp = args.session_id or dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"wps_v6_{self.session_timestamp}" if not self.session_timestamp.startswith("wps_v6_") else self.session_timestamp
        self.script_dir = Path(__file__).resolve().parent
        self.local_out = Path(args.out).expanduser() if args.out else self.script_dir / "hdc_out" / f"wps_session_{self.session_id}"
        self.local_out.mkdir(parents=True, exist_ok=True)
        config_path = Path(args.vma_mapping_config).expanduser() if args.vma_mapping_config else self.script_dir / "vma_mapping_config.json"
        self.vma_mapping_config = load_vma_mapping_config(config_path)
        self.vma_mapping_config["idle_baseline"]["enabled"] = bool(args.idle_baseline)
        self.vma_mapping_config["idle_baseline"]["window_s"] = float(args.baseline_window_s)
        configured_fixed = fixed_window_config(self.vma_mapping_config)
        configured_fixed["enabled"] = bool(getattr(args, "fixed_windows", configured_fixed["enabled"]))
        configured_fixed["target_window_s"] = float(
            getattr(args, "fixed_window_s", configured_fixed["target_window_s"])
        )
        configured_fixed["baseline_window_count"] = int(
            getattr(args, "baseline_window_count", configured_fixed["baseline_window_count"])
        )
        configured_fixed["ok_tolerance_s"] = float(
            getattr(args, "fixed_window_ok_tolerance_s", configured_fixed["ok_tolerance_s"])
        )
        self.vma_mapping_config["fixed_windows"] = configured_fixed
        self.vma_mapping_dir = self.local_out / "vma_mapping"
        self.vma_mapping_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.local_out / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.device_out = f"{args.device_out.rstrip('/')}/wps_session_{self.session_id}"
        self.device_screenshot_out = f"{args.device_dir.rstrip('/')}/wps_screenshots/{self.session_id}"
        self.device_dir = args.device_dir.rstrip("/")
        self.device_bin = f"{self.device_dir}/mem_analyze-v6"
        self.operations_path = self.local_out / "operations.csv"
        self.operations_file = self.operations_path.open("w", encoding="utf-8", newline="")
        self.operation_fields = LEGACY_OPERATION_FIELDS + NEW_OPERATION_FIELDS
        self.operations = csv.DictWriter(self.operations_file, fieldnames=self.operation_fields)
        self.operations.writeheader()
        self.operations_file.flush()
        self.hash_path = self.local_out / "report_hashes.csv"
        self.hash_file = self.hash_path.open("w", encoding="utf-8", newline="")
        self.hashes = csv.DictWriter(
            self.hash_file,
            fieldnames=HASH_FIELDS,
        )
        self.hashes.writeheader()
        self.hash_file.flush()
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.timing_records: list[dict[str, Any]] = []
        self.report_records: list[dict[str, Any]] = []
        self.device_report_hashes: dict[str, str] = {}
        self.local_report_hashes: dict[str, str] = {}
        self.screenshots: list[str] = []
        self.collector_local: Path | None = None
        self.document_baseline: dict[str, tuple[int, str]] = {}
        self.saved_document: dict[str, Any] | None = None
        self.reopen_verified = False
        self.normal_close_before_reopen = False
        self.final_close_success = False
        self.force_stop_used = False
        self.started_at = now_iso()
        self.fixed_window_records: list[dict[str, Any]] = []
        self.fixed_window_sequences: list[dict[str, Any]] = []
        self.fixed_window_counter = 0

    def close_files(self) -> None:
        if not self.operations_file.closed:
            self.operations_file.flush()
            self.operations_file.close()
        if not self.hash_file.closed:
            self.hash_file.flush()
            self.hash_file.close()

    def verify_access(self) -> None:
        identity = self.device.shell("id")
        if "uid=0" not in identity and "uid:0" not in identity:
            raise HdcError(f"hdc shell 不是 root: {identity}")
        self.device.shell(
            "test -r /proc/1/maps -a -r /proc/1/smaps -a -r /proc/1/pagemap "
            "-a -w /proc/self/clear_refs"
        )
        self.device.shell(
            f"mkdir -p {q(self.device_dir)} {q(self.device_out)} {q(self.device_screenshot_out)} "
            f"&& test -d {q(self.device_dir)} -a -d {q(self.device_out)}"
        )

    def build_and_push(self) -> None:
        sdk = os.environ.get("OHOS_SDK", "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native")
        source = self.script_dir / "mem_analyze-v6.c"
        if self.args.no_build:
            local_bin = self.script_dir / "mem_analyze-v6-ohos"
        else:
            clang = Path(sdk) / "llvm/bin/clang"
            sysroot = Path(sdk) / "sysroot"
            if not clang.is_file() or not sysroot.is_dir():
                raise HdcError(f"OpenHarmony SDK 不完整: {sdk}")
            temp_dir = Path(tempfile.mkdtemp(prefix="wps-v6-"))
            local_bin = temp_dir / "mem_analyze-v6-ohos"
            run_host([
                str(clang), "-O2", "-std=c11", "-Wall", "-Wextra",
                "-target", "aarch64-linux-ohos", f"--sysroot={sysroot}",
                "-o", str(local_bin), str(source),
            ])
        if not local_bin.is_file():
            raise HdcError(f"采集器不存在: {local_bin}")
        self.collector_local = local_bin
        self.device.send(local_bin, self.device_bin)
        self.device.shell(f"chmod 755 {q(self.device_bin)}")

    def clear_refs(self) -> None:
        self.device.shell(f"{q(self.device_bin)} --clear-refs --app {q(BUNDLE)}")

    def run_fixed_window(
        self,
        *,
        operation_execution_id: str,
        operation_id: str,
        segment_index: int,
        segment_label: str,
        window_kind: str,
        target_duration_s: float,
        action_callback: Callable[[], Any] | None = None,
        baseline_group_id: str | None = None,
        action_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one auditable fixed observation window without interrupting its action."""
        self.fixed_window_counter = getattr(self, "fixed_window_counter", 0) + 1
        execution_token = hashlib.sha256(operation_execution_id.encode("utf-8")).hexdigest()[:10]
        window_id = f"fw_{execution_token}_{self.fixed_window_counter:04d}"
        record: dict[str, Any] = {
            "window_id": window_id,
            "operation_execution_id": operation_execution_id,
            "operation_id": operation_id,
            "segment_index": segment_index,
            "segment_label": segment_label,
            "window_kind": window_kind,
            "baseline_group_id": baseline_group_id or "",
            "action_count": 0,
            "action_metadata": dict(action_metadata or {}),
            "collection_quality": "OK",
            "action_quality": "OK",
            "error": "",
        }
        clear_started = time.perf_counter()
        record["clear_refs_started_at"] = now_iso()
        self.clear_refs()
        clear_completed = time.perf_counter()
        record["clear_refs_ended_at"] = now_iso()
        record["clear_refs_elapsed_s"] = clear_completed - clear_started
        record["window_started_at"] = record["clear_refs_ended_at"]
        action_result: Any = None
        record["action_started_at"] = now_iso()
        action_started = time.perf_counter()
        try:
            if action_callback is not None:
                action_result = action_callback()
        except Exception as exc:  # preserve a failed real action and still collect the window
            record["action_quality"] = "ACTION_FAILED"
            record["error"] = str(exc)
        finally:
            action_ended = time.perf_counter()
            record["action_ended_at"] = now_iso()
            record["action_elapsed_s"] = action_ended - action_started
        if isinstance(action_result, Mapping):
            result_metadata = dict(action_result)
            record["action_count"] = int(result_metadata.pop("action_count", 0) or 0)
            record["action_metadata"].update(result_metadata)
        elif action_callback is not None:
            record["action_count"] = 1

        remaining = float(target_duration_s) - (time.perf_counter() - clear_completed)
        if remaining > 0:
            time.sleep(remaining)
        collection_started_monotonic = time.perf_counter()
        record["collection_started_at"] = now_iso()
        record["window_ended_at"] = record["collection_started_at"]
        record.update(classify_fixed_window(collection_started_monotonic - clear_completed, {
            **self.vma_mapping_config,
            "fixed_windows": {
                **self.vma_mapping_config["fixed_windows"],
                "target_window_s": float(target_duration_s),
            },
        }))
        if record["action_quality"] != "OK":
            record["support_eligible"] = False
            record["support_exclusion_reason"] = record["action_quality"]

        sample_kind = "BASELINE" if window_kind == "BASELINE" else (
            "POST_LAUNCH" if window_kind == "POST_LAUNCH" else "OPERATION"
        )
        try:
            processes = self.snapshot()
            if not processes:
                raise HdcError("fixed window collection found no WPS process")
            sample_stage = f"fw_{self.fixed_window_counter:04d}_{segment_label[:32]}"
            sample = self.sample(self.fixed_window_counter, sample_stage, sample_kind, processes)
            record["processes"] = processes
            record["sample"] = sample
            record["markdown_reports"] = sample["markdown_reports"]
            record["jsonl_reports"] = sample["jsonl_reports"]
            record["report"] = sample.get("report", "")
            record["collection_ended_at"] = sample["collection_ended_at"]
            record["collection_elapsed_s"] = sample["collection_elapsed_s"]
            record["hash_mismatch_count"] = sample["hash_mismatch_count"]
            if sample["hash_mismatch_count"]:
                record["collection_quality"] = "HASH_MISMATCH"
                record["support_eligible"] = False
                record["support_exclusion_reason"] = "HASH_MISMATCH"
        except (HdcError, OSError, ValueError, VmaJsonError) as exc:
            record["collection_quality"] = "COLLECTION_FAILED"
            record["support_eligible"] = False
            record["support_exclusion_reason"] = "COLLECTION_FAILED"
            record["error"] = str(exc)
            record.setdefault("processes", [])
            record.setdefault("markdown_reports", [])
            record.setdefault("jsonl_reports", [])
            record["collection_ended_at"] = now_iso()
            record["collection_elapsed_s"] = time.perf_counter() - collection_started_monotonic

        self.fixed_window_records.append(record)
        persisted = {key: value for key, value in record.items() if key != "sample"}
        append_jsonl(self.vma_mapping_dir / "operation_window_samples.jsonl", [persisted])
        return record

    def collect_fixed_baselines(
        self, *, operation_execution_id: str, operation_id: str, baseline_state: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        cfg = self.vma_mapping_config["fixed_windows"]
        baseline_group_id = f"{operation_execution_id}_baseline"
        windows = []
        for offset in range(int(cfg["baseline_window_count"])):
            windows.append(self.run_fixed_window(
                operation_execution_id=operation_execution_id,
                operation_id=operation_id,
                segment_index=offset + 1,
                segment_label=f"BASELINE_{offset + 1:02d}",
                window_kind="BASELINE",
                target_duration_s=float(cfg["target_window_s"]),
                baseline_group_id=baseline_group_id,
                action_metadata={"baseline_state": baseline_state},
            ))
        return baseline_group_id, windows

    def map_fixed_window_sequence(
        self,
        *,
        operation_execution_id: str,
        operation_id: str,
        baseline_windows: list[dict[str, Any]],
        operation_windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        hydrated_baselines = []
        for baseline in baseline_windows:
            hydrated = dict(baseline)
            hydrated["vmas"] = load_vma_jsonl(Path(path) for path in baseline.get("jsonl_reports", []))
            hydrated_baselines.append(hydrated)
        sequence_results: list[dict[str, Any]] = []
        aggregate_by_key: dict[str, dict[str, Any]] = {}
        eligible_window_count = 0
        for window in operation_windows:
            hydrated_window = dict(window)
            hydrated_window["vmas"] = load_vma_jsonl(Path(path) for path in window.get("jsonl_reports", []))
            result = map_fixed_window(
                baseline_windows=hydrated_baselines,
                operation_window=hydrated_window,
                app_id=BUNDLE,
                config=self.vma_mapping_config,
                session_context={
                    "current_test_document": bool(self.saved_document),
                    "current_test_document_path": (self.saved_document or {}).get("final_path", ""),
                },
            )
            one_window_aggregate = aggregate_execution([result])
            eligible_window_count += int(one_window_aggregate["eligible_window_count"])
            for item in one_window_aggregate["feature_aggregates"]:
                key = str(item["feature_key"])
                target = aggregate_by_key.setdefault(key, {
                    "feature_key": key, "sum_estimated_excess_vma_pages": 0.0,
                    "max_estimated_excess_pages": 0.0, "active_window_count": 0, "window_count": 0,
                })
                target["sum_estimated_excess_vma_pages"] += float(item["sum_estimated_excess_vma_pages"])
                target["max_estimated_excess_pages"] = max(
                    float(target["max_estimated_excess_pages"]), float(item["max_estimated_excess_pages"])
                )
                target["active_window_count"] += int(item["active_window_count"])
                target["window_count"] += int(item["window_count"])
            common = {
                "window_id": result["window_id"],
                "operation_execution_id": operation_execution_id,
                "operation_id": operation_id,
                "segment_index": result["segment_index"],
                "segment_label": result["segment_label"],
                "baseline_group_id": result["baseline_group_id"],
                "support_eligible": result["support_eligible"],
            }
            process_records = []
            for category, items in result["process_pairing"].items():
                process_records.extend({**common, "pair_category": category, **item} for item in items)
            append_jsonl(self.vma_mapping_dir / "operation_window_process_pairs.jsonl", process_records)
            append_jsonl(self.vma_mapping_dir / "operation_window_vma_pairs.jsonl", result["paired_vmas"])
            append_jsonl(self.vma_mapping_dir / "operation_window_file_vma_samples.jsonl", result["file_samples"])
            append_jsonl(self.vma_mapping_dir / "operation_window_anon_vma_samples.jsonl", result["anonymous_samples"])

            sequence_results.append({
                "window_id": result["window_id"],
                "operation_execution_id": result["operation_execution_id"],
                "operation_id": result["operation_id"],
                "segment_index": result["segment_index"],
                "segment_label": result["segment_label"],
                "normalized_segment_label": result["normalized_segment_label"],
                "baseline_group_id": result["baseline_group_id"],
                "baseline_quality": result["baseline_quality"],
                "baseline_valid_window_count": result.get("baseline_valid_window_count", 0),
                "median_baseline_window_s": result.get("median_baseline_window_s", 0.0),
                "support_eligible": result["support_eligible"],
                "support_exclusion_reason": result["support_exclusion_reason"],
                "vma_mapping_status": result["vma_mapping_status"],
                "vma_mapping_error": result["vma_mapping_error"],
                "summary": result["summary"],
            })

        execution_aggregate = {
            "aggregation_semantics": "SUM_OF_VMA_WINDOW_SAMPLES_NOT_UNIQUE_PAGE_SET",
            "eligible_window_count": eligible_window_count,
            "feature_aggregates": sorted(aggregate_by_key.values(), key=lambda item: item["feature_key"]),
            "sum_estimated_excess_vma_pages": sum(
                float(item["sum_estimated_excess_vma_pages"]) for item in aggregate_by_key.values()
            ),
        }
        sequence = {
            "schema_version": "homeny.operation-window-sequence.v1",
            "operation_execution_id": operation_execution_id,
            "operation_id": operation_id,
            "baseline_window_ids": [item["window_id"] for item in baseline_windows],
            "operation_window_ids": [item["window_id"] for item in operation_windows],
            "window_results": sequence_results,
            "execution_aggregate": execution_aggregate,
        }
        self.fixed_window_sequences.append(sequence)
        sequence_path = self.vma_mapping_dir / "operation_window_sequences.json"
        sequence_path.write_text(
            json.dumps(self.fixed_window_sequences, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.write_fixed_window_quality()
        return sequence

    def write_fixed_window_quality(self) -> None:
        counts: dict[str, int] = {}
        for item in self.fixed_window_records:
            quality = str(item.get("window_quality", "UNKNOWN"))
            counts[quality] = counts.get(quality, 0) + 1
        eligible = sum(bool(item.get("support_eligible")) for item in self.fixed_window_records)
        payload = {
            "schema_version": "homeny.fixed-window-quality.v1",
            "window_count": len(self.fixed_window_records),
            "support_eligible_count": eligible,
            "support_eligible_ratio": eligible / len(self.fixed_window_records) if self.fixed_window_records else 0.0,
            "quality_counts": counts,
        }
        (self.vma_mapping_dir / "fixed_window_quality.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        lines = ["# Fixed-window summary", "", f"- Windows: `{payload['window_count']}`",
                 f"- Support eligible: `{eligible}`", f"- Eligible ratio: `{payload['support_eligible_ratio']:.6f}`", ""]
        lines.extend(f"- `{key}`: `{value}`" for key, value in sorted(counts.items()))
        (self.vma_mapping_dir / "fixed_window_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _collect_idle_baseline(self, record: dict[str, Any], index: int, stage: str) -> dict[str, Any] | None:
        if not getattr(self.args, "idle_baseline", True):
            record.update({
                "baseline_enabled": False,
                "baseline_status": "DISABLED",
                "baseline_unavailable_reason": "IDLE_BASELINE_DISABLED",
                "baseline_quality": "NO_BASELINE",
            })
            return None
        record.update({"baseline_enabled": True, **stage_baseline_semantics(stage)})
        record["baseline_started_at"] = now_iso()
        record["baseline_clear_refs_started_at"] = now_iso()
        clear_started = time.perf_counter()
        self.clear_refs()
        clear_ended = time.perf_counter()
        record["baseline_clear_refs_ended_at"] = now_iso()
        record["baseline_clear_refs_elapsed_s"] = clear_ended - clear_started
        record["baseline_window_started_at"] = now_iso()
        time.sleep(float(getattr(self.args, "baseline_window_s", 5.0)))
        baseline_processes = self.snapshot()
        if not baseline_processes:
            raise HdcError("baseline 采集前未发现 WPS 相关进程")
        record["baseline_window_ended_at"] = now_iso()
        record["baseline_window_s"] = time.perf_counter() - clear_ended
        record["baseline_collection_started_at"] = now_iso()
        sample = self.sample(index, stage, "BASELINE", baseline_processes)
        record["baseline_collection_ended_at"] = sample["collection_ended_at"]
        record["baseline_collection_elapsed_s"] = sample["collection_elapsed_s"]
        record["baseline_ended_at"] = sample["collection_ended_at"]
        for key, value in sample.items():
            if key.startswith("baseline_"):
                record[key] = value
        record["baseline_processes"] = baseline_processes
        record["baseline_sample"] = sample
        return sample

    def _collect_operation_sample(
        self,
        record: dict[str, Any],
        index: int,
        stage: str,
        action: Callable[[], None],
        settle_wait_s: float,
    ) -> dict[str, Any]:
        record["operation_clear_refs_started_at"] = now_iso()
        clear_started = time.perf_counter()
        self.clear_refs()
        clear_ended = time.perf_counter()
        record["operation_clear_refs_ended_at"] = now_iso()
        record["operation_clear_refs_elapsed_s"] = clear_ended - clear_started
        record["clear_refs_elapsed_s"] = record["operation_clear_refs_elapsed_s"]
        record["operation_window_started_at"] = now_iso()
        record["operation_started_at"] = now_iso()
        operation_started = time.perf_counter()
        try:
            action()
        finally:
            record["operation_elapsed_s"] = time.perf_counter() - operation_started
            record["operation_ended_at"] = now_iso()
        settle_started = time.perf_counter()
        time.sleep(settle_wait_s)
        record["settle_wait_s"] = time.perf_counter() - settle_started
        operation_processes = self.snapshot()
        if not operation_processes:
            raise HdcError("操作后未发现 WPS 相关进程")
        record["after"] = operation_processes
        record["operation_window_ended_at"] = now_iso()
        record["operation_window_s"] = time.perf_counter() - clear_ended
        record["operation_collection_started_at"] = now_iso()
        sample = self.sample(index, stage, "OPERATION", operation_processes)
        record.update(sample)
        record["operation_collection_ended_at"] = sample["collection_ended_at"]
        record["operation_collection_elapsed_s"] = sample["collection_elapsed_s"]
        record["operation_processes"] = operation_processes
        record["operation_sample"] = sample
        return sample

    def _map_operation_vmas(self, record: dict[str, Any], stage: str) -> None:
        if getattr(self.args, "disable_vma_mapping", False):
            record.update({
                "vma_mapping_status": "DISABLED",
                "vma_mapping_error": "",
                "collection_quality": "OK",
                "baseline_quality": "NO_BASELINE" if not record.get("baseline_sample") else "OK",
            })
            return
        baseline_sample = record.get("baseline_sample")
        operation_sample = record.get("operation_sample")
        if not baseline_sample:
            record.update({
                "vma_mapping_status": "NO_BASELINE",
                "vma_mapping_error": "",
                "collection_quality": "OK",
                "baseline_quality": "BASELINE_NOT_APPLICABLE" if stage == "01_open_wps" else "NO_BASELINE",
                "activity_quality": "NO_BASELINE",
            })
            return
        try:
            baseline_vmas = load_vma_jsonl(Path(path) for path in baseline_sample["jsonl_reports"])
            operation_vmas = load_vma_jsonl(Path(path) for path in operation_sample["jsonl_reports"])
            context = {
                "current_test_document": bool(self.saved_document),
                "current_test_document_path": (self.saved_document or {}).get("final_path", ""),
            }
            result = map_operation_stage(
                stage=stage,
                baseline_processes=record["baseline_processes"],
                operation_processes=record["operation_processes"],
                baseline_vmas=baseline_vmas,
                operation_vmas=operation_vmas,
                baseline_window_s=float(record["baseline_window_s"]),
                operation_window_s=float(record["operation_window_s"]),
                app_id=BUNDLE,
                config=self.vma_mapping_config,
                session_context=context,
            )
            write_stage_outputs(self.vma_mapping_dir, result)
            record.update(result["summary"])
            process_qualities = [item["quality"] for item in result["process_pairing"]["pairs"]]
            vma_qualities = [item["vma_match_quality"] for item in result["paired_vmas"]]
            window_qualities = [item["window_quality"] for item in result["paired_vmas"]]
            record.update({
                "vma_mapping_status": result["vma_mapping_status"],
                "vma_mapping_error": result["vma_mapping_error"],
                "collection_quality": "OK",
                "process_match_quality": "PID_ONLY_MATCH" if "PID_ONLY_MATCH" in process_qualities else "OK",
                "vma_match_quality": "VMA_SPLIT_MERGE_APPROXIMATION" if "VMA_SPLIT_MERGE_APPROXIMATION" in vma_qualities else "OK",
                "baseline_quality": "OK",
                "window_quality": next((item for item in window_qualities if item != "OK"), "OK"),
                "activity_quality": next((item for item in window_qualities if item != "OK"), "OK"),
                "identity_confidence": "HIGH" if result["file_samples"] else "MEDIUM" if result["anonymous_samples"] else "LOW",
            })
        except (OSError, ValueError, KeyError, VmaJsonError) as exc:
            record.update({
                "vma_mapping_status": "ERROR",
                "vma_mapping_error": str(exc),
                "collection_quality": "JSON_PARSE_ERROR" if isinstance(exc, VmaJsonError) else "MISSING_JSONL",
                "activity_quality": "NO_BASELINE",
            })
            self.warnings.append(f"{stage} VMA mapping: {exc}")

    def list_documents(self) -> list[dict[str, Any]]:
        command = (
            f"find {q(DOCUMENT_ROOT)} -type f "
            "\\( -iname '*.docx' -o -iname '*.doc' -o -iname '*.wps' \\) "
            "2>/dev/null | while read -r f; do "
            "stat -c '%n|%s|%y' \"$f\"; done"
        )
        return parse_device_documents(self.device.shell(command, check=False))

    def record_document_baseline(self) -> None:
        self.document_baseline = {
            item["path"]: (item["size_bytes"], item["mtime"])
            for item in self.list_documents()
        }

    def find_saved_document(self, *, wait_s: float = 0.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait_s
        while True:
            documents = self.list_documents()
            candidates = [
                item for item in documents
                if item["size_bytes"] > 0
                and (
                    item["path"] not in self.document_baseline
                    or (item["size_bytes"], item["mtime"]) != self.document_baseline[item["path"]]
                )
            ]
            candidates.sort(key=lambda item: (item["mtime"], item["size_bytes"]), reverse=True)
            if candidates:
                return candidates[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(1.0)

    def verify_document_content(self, path: str) -> dict[str, bool]:
        """Verify required metadata and the complete requested stress payload."""
        with tempfile.TemporaryDirectory(prefix="wps-doc-verify-") as temp_dir:
            local = Path(temp_dir) / Path(path).name
            self.device.recv(path, local)
            try:
                with zipfile.ZipFile(local) as archive:
                    xml = archive.read("word/document.xml")
                root = ET.fromstring(xml)
            except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
                raise HdcError(f"保存文件不是可读取的 docx: {path}") from exc
        document_text = "".join(
            element.text or ""
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "t"
        )
        heavy_block = self.heavy_workload_block()
        markers = {
            "test_serial": self.args.test_serial in document_text,
            "exact_time": "Exact_time" in document_text,
            "purpose": (
                "Purpose_measure_WPS_related_process_RSS_PSS_Referenced_and_Swap_"
                "during_a_real_Word_workflow"
            ) in document_text,
            "operation_chain": (
                "Operation_chain_open_WPS_new_Word_write_metadata_heavy_edit_line_breaks_"
                "page_scroll_cursor_move_save_background_foreground_close_reopen_saved_"
                "document_reopen_edit_scroll_close"
            ) in document_text,
            "preliminary_conclusion": (
                "Preliminary_conclusion_profiling_evidence_only_compare_stage_aggregates_"
                "and_do_not_infer_reclamation_from_Referenced_alone"
            ) in document_text,
            "heavy_workload_complete": document_text.count(heavy_block) >= self.args.heavy_repeats,
        }
        if not all(markers.values()):
            missing = [key for key, present in markers.items() if not present]
            raise HdcError(f"Word 正文缺少自动化写入标记: {missing}")
        return markers

    def rename_saved_document(self) -> dict[str, Any]:
        if not self.saved_document:
            raise HdcError("没有可重命名的已保存文档")
        source = str(self.saved_document["path"])
        final_name = f"WPS_memory_test_{self.session_timestamp}.docx"
        destination = f"{DESKTOP_ROOT}/{final_name}"
        if source != destination:
            self.device.shell(f"mv {q(source)} {q(destination)}")
        verified = next((item for item in self.list_documents() if item["path"] == destination), None)
        if not verified or verified["size_bytes"] <= 0:
            raise HdcError(f"重命名后未验证文档: {destination}")
        self.saved_document = {
            **self.saved_document,
            **verified,
            "original_path": source,
            "final_path": destination,
            "file_name": final_name,
        }
        return self.saved_document

    def capture_screen(self, label: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
        remote = f"{self.device_screenshot_out}/{safe}.png"
        local = self.screenshot_dir / f"{safe}.png"
        self.device.shell(f"mkdir -p {q(self.device_screenshot_out)}")
        self.device.shell(f"uitest screenCap -p {q(remote)}", check=False)
        try:
            self.device.recv(remote, local)
            if local.is_file() and local.stat().st_size:
                self.screenshots.append(str(local))
        except HdcError:
            # Screenshots are automatic evidence only.  No stage depends on
            # an AI/visual inspection or becomes failed because a screenshot
            # transfer is unavailable.
            self.warnings.append(f"截图未拉回: {label}")

    def sample(
        self,
        index: int,
        stage: str,
        sample_kind: str,
        process_snapshot_before_collection: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if sample_kind not in SAMPLE_KINDS:
            raise ValueError(f"unsupported sample kind: {sample_kind}")
        collection_started_at = now_iso()
        collection_started = time.perf_counter()
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        remote_dir = f"{self.device_out}/{sample_kind.lower()}/{safe_stage}"
        remote_md = f"{remote_dir}/referenced_{index:02d}_{safe_stage}_{stamp}.md"
        remote_jsonl = f"{remote_dir}/referenced_{index:02d}_{safe_stage}_{stamp}.jsonl"
        self.device.shell(f"mkdir -p {q(remote_dir)}")
        collector_started = time.perf_counter()
        output = self.device.shell(
            f"{q(self.device_bin)} --app {q(BUNDLE)} -o {q(remote_md)} "
            f"--jsonl-output {q(remote_jsonl)} --with-vma",
            timeout_s=300.0,
        )
        collector_elapsed_s = time.perf_counter() - collector_started
        remote_by_format = parse_collector_report_paths(output)
        if not remote_by_format["MARKDOWN"]:
            raise HdcError(f"采集器没有返回 Markdown 报告路径: {output}")
        if not remote_by_format["JSONL"]:
            raise HdcError(f"采集器没有返回 JSONL 报告路径: {output}")

        pull_started_at = now_iso()
        pull_started = time.perf_counter()
        local_dir = report_directory(self.local_out, sample_kind, stage)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_by_format: dict[str, list[str]] = {"MARKDOWN": [], "JSONL": []}
        sample_hash_matches: list[bool] = []
        process_by_pid = {str(item.get("pid")): item for item in process_snapshot_before_collection}
        for report_format in ("MARKDOWN", "JSONL"):
            for remote_report in remote_by_format[report_format]:
                remote_hash = self.device.shell(f"sha256sum {q(remote_report)} | cut -d ' ' -f 1")
                local = local_dir / Path(remote_report).name
                self.device.recv(remote_report, local)
                if not local.is_file() or not local.stat().st_size:
                    raise HdcError(f"报告未拉回或为空: {local}")
                local_hash = sha256_file(local)
                hash_match = remote_hash.strip() == local_hash
                sample_hash_matches.append(hash_match)
                if report_format == "JSONL":
                    try:
                        first_record = json.loads(local.read_text(encoding="utf-8").splitlines()[0])
                        pid = str(first_record.get("pid", ""))
                    except (IndexError, json.JSONDecodeError, OSError):
                        pid = ""
                else:
                    metrics = parse_report_metrics(local)
                    pid = str(metrics.get("pid", ""))
                    if sample_kind in {"OPERATION", "POST_LAUNCH"}:
                        self.report_records.append({
                            "stage": stage,
                            "index": index,
                            "sample_kind": sample_kind,
                            "report": str(local),
                            **metrics,
                        })
                identity = f"{sample_kind}|{stage}|{report_format}|{pid}|{local.name}"
                self.device_report_hashes[identity] = remote_hash.strip()
                self.local_report_hashes[identity] = local_hash
                self.hashes.writerow({
                    "report": local.name,
                    "device_path": remote_report,
                    "local_path": str(local),
                    "device_sha256": remote_hash.strip(),
                    "local_sha256": local_hash,
                    "match": str(hash_match).lower(),
                    "sample_kind": sample_kind,
                    "report_format": report_format,
                    "stage": stage,
                    "pid": pid,
                })
                local_by_format[report_format].append(str(local))
                if pid in process_by_pid:
                    process_by_pid[pid].setdefault("reports", {})[report_format] = str(local)
        self.hash_file.flush()
        pull_elapsed_s = time.perf_counter() - pull_started
        collection_elapsed_s = time.perf_counter() - collection_started
        markdown_value = ";".join(local_by_format["MARKDOWN"])
        jsonl_value = ";".join(local_by_format["JSONL"])
        prefix = {"BASELINE": "baseline", "OPERATION": "operation", "POST_LAUNCH": "post_launch"}[sample_kind]
        return {
            "sample_kind": sample_kind,
            "report": markdown_value if sample_kind in {"OPERATION", "POST_LAUNCH"} else "",
            "report_count": len(local_by_format["MARKDOWN"]) if sample_kind in {"OPERATION", "POST_LAUNCH"} else 0,
            f"{prefix}_report": markdown_value,
            f"{prefix}_report_count": len(local_by_format["MARKDOWN"]),
            f"{prefix}_jsonl_report": jsonl_value,
            f"{prefix}_jsonl_report_count": len(local_by_format["JSONL"]),
            "markdown_reports": list(local_by_format["MARKDOWN"]),
            "jsonl_reports": list(local_by_format["JSONL"]),
            "process_snapshot": process_snapshot_before_collection,
            "collection_started_at": collection_started_at,
            "collection_ended_at": now_iso(),
            "collection_elapsed_s": collection_elapsed_s,
            "collector_elapsed_s": collector_elapsed_s,
            "report_pull_started_at": pull_started_at,
            "report_pull_ended_at": now_iso(),
            "report_pull_elapsed_s": pull_elapsed_s,
            "device_report_count": sum(len(items) for items in remote_by_format.values()),
            "local_report_count": sum(len(items) for items in local_by_format.values()),
            "matched_report_count": sum(sample_hash_matches),
            "hash_mismatch_count": sum(not item for item in sample_hash_matches),
        }

    def start_wps(self) -> None:
        self.device.shell(f"aa start -a {q(ABILITY)} -b {q(BUNDLE)} -m {q(MODULE)}")

    def force_stop_wps(self) -> None:
        self.device.shell(f"aa force-stop {q(BUNDLE)}", check=False)

    def ui_key(self, key: str) -> None:
        self.device.shell(f"uitest uiInput keyEvent {q(key)}")

    def ui_click(self, x: int, y: int) -> None:
        self.device.shell(f"uitest uiInput click {x} {y}")

    def ui_text_payload(self, text: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.:/+-]+", "_", text)
        if safe:
            self.device.shell(f"uitest uiInput text {q(safe)}", timeout_s=120.0)
            # WPS commits XComponent input asynchronously.  Without a short
            # gap, consecutive real-device injections can overwrite/drop
            # complete chunks even though uitest has already returned.
            time.sleep(UI_TEXT_SETTLE_S)

    def ui_text_chunks(self, text: str) -> list[str]:
        """Split safe text without starting a later chunk with punctuation."""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + UI_TEXT_CHUNK_SIZE, len(text))
            # On the device, a leading underscore is transformed by the WPS
            # input method. Move the boundary left so each later injection
            # begins with an alphanumeric character from the same payload.
            while end < len(text) and end > start + 1 and not text[end].isalnum():
                end -= 1
            chunks.append(text[start:end])
            start = end
        return chunks

    def ui_commit_chunks(self, chunks: list[str]) -> None:
        """Commit text chunks in small device-side batches.

        Each chunk keeps the proven text/wait/Enter/wait sequence.  Batching
        only removes repeated host-to-device process startup overhead.
        """
        for offset in range(0, len(chunks), UI_TEXT_BATCH_SIZE):
            batch = chunks[offset : offset + UI_TEXT_BATCH_SIZE]
            commands: list[str] = []
            for chunk in batch:
                safe = re.sub(r"[^A-Za-z0-9_.:/+-]+", "_", chunk)
                if not safe:
                    continue
                commands.extend([
                    f"uitest uiInput text {q(safe)}",
                    f"sleep {UI_TEXT_SETTLE_S}",
                    f"uitest uiInput keyEvent {q(KEY_ENTER)}",
                    f"sleep {UI_TEXT_SETTLE_S}",
                ])
            if commands:
                self.device.shell("\n".join(commands), timeout_s=120.0)

    def ui_text(self, text: str) -> None:
        """Type safe ASCII lines and use Enter for real paragraph breaks.

        On this target ``hdc shell`` passes quote characters through to
        ``uitest uiInput text`` and embedded newlines are not reliable.  The
        old 1200-character chunks were truncated to a single trailing letter
        on this device.  Saved DOCX evidence established a hard 62-character
        limit and showed that WPS ignores a second text injection in the same
        paragraph.  Use 60 characters and commit every chunk with Enter.
        """
        lines = text.splitlines() or [text]
        for line in lines:
            safe = re.sub(r"[^A-Za-z0-9_.:/+-]+", "_", line)
            if safe:
                for chunk in self.ui_text_chunks(safe):
                    self.ui_text_payload(chunk)
                    self.ui_key(KEY_ENTER)
            else:
                self.ui_key(KEY_ENTER)

    def ui_swipe(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.device.shell(f"uitest uiInput swipe {x1} {y1} {x2} {y2} 800")

    def snapshot(self) -> list[dict[str, str]]:
        return process_snapshot(self.device)

    def metadata_text(self) -> str:
        timestamp = now_iso()
        return (
            "WPS_HarmonyOS_PC_memory_collection\n"
            f"Test_serial_{self.args.test_serial}\n"
            f"Exact_time_{timestamp}\n"
            "Purpose_measure_WPS_related_process_RSS_PSS_Referenced_and_Swap_during_a_real_Word_workflow\n"
            "Operation_chain_open_WPS_new_Word_write_metadata_heavy_edit_line_breaks_page_scroll_cursor_move_save_background_foreground_close_reopen_saved_document_reopen_edit_scroll_close\n"
            "Preliminary_conclusion_profiling_evidence_only_compare_stage_aggregates_and_do_not_infer_reclamation_from_Referenced_alone\n"
        )

    def new_word(self) -> None:
        # Verified on the native 3120x2080 display: open New, choose Word,
        # then choose the blank document.
        self.ui_click(420, 275)
        time.sleep(2)
        self.ui_click(835, 555)
        time.sleep(4)
        self.ui_click(1125, 600)
        time.sleep(5)
        self.capture_screen("02_new_word_after")

    def write_metadata(self) -> None:
        self.ui_click(self.args.editor_x, self.args.editor_y)
        self.ui_text(self.metadata_text())

    def write_metadata_fields(self, start_index: int = 0, count: int | None = None) -> dict[str, Any]:
        fields = self.metadata_text().splitlines()
        selected = fields[start_index:] if count is None else fields[start_index:start_index + count]
        started = time.perf_counter()
        if start_index == 0:
            self.ui_click(self.args.editor_x, self.args.editor_y)
        self.ui_text("\n".join(selected) + "\n")
        return {
            "success": True,
            "action_count": len(selected),
            "actual_action_elapsed_s": time.perf_counter() - started,
            "content_range": [start_index, start_index + len(selected)],
            "validation_metadata": {"metadata_field_count": len(selected)},
            "error": "",
        }

    def heavy_workload_block(self) -> str:
        return (
            "WPS_memory_profiling_stress_paragraph_repeated_text_creates_a_multi_page_Word_document_"
            f"for_observing_layout_rendering_cache_and_process_memory_behavior_test_serial_{self.args.test_serial}_controlled_workload_"
        )

    def write_pressure_blocks(self, start_index: int, count: int) -> dict[str, Any]:
        if start_index < 1 or count < 1:
            raise ValueError("start_index and count must be >= 1")
        started = time.perf_counter()
        block = self.heavy_workload_block()
        self.ui_commit_chunks(self.ui_text_chunks(block) * count)
        return {
            "success": True,
            "action_count": count,
            "actual_action_elapsed_s": time.perf_counter() - started,
            "content_range": [start_index, start_index + count - 1],
            "validation_metadata": {
                "logical_block_count": count,
                "block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "complete_logical_blocks": True,
            },
            "error": "",
        }

    def write_pressure_block_chunk(self, block_index: int, chunk_index: int) -> dict[str, Any]:
        chunks = self.ui_text_chunks(self.heavy_workload_block())
        if block_index < 1 or not 1 <= chunk_index <= len(chunks):
            raise ValueError("invalid block/chunk index")
        started = time.perf_counter()
        self.ui_commit_chunks([chunks[chunk_index - 1]])
        return {
            "success": True, "action_count": 1,
            "actual_action_elapsed_s": time.perf_counter() - started,
            "content_range": {"block_index": block_index, "chunk_index": chunk_index,
                              "chunk_count": len(chunks)},
            "validation_metadata": {
                "complete_chunk": True,
                "block_sha256": hashlib.sha256(self.heavy_workload_block().encode("utf-8")).hexdigest(),
            },
            "error": "",
        }

    def write_safe_text_chunk(self, text: str, *, content_label: str) -> dict[str, Any]:
        chunks = self.ui_text_chunks(text)
        if len(chunks) != 1:
            raise ValueError("write_safe_text_chunk requires exactly one safe chunk")
        started = time.perf_counter()
        self.ui_commit_chunks(chunks)
        return {
            "success": True, "action_count": 1,
            "actual_action_elapsed_s": time.perf_counter() - started,
            "content_range": content_label,
            "validation_metadata": {"complete_safe_chunk": True, "payload_length": len(text)},
            "error": "",
        }

    def scroll_for_window(self, direction: str, target_duration_s: float, interval_s: float = 0.2) -> dict[str, Any]:
        if direction not in {"DOWN", "UP"}:
            raise ValueError("direction must be DOWN or UP")
        started = time.perf_counter()
        count = 0
        while time.perf_counter() - started < max(0.0, target_duration_s - 1.0):
            if direction == "DOWN":
                self.ui_swipe(self.args.editor_x, 1500, self.args.editor_x, 620)
            else:
                self.ui_swipe(self.args.editor_x, 620, self.args.editor_x, 1500)
            count += 1
            remaining = target_duration_s - (time.perf_counter() - started)
            if remaining > interval_s + 1.0:
                time.sleep(interval_s)
            else:
                break
        return {
            "success": True,
            "action_count": count,
            "actual_action_elapsed_s": time.perf_counter() - started,
            "content_range": direction,
            "validation_metadata": {"direction": direction, "interval_s": interval_s},
            "error": "",
        }

    def heavy_edit_scroll(self) -> None:
        # write_metadata leaves the insertion point at the document end.
        # Clicking the nominal editor coordinate here can move it back into
        # existing text and interleave the stress payload with metadata.
        block = self.heavy_workload_block()
        # The real WPS XComponent accepts at most one uitest text injection
        # per paragraph and truncates payloads above 62 characters.  Commit
        # every 60-character chunk as its own paragraph so no data is lost.
        # Split one logical block and repeat that stable chunk layout.  If the
        # entire repeated payload is split as one stream, chunk boundaries
        # rotate through the block and periodically trigger WPS input-method
        # auto-formatting (observed as ``_`` becoming ``——`` every 5 blocks).
        block_chunks = self.ui_text_chunks(block)
        chunks = block_chunks * self.args.heavy_repeats
        self.ui_commit_chunks(chunks)
        # Multiple explicit line breaks and navigation gestures keep the
        # XComponent active while allowing layout/scroll work to settle.
        for _ in range(8):
            self.ui_text("\n")
        for _ in range(8):
            self.ui_swipe(self.args.editor_x, 1500, self.args.editor_x, 620)
        for _ in range(4):
            self.ui_swipe(self.args.editor_x, 620, self.args.editor_x, 1500)
        self.ui_click(self.args.editor_x - 120, self.args.editor_y - 80)
        self.ui_key(KEY_DPAD_LEFT)
        self.ui_key(KEY_DPAD_RIGHT)
        self.ui_click(self.args.editor_x + 120, self.args.editor_y + 80)

    def save_document(self) -> dict[str, Any]:
        before = {item["path"]: (item["size_bytes"], item["mtime"]) for item in self.list_documents()}
        self.document_baseline = before
        self.capture_screen("05_save_before")
        # Word toolbar save icon, verified on the native 3120x2080 display.
        self.ui_click(195, 115)
        time.sleep(4)
        # Choose the user-visible Desktop in the WPS save picker.  A first
        # access may show a HarmonyOS permission dialog; allow it and retry.
        self.ui_click(650, 842)
        time.sleep(2)
        self.ui_click(2300, 1665)
        time.sleep(4)
        self.ui_click(1885, 1275)
        time.sleep(2)
        # If the permission dialog was absent, this is harmless only when it
        # lands outside the app; retrying Save is the useful action.
        self.ui_click(2300, 1665)
        saved = self.find_saved_document(wait_s=20.0)
        if not saved:
            raise HdcError("保存操作后未在设备 Docs 目录发现新增或变化的文档")
        content_markers = self.verify_document_content(saved["path"])
        self.saved_document = {
            **saved,
            "original_path": saved["path"],
            "content_markers_verified": content_markers,
        }
        self.capture_screen("05_save_after")
        return self.saved_document

    def open_saved_document(self, *, start_wps: bool = True) -> None:
        if not self.saved_document:
            raise HdcError("重新打开前没有已保存文档记录")
        final_path = str(self.saved_document.get("final_path") or self.saved_document["path"])
        if not final_path.startswith(DESKTOP_ROOT + "/"):
            raise HdcError(f"保存文件不在预期的 Desktop 目录，无法用固定文件选择器重开: {final_path}")
        verified = next((item for item in self.list_documents() if item["path"] == final_path), None)
        if not verified or verified["size_bytes"] <= 0:
            raise HdcError(f"重新打开前目标文档不存在或为空: {final_path}")
        content_markers = self.verify_document_content(final_path)
        self.saved_document.update(verified)
        self.saved_document["content_markers_verified"] = content_markers
        if start_wps:
            self.start_wps()
            time.sleep(self.args.launch_wait_s)
        # Open the real WPS picker, select Desktop, and enter the exact
        # session filename. Two Enter events accept the filename suggestion
        # and open that exact file. This avoids guessing the newest row.
        self.ui_click(420, 390)
        time.sleep(4)
        self.ui_click(670, 980)
        time.sleep(3)
        self.capture_screen("08_reopen_picker")
        self.ui_click(1850, 1535)
        filename = Path(final_path).name
        self.device.shell(f"uitest uiInput text {q(filename)}")
        time.sleep(2)
        self.ui_key(KEY_ENTER)
        time.sleep(2)
        self.ui_key(KEY_ENTER)
        time.sleep(10)
        self.capture_screen("08_reopen_after")
        if not self.snapshot():
            raise HdcError("按精确文件名打开后未发现 WPS 进程")
        self.saved_document.update({
            "reopen_requested_path": final_path,
            "reopen_filename_typed": filename,
            "reopen_picker_exact_name": True,
        })
        self.reopen_verified = True

    def reopen_edit_scroll(self) -> None:
        if not self.saved_document or not self.reopen_verified:
            raise HdcError("重新打开未成功，不能执行重开后的编辑与滚动")
        self.ui_click(self.args.editor_x, self.args.editor_y)
        marker = f"Reopen_verification_{self.session_timestamp}"
        self.ui_text(marker + "\n")
        for _ in range(4):
            self.ui_swipe(self.args.editor_x, 1450, self.args.editor_x, 650)
        for _ in range(2):
            self.ui_swipe(self.args.editor_x, 650, self.args.editor_x, 1450)
        self.ui_click(self.args.editor_x, self.args.editor_y)
        self.ui_key(KEY_DPAD_LEFT)
        self.ui_key(KEY_DPAD_RIGHT)
        self.capture_screen("09_reopen_marker_ui")
        self.saved_document["reopen_ui_marker"] = marker
        self.saved_document["reopen_ui_marker_evidence"] = "SCREENSHOT_UI_ONLY"
        self.saved_document["reopen_marker_persistence"] = "NOT_REQUIRED_FOR_STAGE_09"
        self.reopen_verified = True

    def write_operation(self, record: dict[str, Any]) -> None:
        row = {field: "" for field in self.operation_fields}
        row.update({
            "session_id": self.session_id,
            "index": record["index"],
            "stage": record["stage"],
            "label": record["label"],
            "operation": record["operation"],
            "success": str(bool(record["success"])).lower(),
            "status": "success" if record["success"] else "failed",
            "started_at": record["started_at"],
            "ended_at": record["ended_at"],
            "before_pids": json.dumps(record.get("before", []), ensure_ascii=False),
            "after_pids": json.dumps(record.get("after", []), ensure_ascii=False),
            "operation_started_at": record.get("operation_started_at", ""),
            "operation_ended_at": record.get("operation_ended_at", ""),
            "operation_elapsed_s": f"{record.get('operation_elapsed_s', 0.0):.6f}",
            "settle_wait_s": f"{record.get('settle_wait_s', 0.0):.6f}",
            "observation_wait_s": f"{record.get('settle_wait_s', 0.0):.6f}",
            "clear_refs_elapsed_s": f"{record.get('clear_refs_elapsed_s', 0.0):.6f}",
            "collection_started_at": record.get("collection_started_at", ""),
            "collection_ended_at": record.get("collection_ended_at", ""),
            "collection_elapsed_s": f"{record.get('collection_elapsed_s', 0.0):.6f}",
            "report_pull_started_at": record.get("report_pull_started_at", ""),
            "report_pull_ended_at": record.get("report_pull_ended_at", ""),
            "report_pull_elapsed_s": f"{record.get('report_pull_elapsed_s', 0.0):.6f}",
            "stage_total_elapsed_s": f"{record.get('stage_total_elapsed_s', 0.0):.6f}",
            "phase_elapsed_s": f"{record.get('stage_total_elapsed_s', 0.0):.6f}",
            "report_count": record.get("report_count", 0),
            "report": record.get("report", ""),
            "device_report_count": record.get("device_report_count", 0),
            "local_report_count": record.get("local_report_count", 0),
            "matched_report_count": record.get("matched_report_count", 0),
            "hash_mismatch_count": record.get("hash_mismatch_count", 0),
            "missing_local_count": record.get("missing_local_count", 0),
            "missing_device_count": record.get("missing_device_count", 0),
            "document_path": record.get("document_path", ""),
            "document_size_bytes": record.get("document_size_bytes", ""),
            "document_mtime": record.get("document_mtime", ""),
            "error": record.get("error", ""),
        })
        for field in NEW_OPERATION_FIELDS:
            value = record.get(field, "")
            if isinstance(value, bool):
                row[field] = str(value).lower()
            elif isinstance(value, float):
                row[field] = f"{value:.6f}"
            elif isinstance(value, (dict, list)):
                row[field] = json.dumps(value, ensure_ascii=False)
            else:
                row[field] = value
        self.operations.writerow(row)
        self.operations_file.flush()
        self.timing_records.append({
            key: record.get(key, 0.0)
            for key in ("index", "stage", "label", "success", "operation_elapsed_s", "settle_wait_s", "clear_refs_elapsed_s", "collection_elapsed_s", "report_pull_elapsed_s", "stage_total_elapsed_s", "report_count")
        })

    def measured_stage(
        self,
        index: int,
        stage: str,
        label: str,
        operation: str,
        action: Callable[[], None],
        settle_wait_s: float,
    ) -> bool:
        stage_started = time.perf_counter()
        started_at = now_iso()
        before = self.snapshot()
        record: dict[str, Any] = {
            "index": index, "stage": stage, "label": label, "operation": operation,
            "success": False, "started_at": started_at, "before": before, "after": [],
            "settle_wait_s": settle_wait_s, "stage_total_elapsed_s": 0.0,
        }
        try:
            if not before:
                raise HdcError("操作前未发现 WPS 相关进程")
            self._collect_idle_baseline(record, index, stage)
            self._collect_operation_sample(record, index, stage, action, settle_wait_s)
            self._map_operation_vmas(record, stage)
            record["document_path"] = (self.saved_document or {}).get("final_path", "")
            record["document_size_bytes"] = (self.saved_document or {}).get("size_bytes", "")
            record["document_mtime"] = (self.saved_document or {}).get("mtime", "")
            record["success"] = True
            print(
                f"[wps-v6] {stage}: success operation={record['operation_elapsed_s']:.3f}s "
                f"collection={record['collection_elapsed_s']:.3f}s reports={record['report_count']}",
                flush=True,
            )
            return True
        except (HdcError, OSError, subprocess.SubprocessError) as exc:
            message = str(exc)
            self.failures.append(f"{stage}: {message}")
            record["error"] = message
            record["after"] = self.snapshot()
            print(f"[wps-v6] {stage}: FAILED: {message}", file=sys.stderr, flush=True)
            return False
        finally:
            record["stage_total_elapsed_s"] = time.perf_counter() - stage_started
            record["ended_at"] = now_iso()
            self.write_operation(record)

    def fixed_heavy_edit_stage(
        self, index: int, *, blocks_per_window: int, edit_window_mode: str = "block",
    ) -> bool:
        """Collect stage 04 as edit batches plus separately paced scroll windows."""
        if blocks_per_window < 1:
            raise ValueError("blocks_per_window must be >= 1")
        if edit_window_mode not in {"block", "chunk"}:
            raise ValueError("edit_window_mode must be block or chunk")
        stage = "04_heavy_edit_scroll"
        execution_token = hashlib.sha256(f"{self.session_id}|{stage}".encode("utf-8")).hexdigest()[:12]
        execution_id = f"fwexec_{execution_token}"
        started = time.perf_counter()
        record: dict[str, Any] = {
            "index": index, "stage": stage, "label": "fixed-window heavy edit and scroll",
            "operation": "complete logical edit batches, then separate down/up scroll windows",
            "success": False, "started_at": now_iso(), "before": self.snapshot(), "after": [],
            "fixed_windows_enabled": True,
            "target_window_s": float(self.vma_mapping_config["fixed_windows"]["target_window_s"]),
            "baseline_window_count": int(self.vma_mapping_config["fixed_windows"]["baseline_window_count"]),
            **stage_baseline_semantics(stage),
        }
        try:
            if not record["before"]:
                raise HdcError("stage 04 fixed-window collection requires a running WPS document")
            baseline_group_id, baselines = self.collect_fixed_baselines(
                operation_execution_id=execution_id, operation_id=stage,
                baseline_state=record["baseline_state"],
            )
            target = float(self.vma_mapping_config["fixed_windows"]["target_window_s"])
            operation_windows: list[dict[str, Any]] = []
            segment_index = 1
            if edit_window_mode == "chunk":
                chunk_count = len(self.ui_text_chunks(self.heavy_workload_block()))
                for block_index in range(1, int(self.args.heavy_repeats) + 1):
                    for chunk_index in range(1, chunk_count + 1):
                        operation_windows.append(self.run_fixed_window(
                            operation_execution_id=execution_id, operation_id=stage,
                            segment_index=segment_index,
                            segment_label=f"EDIT_BATCH_{block_index:02d}_CHUNK_{chunk_index:02d}",
                            window_kind="OPERATION", target_duration_s=target,
                            action_callback=lambda block_index=block_index, chunk_index=chunk_index:
                                self.write_pressure_block_chunk(block_index, chunk_index),
                            baseline_group_id=baseline_group_id,
                            action_metadata={
                                "edit_window_mode": "chunk", "chunks_per_window": 1,
                                "logical_block_index": block_index, "logical_block_chunk_count": chunk_count,
                            },
                        ))
                        segment_index += 1
            else:
                block_start = 1
                while block_start <= int(self.args.heavy_repeats):
                    count = min(blocks_per_window, int(self.args.heavy_repeats) - block_start + 1)
                    start = block_start
                    operation_windows.append(self.run_fixed_window(
                        operation_execution_id=execution_id, operation_id=stage,
                        segment_index=segment_index, segment_label=f"EDIT_BATCH_{segment_index:02d}",
                        window_kind="OPERATION", target_duration_s=target,
                        action_callback=lambda start=start, count=count: self.write_pressure_blocks(start, count),
                        baseline_group_id=baseline_group_id,
                        action_metadata={"blocks_per_window": blocks_per_window, "edit_window_mode": "block"},
                    ))
                    block_start += count
                    segment_index += 1
            for direction in ("DOWN", "UP"):
                operation_windows.append(self.run_fixed_window(
                    operation_execution_id=execution_id, operation_id=stage,
                    segment_index=segment_index, segment_label=f"SCROLL_{direction}",
                    window_kind="OPERATION", target_duration_s=target,
                    action_callback=lambda direction=direction: self.scroll_for_window(direction, target),
                    baseline_group_id=baseline_group_id,
                ))
                segment_index += 1
            sequence = self.map_fixed_window_sequence(
                operation_execution_id=execution_id, operation_id=stage,
                baseline_windows=baselines, operation_windows=operation_windows,
            )
            record["baseline_valid_window_count"] = sum(bool(item["support_eligible"]) for item in baselines)
            record["operation_window_count"] = len(operation_windows)
            record["operation_valid_window_count"] = sum(bool(item["support_eligible"]) for item in operation_windows)
            record["operation_partial_window_count"] = sum(item["window_quality"] == "PARTIAL_WINDOW" for item in operation_windows)
            record["operation_overrun_window_count"] = sum(item["window_quality"] == "OVERRUN_WINDOW" for item in operation_windows)
            record["operation_severe_overrun_count"] = sum(item["window_quality"] == "SEVERE_OVERRUN" for item in operation_windows)
            record["window_sequence_path"] = str(self.vma_mapping_dir / "operation_window_sequences.json")
            record["fixed_window_mapping_status"] = "OK"
            record["fixed_window_error"] = ""
            record["vma_mapping_status"] = "OK"
            record["report"] = ";".join(
                report for item in operation_windows for report in item.get("markdown_reports", [])
            )
            record["report_count"] = sum(len(item.get("markdown_reports", [])) for item in operation_windows)
            record["hash_mismatch_count"] = sum(int(item.get("hash_mismatch_count", 0)) for item in baselines + operation_windows)
            record["collection_quality"] = "OK" if not record["hash_mismatch_count"] else "HASH_MISMATCH"
            record["baseline_quality"] = (
                "OK" if record["baseline_valid_window_count"] >= 2
                else "SINGLE_BASELINE_WINDOW" if record["baseline_valid_window_count"] == 1
                else "NO_VALID_BASELINE_WINDOWS"
            )
            record["after"] = self.snapshot()
            record["success"] = all(item.get("action_quality") == "OK" for item in operation_windows)
            record["execution_aggregate"] = sequence["execution_aggregate"]
            return bool(record["success"])
        except (HdcError, OSError, ValueError, VmaJsonError) as exc:
            record["error"] = str(exc)
            record["fixed_window_mapping_status"] = "ERROR"
            record["fixed_window_error"] = str(exc)
            self.failures.append(f"{stage}: {exc}")
            return False
        finally:
            record["stage_total_elapsed_s"] = time.perf_counter() - started
            record["ended_at"] = now_iso()
            self.write_operation(record)

    def open_stage(self, index: int) -> bool:
        stage = "01_open_wps"
        started = time.perf_counter()
        record: dict[str, Any] = {
            "index": index, "stage": stage, "label": "打开 WPS", "operation": "清理残留后打开 WPS",
            "success": False, "started_at": now_iso(), "before": self.snapshot(),
            "baseline_enabled": True,
            **stage_baseline_semantics(stage),
        }
        try:
            self.force_stop_wps()
            time.sleep(2)
            record["operation_started_at"] = now_iso()
            op_started = time.perf_counter()
            try:
                self.start_wps()
                time.sleep(self.args.launch_wait_s)
            finally:
                record["operation_elapsed_s"] = time.perf_counter() - op_started
                record["operation_ended_at"] = now_iso()
            if not self.snapshot():
                raise HdcError("打开 WPS 后未发现进程")
            # Launch has no pre-existing WPS process to clear.  We clear
            # immediately after launch and record this exception explicitly.
            record["operation_clear_refs_started_at"] = now_iso()
            clear_started = time.perf_counter()
            self.clear_refs()
            clear_ended = time.perf_counter()
            record["operation_clear_refs_ended_at"] = now_iso()
            record["operation_clear_refs_elapsed_s"] = clear_ended - clear_started
            record["clear_refs_elapsed_s"] = record["operation_clear_refs_elapsed_s"]
            record["operation_window_started_at"] = now_iso()
            settle_started = time.perf_counter()
            time.sleep(3)
            record["settle_wait_s"] = time.perf_counter() - settle_started
            record["after"] = self.snapshot()
            record["operation_window_ended_at"] = now_iso()
            record["operation_window_s"] = time.perf_counter() - clear_ended
            sample = self.sample(index, stage, "POST_LAUNCH", record["after"])
            record.update(sample)
            record.update({
                "post_launch_report": sample["post_launch_report"],
                "post_launch_jsonl_report": sample["post_launch_jsonl_report"],
                "baseline_quality": "BASELINE_NOT_APPLICABLE",
                "activity_quality": "NO_BASELINE",
                "vma_mapping_status": "BASELINE_NOT_APPLICABLE",
                "vma_mapping_error": "",
                "paired_process_count": 0,
                "paired_vma_count": 0,
            })
            record["success"] = True
            self.capture_screen(stage)
            print(
                f"[wps-v6] {stage}: success operation={record['operation_elapsed_s']:.3f}s "
                f"collection={record['collection_elapsed_s']:.3f}s reports={record['report_count']}",
                flush=True,
            )
            return True
        except (HdcError, OSError, subprocess.SubprocessError) as exc:
            message = str(exc)
            self.failures.append(f"{stage}: {message}")
            record["error"] = message
            record["after"] = self.snapshot()
            print(f"[wps-v6] {stage}: FAILED: {message}", file=sys.stderr, flush=True)
            return False
        finally:
            record["stage_total_elapsed_s"] = time.perf_counter() - started
            record["ended_at"] = now_iso()
            self.write_operation(record)

    def reopen_stage(self, index: int) -> bool:
        """Measure reopening from a deliberately closed WPS baseline.

        Unlike ordinary measured stages, the operation starts with no WPS
        process.  WPS is launched as the stage precondition, then clear_refs
        is applied before the actual file-picker/open action.
        """
        stage = "08_reopen_saved_document"
        started = time.perf_counter()
        record: dict[str, Any] = {
            "index": index, "stage": stage, "label": "重新打开已保存 Word",
            "operation": "启动 WPS 后在文件选择器中输入本会话精确文件名并打开",
            "success": False, "started_at": now_iso(), "before": self.snapshot(),
        }
        try:
            self.start_wps()
            time.sleep(self.args.launch_wait_s)
            if not self.snapshot():
                raise HdcError("重新打开阶段启动 WPS 后未发现进程")
            self._collect_idle_baseline(record, index, stage)
            self._collect_operation_sample(
                record,
                index,
                stage,
                lambda: self.open_saved_document(start_wps=False),
                6,
            )
            self._map_operation_vmas(record, stage)
            record["success"] = True
            print(
                f"[wps-v6] {stage}: success operation={record['operation_elapsed_s']:.3f}s "
                f"collection={record['collection_elapsed_s']:.3f}s reports={record['report_count']}",
                flush=True,
            )
            return True
        except (HdcError, OSError, subprocess.SubprocessError) as exc:
            message = str(exc)
            self.failures.append(f"{stage}: {message}")
            record["error"] = message
            record["after"] = self.snapshot()
            print(f"[wps-v6] {stage}: FAILED: {message}", file=sys.stderr, flush=True)
            return False
        finally:
            record["stage_total_elapsed_s"] = time.perf_counter() - started
            record["ended_at"] = now_iso()
            self.write_operation(record)
            self.capture_screen(stage)

    def close_wps(self, index: int, label: str) -> bool:
        started = time.perf_counter()
        before = self.snapshot()
        record: dict[str, Any] = {
            "index": index, "stage": label, "label": label,
            "operation": "正常关闭文档和 WPS；必要时记录 force-stop 回退",
            "success": False, "started_at": now_iso(), "before": before,
        }
        op_started = time.perf_counter()
        try:
            # Close current document tab, then close the WPS window.  These
            # are native window coordinates already verified on this device.
            self.ui_click(1695, 478)
            time.sleep(2)
            self.ui_click(2675, 475)
            time.sleep(5)
            after = self.snapshot()
            if after:
                self.force_stop_used = True
                record["error"] = "正常关闭后仍有 WPS 进程，已按回退规则使用 aa force-stop"
                self.force_stop_wps()
                time.sleep(3)
                after = self.snapshot()
            record["after"] = after
            record["success"] = not after
            if after:
                raise HdcError("force-stop 后仍存在 WPS 相关进程")
            if label == "close_before_reopen":
                self.normal_close_before_reopen = not self.force_stop_used
            else:
                self.final_close_success = True
            return True
        except (HdcError, OSError, subprocess.SubprocessError) as exc:
            message = str(exc)
            record["error"] = message
            self.failures.append(f"{label}: {message}")
            record["after"] = self.snapshot()
            return False
        finally:
            record["operation_elapsed_s"] = time.perf_counter() - op_started
            record["operation_ended_at"] = now_iso()
            record["stage_total_elapsed_s"] = time.perf_counter() - started
            record["ended_at"] = now_iso()
            self.write_operation(record)
            self.capture_screen(label)
            print(
                f"[wps-v6] {label}: {'success' if record['success'] else 'failed'} "
                f"operation={record['operation_elapsed_s']:.3f}s force_stop={self.force_stop_used}",
                flush=True,
            )

    def write_memory_summary(self) -> None:
        path = self.local_out / "memory_summary.csv"
        fields = [
            "stage", "pid", "process_name", "rss_kib", "pss_kib", "referenced_kib", "swap_kib",
            "operation_elapsed_s", "collection_elapsed_s", "report",
        ]
        timings = {item.get("stage"): item for item in self.timing_records}
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in self.report_records:
                timing = timings.get(item["stage"], {})
                writer.writerow({
                    **{field: item.get(field, "") for field in fields},
                    "operation_elapsed_s": f"{timing.get('operation_elapsed_s', 0.0):.6f}",
                    "collection_elapsed_s": f"{timing.get('collection_elapsed_s', 0.0):.6f}",
                })

    def hash_summary(self) -> dict[str, int]:
        names = set(self.device_report_hashes) | set(self.local_report_hashes)
        matched = sum(
            name in self.device_report_hashes
            and name in self.local_report_hashes
            and self.device_report_hashes[name] == self.local_report_hashes[name]
            for name in names
        )
        return {
            "device_report_count": len(self.device_report_hashes),
            "local_report_count": len(self.local_report_hashes),
            "matched_report_count": matched,
            "hash_mismatch_count": sum(
                name in self.device_report_hashes
                and name in self.local_report_hashes
                and self.device_report_hashes[name] != self.local_report_hashes[name]
                for name in names
            ),
            "missing_local_count": len(set(self.device_report_hashes) - set(self.local_report_hashes)),
            "missing_device_count": len(set(self.local_report_hashes) - set(self.device_report_hashes)),
        }

    def write_experiment_summary(self) -> None:
        operations = []
        if self.operations_path.is_file():
            with self.operations_path.open(encoding="utf-8", newline="") as handle:
                operations = list(csv.DictReader(handle))
        by_stage: dict[str, list[dict[str, Any]]] = {}
        for item in self.report_records:
            by_stage.setdefault(item["stage"], []).append(item)
        lines = [
            f"# WPS HarmonyOS v6 正式实验总结 — `{self.session_id}`",
            "",
            f"- 设备：`{self.device.target}`；包名：`{BUNDLE}`；采集器：`mem_analyze-v6 --with-vma`。",
            f"- 自动化全部关键阶段成功：`{'是' if all(row.get('success') == 'true' for row in operations if row.get('stage','').startswith(('0','close'))) else '否'}`。",
            f"- Word 实际保存：`{'是' if self.saved_document else '否'}`。",
        ]
        if self.saved_document:
            lines.extend([
                f"- 保存文件真实路径：`{self.saved_document.get('final_path', self.saved_document.get('path',''))}`。",
                f"- 文件大小：`{self.saved_document.get('size_bytes', 0)} bytes`；设备修改时间：`{self.saved_document.get('mtime', '')}`。",
                f"- 重新打开验证：`{'是' if self.reopen_verified else '否'}`。原始保存路径：`{self.saved_document.get('original_path', '')}`。",
                f"- Word 正文固定测试序列号和时间/目的/操作链/初步结论标记：`{'是' if self.saved_document.get('content_markers_verified') else '否'}`。",
            ])
        lines.extend([
            f"- 关闭前正常关闭无 force-stop：`{'是' if self.normal_close_before_reopen else '否'}`；最终 WPS 已退出：`{'是' if self.final_close_success else '否'}`；force-stop 回退：`{'是' if self.force_stop_used else '否'}`。",
            "",
            "## 阶段耗时与聚合内存",
            "",
            "| stage | success | operation s | settle s | collection s | pull s | reports | RSS KiB | PSS KiB | Referenced KiB | Swap KiB |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        peak_stage = ""
        peak_rss = -1
        for row in operations:
            stage = row.get("stage", "")
            if not stage or stage.startswith("close"):
                continue
            metrics = by_stage.get(stage, [])
            sums = {key: sum(int(item.get(key, 0) or 0) for item in metrics) for key in ("rss_kib", "pss_kib", "referenced_kib", "swap_kib")}
            rss = sums["rss_kib"]
            if rss > peak_rss:
                peak_rss, peak_stage = rss, stage
            lines.append(
                f"| {stage} | {row.get('success','')} | {float(row.get('operation_elapsed_s') or 0):.3f} | "
                f"{float(row.get('settle_wait_s') or 0):.3f} | {float(row.get('collection_elapsed_s') or 0):.3f} | "
                f"{float(row.get('report_pull_elapsed_s') or 0):.3f} | {row.get('report_count','0')} | "
                f"{sums['rss_kib']} | {sums['pss_kib']} | {sums['referenced_kib']} | {sums['swap_kib']} |"
            )
        lines.extend([
            "",
            f"- RSS 聚合峰值阶段：`{peak_stage}`（{peak_rss} KiB）。",
            "- RSS/PSS/Referenced/Swap 是独立列，未将 Referenced 当作 RSS 增量；Referenced 表示 clear_refs 后观察窗口内访问到的驻留页。",
            "",
            "## 关键变化",
            "",
        ])
        stage_sums = {
            stage: {key: sum(int(item.get(key, 0) or 0) for item in items) for key in ("rss_kib", "pss_kib", "referenced_kib", "swap_kib")}
            for stage, items in by_stage.items()
        }
        for left, right, label in (
            ("03_write_metadata", "04_heavy_edit_scroll", "写入元数据到重编辑"),
            ("04_heavy_edit_scroll", "05_save_document", "重编辑到保存"),
            ("06_background", "07_foreground", "后台到前台"),
            ("07_foreground", "08_reopen_saved_document", "前台到重新打开"),
        ):
            if left in stage_sums and right in stage_sums:
                delta = {key: stage_sums[right][key] - stage_sums[left][key] for key in stage_sums[left]}
                lines.append(f"- {label}：RSS `{delta['rss_kib']:+d}` KiB；PSS `{delta['pss_kib']:+d}` KiB；Referenced `{delta['referenced_kib']:+d}` KiB；Swap `{delta['swap_kib']:+d}` KiB。")
        hashes = self.hash_summary()
        lines.extend([
            "",
            "## 报告一致性",
            "",
            f"`device_report_count={hashes['device_report_count']}`, `local_report_count={hashes['local_report_count']}`, `matched_report_count={hashes['matched_report_count']}`, `hash_mismatch_count={hashes['hash_mismatch_count']}`, `missing_local_count={hashes['missing_local_count']}`, `missing_device_count={hashes['missing_device_count']}`。",
            "",
            "## 失败或不确定项",
            "",
        ])
        if self.failures:
            lines.extend(f"- {failure}" for failure in self.failures)
        else:
            lines.append("- 未记录失败项；重新打开成功依据为设备文件已验证、文件选择器双击完成、WPS 进程仍存活并取得重新打开截图。")
        (self.local_out / "experiment_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_metadata_file(self, return_code: int) -> None:
        self.write_memory_summary()
        self.write_experiment_summary()
        hashes = self.hash_summary()
        operation_rows: list[dict[str, str]] = []
        if self.operations_path.is_file():
            with self.operations_path.open(encoding="utf-8", newline="") as handle:
                operation_rows = list(csv.DictReader(handle))
        valid_baselines = [
            row for row in operation_rows
            if row.get("stage", "").startswith("0")
            and row.get("baseline_status") == "ENABLED"
            and row.get("baseline_report")
            and row.get("baseline_jsonl_report")
            and row.get("vma_mapping_status") == "OK"
        ]
        file_sample_path = self.vma_mapping_dir / "operation_file_vma_samples.jsonl"
        anon_sample_path = self.vma_mapping_dir / "operation_anon_vma_samples.jsonl"
        file_samples_available = file_sample_path.is_file() and file_sample_path.stat().st_size > 0
        anon_samples_available = anon_sample_path.is_file() and anon_sample_path.stat().st_size > 0
        readiness = {
            "ready_for_idle_baseline_collection": bool(valid_baselines),
            "ready_for_file_vma_mapping": bool(valid_baselines) and file_samples_available,
            "ready_for_anon_aux_features": bool(valid_baselines) and anon_samples_available,
            "ready_for_operation_recognition": False,
            "ready_for_apply": False,
        }
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "target": self.device.target,
            "bundle": BUNDLE,
            "ability": ABILITY,
            "collector": "mem_analyze-v6.c",
            "collector_semantics": "idle baseline clear_refs/sample -> operation clear_refs/action/sample -> time-normalized VMA mapping",
            "vma_schema_version": "homeny.vma.v1",
            "vma_mapping_config": self.vma_mapping_config,
            "started_at": self.started_at,
            "finished_at": now_iso(),
            "return_code": return_code,
            "failures": self.failures,
            "warnings": self.warnings,
            "local_output": str(self.local_out),
            "device_output": self.device_out,
            "device_screenshot_output": self.device_screenshot_out,
            "screenshots": self.screenshots,
            "document": self.saved_document,
            "document_saved": bool(self.saved_document),
            "reopen_verified": self.reopen_verified,
            "normal_close_before_reopen": self.normal_close_before_reopen,
            "final_close_success": self.final_close_success,
            "force_stop_used": self.force_stop_used,
            "report_hash_verification": hashes,
            "readiness": readiness,
            "timing": self.timing_records,
            "timing_totals": {
                "stage_total_elapsed_s": round(sum(float(item.get("stage_total_elapsed_s", 0.0) or 0.0) for item in self.timing_records), 6),
                "operation_elapsed_s": round(sum(float(item.get("operation_elapsed_s", 0.0) or 0.0) for item in self.timing_records), 6),
                "collection_elapsed_s": round(sum(float(item.get("collection_elapsed_s", 0.0) or 0.0) for item in self.timing_records), 6),
                "report_pull_elapsed_s": round(sum(float(item.get("report_pull_elapsed_s", 0.0) or 0.0) for item in self.timing_records), 6),
            },
            "notes": [
                "01_open_wps 在没有 WPS 进程的干净起点启动后生成 POST_LAUNCH 样本；普通阶段采集 idle baseline 后再次 clear_refs 再执行 operation。",
                "Referenced 只覆盖 clear_refs 后到 smaps 读取之间访问过的驻留页；RSS、PSS、Referenced、Swap 分列聚合。",
                "baseline 时间缩放使用 TIME_NORMALIZED_REFERENCED_HEURISTIC，只是后台噪声估计，不是精确集合差。",
                "collection_elapsed_s 包含设备端报告生成和全部报告拉回；report_pull_elapsed_s 单独记录 HDC 拉回耗时。",
                "WPS 编辑区是 XComponent，uitest 不能读取正文；保存文件、设备路径/大小/mtime、重新打开截图和最终进程状态作为验证证据。",
                f"Word 固定测试序列号：{self.args.test_serial}；截图仅由脚本自动保存，不参与成功判定。",
                "报告在拉回前计算设备端 SHA-256，拉回后计算本机 SHA-256；report_hashes.csv 保存逐文件清单。",
                "ready_for_operation_recognition=false；ready_for_apply=false。",
            ],
        }
        (self.local_out / "session_metadata.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def run(self) -> int:
        self.verify_access()
        self.build_and_push()
        self.record_document_baseline()
        index = 1
        self.open_stage(index)
        index += 1
        self.measured_stage(index, "02_new_word", "新建 Word 文档", "打开新建菜单、选择 Word、创建空白文档", self.new_word, 5)
        index += 1
        self.measured_stage(index, "03_write_metadata", "写入时间、目的、操作链和初步结论", "写入实验元数据", self.write_metadata, 5)
        index += 1
        self.measured_stage(index, "04_heavy_edit_scroll", "写入大文本、换行、翻页、滚动和光标移动", "高负载文档编辑与导航", self.heavy_edit_scroll, 8)
        index += 1
        self.measured_stage(index, "05_save_document", "保存 Word 文档并验证设备文件", "保存到用户可见 Desktop 并检查真实路径/大小/mtime", self.save_document, 5)
        index += 1
        self.measured_stage(index, "06_background", "切换 WPS 到后台", "Home 切后台", lambda: self.ui_key(KEY_HOME), 4)
        index += 1
        self.measured_stage(index, "07_foreground", "切回 WPS 前台", "重新拉起 WPS 前台", self.start_wps, 4)
        index += 1
        self.close_wps(index, "close_before_reopen")
        if self.saved_document:
            try:
                self.rename_saved_document()
            except HdcError as exc:
                self.failures.append(f"rename_saved_document: {exc}")
        index += 1
        self.reopen_stage(index)
        index += 1
        self.measured_stage(index, "09_reopen_edit_scroll", "重新打开后滚动、翻页和少量编辑", "重新打开文档的轻量编辑与导航", self.reopen_edit_scroll, 6)
        index += 1
        self.close_wps(index, "close_final")
        return 1 if self.failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HarmonyOS WPS v6 document workflow and memory collector")
    parser.add_argument("--target", help="hdc target serial")
    parser.add_argument("--out", help="local output directory")
    parser.add_argument("--device-dir", default=DEFAULT_DEVICE_DIR)
    parser.add_argument("--device-out", default=DEFAULT_DEVICE_OUT_ROOT)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--no-build", action="store_true", help="reuse v6 device binary")
    parser.add_argument("--launch-wait-s", type=float, default=10.0)
    parser.add_argument("--editor-x", type=int, default=1100, help="WPS XComponent text focus x")
    parser.add_argument("--editor-y", type=int, default=1020, help="WPS XComponent text focus y")
    parser.add_argument("--heavy-repeats", type=int, default=180, help="repeated paragraphs in heavy phase")
    parser.add_argument("--test-serial", default=DEFAULT_TEST_SERIAL, help="fixed ASCII test serial inserted into the Word document")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--idle-baseline", dest="idle_baseline", action="store_true", help="collect an idle baseline before ordinary operations (default)")
    baseline.add_argument("--no-idle-baseline", dest="idle_baseline", action="store_false", help="disable idle baseline collection")
    parser.set_defaults(idle_baseline=True)
    parser.add_argument("--baseline-window-s", type=float, default=5.0, help="configured idle baseline wait; actual window is measured with monotonic time")
    fixed = parser.add_mutually_exclusive_group()
    fixed.add_argument("--fixed-windows", dest="fixed_windows", action="store_true")
    fixed.add_argument("--no-fixed-windows", dest="fixed_windows", action="store_false")
    parser.set_defaults(fixed_windows=True)
    parser.add_argument("--fixed-window-s", type=float, default=5.0)
    parser.add_argument("--baseline-window-count", type=int, default=2)
    parser.add_argument("--fixed-window-ok-tolerance-s", type=float, default=0.5)
    parser.add_argument("--blocks-per-window", type=int, default=1)
    parser.add_argument("--vma-mapping-config", default="", help="path to vma_mapping_config.json")
    parser.add_argument("--disable-vma-mapping", action="store_true", help="collect reports without baseline/operation VMA pairing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.baseline_window_s < 0:
        print("error: --baseline-window-s must be >= 0", file=sys.stderr)
        return 2
    if args.fixed_window_s <= 0 or args.baseline_window_count < 1 or args.fixed_window_ok_tolerance_s < 0:
        print("error: invalid fixed-window configuration", file=sys.stderr)
        return 2
    session: Session | None = None
    return_code = 2
    try:
        session = Session(args)
        return_code = session.run()
        return return_code
    except (HdcError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if session is not None:
            session.failures.append(str(exc))
        return return_code
    finally:
        if session is not None:
            try:
                session.write_metadata_file(return_code)
            finally:
                session.close_files()


if __name__ == "__main__":
    raise SystemExit(main())
