#!/usr/bin/env python3
"""Windows/hdc session helpers for the Douyu operation-VMA dataset."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


BUNDLE = "com.douyu.ho.app"
ABILITY = "EntryAbility"
DEFAULT_DEVICE_DIR = "/data/local/tmp/mem_analyze_v6"
KEY_HOME = "1"
KEY_BACK = "2"
KEY_ENTER = "2054"
KEY_CTRL_LEFT = "2072"
KEY_A = "2017"


class HdcError(RuntimeError):
    pass


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def q(value: str) -> str:
    return shlex.quote(str(value))


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
        raise HdcError(f"命令失败({result.returncode}): {' '.join(command)}\n{result.stdout or ''}")
    return result


def find_hdc() -> str:
    configured = os.environ.get("HDC", "").strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
        if path.is_dir():
            for name in ("hdc.exe", "hdc"):
                candidate = path / name
                if candidate.is_file():
                    return str(candidate)
    found = shutil.which("hdc")
    if found:
        return found
    raise HdcError("找不到 hdc，请先设置 HDC 或把 hdc 加入 PATH")


def list_targets(hdc: str) -> list[str]:
    result = run_host([hdc, "list", "targets"])
    targets: list[str] = []
    for line in (result.stdout or "").replace("\r", "").splitlines():
        fields = line.strip().split()
        if fields and not fields[0].startswith("[") and fields[0] not in targets:
            targets.append(fields[0])
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
        output = (result.stdout or "").strip()
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


def process_snapshot(device: Device) -> list[dict[str, str]]:
    output = device.shell("ps -A -o PID,PPID,UID,VSZ,RSS,ARGS", check=False)
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=5)
        if len(fields) < 6 or BUNDLE not in fields[5]:
            continue
        rows.append({
            "pid": fields[0],
            "ppid": fields[1],
            "uid": fields[2],
            "vsz_kb": fields[3],
            "rss_kb": fields[4],
            "args": fields[5],
        })
    return rows


class DouyuSession:
    def __init__(self, args: argparse.Namespace, trial_dir: Path, session_id: str):
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
            raise HdcError(f"检测到多个设备，请使用 -Target 指定: {targets}")
        self.device = Device(self.hdc, target)
        self.script_dir = Path(__file__).resolve().parent
        self.trial_dir = trial_dir
        self.trial_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.device_dir = str(args.device_dir).rstrip("/")
        self.device_out = f"{self.device_dir}/douyu_reports/{session_id}"
        self.device_bin = f"{self.device_dir}/mem_analyze-v6"
        self.report_hash_path = self.trial_dir / "report_hashes.csv"
        self.report_hash_file = self.report_hash_path.open("w", encoding="utf-8", newline="")
        self.hash_writer = csv.DictWriter(
            self.report_hash_file,
            fieldnames=["report", "device_path", "local_path", "device_sha256", "local_sha256", "match"],
        )
        self.hash_writer.writeheader()
        self.report_hash_file.flush()
        self.state = "unknown"
        self.window_index = 0
        self.state_log: list[dict[str, str]] = []

    def close(self) -> None:
        if not self.report_hash_file.closed:
            self.report_hash_file.flush()
            self.report_hash_file.close()

    def verify_access(self) -> None:
        identity = self.device.shell("id")
        if "uid=0" not in identity and "uid:0" not in identity:
            raise HdcError(f"hdc shell 不是 root: {identity}")
        self.device.shell(
            "test -r /proc/1/maps -a -r /proc/1/smaps -a -r /proc/1/pagemap "
            "-a -w /proc/self/clear_refs"
        )
        self.device.shell(
            f"mkdir -p {q(self.device_dir)} {q(self.device_out)}"
        )

    def build_and_push(self) -> None:
        if self.args.no_build:
            local_bin = self.script_dir / "mem_analyze-v6-ohos"
        else:
            sdk_text = os.environ.get(
                "OHOS_SDK",
                r"D:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native",
            )
            sdk = Path(sdk_text)
            clang = sdk / "llvm" / "bin" / "clang.exe"
            sysroot = sdk / "sysroot"
            if not clang.is_file():
                raise HdcError(f"OpenHarmony clang 不存在: {clang}")
            if not sysroot.is_dir():
                raise HdcError(f"OpenHarmony sysroot 不存在: {sysroot}")
            temp_dir = Path(tempfile.mkdtemp(prefix="douyu-v6-"))
            local_bin = temp_dir / "mem_analyze-v6-ohos"
            run_host([
                str(clang), "-O2", "-std=c11", "-Wall", "-Wextra",
                "-target", "aarch64-linux-ohos", f"--sysroot={sysroot}",
                "-o", str(local_bin), str(self.script_dir / "mem_analyze-v6.c"),
            ], timeout_s=180.0)
        if not local_bin.is_file():
            raise HdcError(f"采集器不存在: {local_bin}")
        self.device.send(local_bin, self.device_bin)
        self.device.shell(f"chmod 755 {q(self.device_bin)}")

    def snapshot(self) -> list[dict[str, str]]:
        return process_snapshot(self.device)

    def start_app(self) -> dict[str, Any]:
        self.device.shell(f"aa start -a {q(ABILITY)} -b {q(BUNDLE)}", timeout_s=120.0)
        time.sleep(float(self.args.launch_wait_s))
        alive = bool(self.snapshot())
        self.state = "home" if alive else "unknown"
        return {"process_alive": alive, "action": "aa start"}

    def force_stop(self) -> dict[str, Any]:
        output = self.device.shell(f"aa force-stop {q(BUNDLE)}", check=False)
        time.sleep(1.0)
        self.state = "stopped"
        return {"action": "aa force-stop", "output": output[-200:]}

    def ui_key(self, key: str) -> None:
        self.device.shell(f"uitest uiInput keyEvent {q(key)}", timeout_s=60.0)

    def ui_key_chord(self, *keys: str) -> None:
        self.device.shell(
            "uitest uiInput keyEvent " + " ".join(q(key) for key in keys),
            timeout_s=60.0,
        )

    def point(self, x: float, y: float) -> tuple[int, int]:
        return int(self.args.screen_width * x), int(self.args.screen_height * y)

    def ui_click_frac(self, x: float, y: float) -> None:
        px, py = self.point(x, y)
        self.device.shell(f"uitest uiInput click {px} {py}", timeout_s=60.0)

    def ui_swipe_frac(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 800) -> None:
        ax, ay = self.point(x1, y1)
        bx, by = self.point(x2, y2)
        self.device.shell(f"uitest uiInput swipe {ax} {ay} {bx} {by} {duration_ms}", timeout_s=60.0)

    def ui_text(self, value: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.:/+\- ]+", "_", value)
        if safe:
            self.device.shell(f"uitest uiInput text x{safe}", timeout_s=120.0)

    def reset_home(self) -> None:
        self.force_stop()
        self.start_app()
        if not self.snapshot():
            raise HdcError("启动斗鱼后未发现进程")
        self.state = "home"
        time.sleep(1.0)

    def search_live_room(self, query: str | None = None) -> dict[str, Any]:
        term = query or self.args.search_term
        self.ui_click_frac(0.40, 0.095)
        self.ui_key_chord(KEY_CTRL_LEFT, KEY_A)
        self.ui_text(term)
        self.ui_key(KEY_ENTER)
        time.sleep(float(self.args.ui_wait_s))
        alive = bool(self.snapshot())
        self.state = "results" if alive else "unknown"
        return {"query": term, "process_alive": alive}

    def enter_live_room(self) -> dict[str, Any]:
        self.ui_click_frac(0.14, 0.61)
        time.sleep(float(self.args.room_wait_s))
        alive = bool(self.snapshot())
        self.state = "room" if alive else "unknown"
        return {"process_alive": alive, "room_click": "first_result"}

    def switch_video_tab(self) -> dict[str, Any]:
        self.ui_click_frac(0.46, 0.18)
        time.sleep(float(self.args.ui_wait_s))
        return {"process_alive": bool(self.snapshot()), "tab": "video"}

    def switch_chat_tab(self) -> dict[str, Any]:
        self.ui_click_frac(0.56, 0.18)
        time.sleep(float(self.args.ui_wait_s))
        return {"process_alive": bool(self.snapshot()), "tab": "chat"}

    def play_pause_video(self) -> dict[str, Any]:
        self.ui_click_frac(0.50, 0.48)
        time.sleep(float(self.args.ui_wait_s))
        return {"process_alive": bool(self.snapshot()), "video_click": "center"}

    def scroll_live_room(self) -> dict[str, Any]:
        self.ui_swipe_frac(0.50, 0.72, 0.50, 0.34)
        time.sleep(float(self.args.ui_wait_s))
        self.ui_swipe_frac(0.50, 0.34, 0.50, 0.72)
        return {"process_alive": bool(self.snapshot()), "swipes": 2}

    def back_to_home(self) -> dict[str, Any]:
        self.ui_key(KEY_BACK)
        time.sleep(float(self.args.ui_wait_s))
        alive = bool(self.snapshot())
        self.state = "home" if alive else "unknown"
        return {"process_alive": alive, "key": "BACK"}

    def background_app(self) -> dict[str, Any]:
        self.ui_key(KEY_HOME)
        time.sleep(float(self.args.ui_wait_s))
        alive = bool(self.snapshot())
        self.state = "background" if alive else "unknown"
        return {"process_alive": alive, "key": "HOME"}

    def restore_app(self) -> dict[str, Any]:
        result = self.start_app()
        self.state = "home"
        return {**result, "action": "restore"}

    def restart_app(self) -> dict[str, Any]:
        self.force_stop()
        result = self.start_app()
        self.state = "home"
        return {**result, "action": "restart"}

    def switch_live_room(self) -> dict[str, Any]:
        self.back_to_home()
        self.search_live_room(self.args.second_search_term)
        result = self.enter_live_room()
        result["query"] = self.args.second_search_term
        return result

    def clear_refs(self) -> None:
        self.device.shell(f"{q(self.device_bin)} --clear-refs --app {q(BUNDLE)}", timeout_s=180.0)

    def sample_reports(self, label: str) -> dict[str, Any]:
        self.window_index += 1
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)
        remote = f"{self.device_out}/referenced_{self.window_index:03d}_{safe}_{stamp}.md"
        output = self.device.shell(
            f"{q(self.device_bin)} --app {q(BUNDLE)} -o {q(remote)} --with-vma",
            timeout_s=300.0,
        )
        remote_reports: list[str] = []
        for line in output.splitlines():
            match = re.search(r"报告已写入:\s*(\S+)$", line)
            if match and match.group(1) not in remote_reports:
                remote_reports.append(match.group(1))
        if not remote_reports:
            for token in re.findall(r"/\S+\.md", output):
                if token not in remote_reports:
                    remote_reports.append(token.rstrip(".,"))
        if not remote_reports:
            raise HdcError(f"采集器没有返回报告路径: {output}")

        local_reports: list[str] = []
        mismatch = 0
        for remote_report in remote_reports:
            remote_hash = self.device.shell(f"sha256sum {q(remote_report)} | cut -d ' ' -f 1")
            local = self.trial_dir / Path(remote_report).name
            self.device.recv(remote_report, local)
            if not local.is_file() or local.stat().st_size == 0:
                raise HdcError(f"报告未拉回或为空: {local}")
            local_hash = sha256_file(local)
            matched = remote_hash.strip() == local_hash
            mismatch += int(not matched)
            self.hash_writer.writerow({
                "report": local.name,
                "device_path": remote_report,
                "local_path": str(local),
                "device_sha256": remote_hash.strip(),
                "local_sha256": local_hash,
                "match": str(matched).lower(),
            })
            local_reports.append(str(local))
        self.report_hash_file.flush()
        return {
            "report_paths": local_reports,
            "report_count": len(local_reports),
            "hash_mismatch_count": mismatch,
            "collection_quality": "pass" if mismatch == 0 else "hash_mismatch",
        }

    def collect_window(
        self,
        *,
        operation_id: str,
        phase: str,
        wait_s: float,
        action: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started_at = now_iso()
        started = time.perf_counter()
        before = self.snapshot()
        self.clear_refs()
        action_started_at = now_iso()
        action_started = time.perf_counter()
        action_result: dict[str, Any] = {}
        if action is not None:
            action_result = action() or {}
        action_ended_at = now_iso()
        elapsed = time.perf_counter() - started
        time.sleep(max(float(wait_s) - elapsed, 0.0))
        sample = self.sample_reports(f"{operation_id}_{phase}")
        return {
            "window_id": f"{self.session_id}_{self.window_index:03d}_{phase.lower()}",
            "operation_id": operation_id,
            "segment_label": phase,
            "window_kind": "BASELINE" if phase.startswith("BASELINE") else "OPERATION",
            "status": "success",
            "window_started_at": started_at,
            "window_ended_at": now_iso(),
            "action_started_at": action_started_at if action is not None else "",
            "action_ended_at": action_ended_at if action is not None else "",
            "window_elapsed_s": round(time.perf_counter() - started, 6),
            "action_elapsed_s": round(time.perf_counter() - action_started, 6) if action is not None else 0.0,
            "before_process_count": len(before),
            "action_result": action_result,
            **sample,
        }

    def collect_labeled_operation(
        self,
        *,
        trial_id: str,
        label_id: int,
        operation_label: str,
        family: str,
        precondition: str,
        action: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        execution_id = f"{self.session_id}_{trial_id}_{operation_label.lower()}"
        baselines: list[dict[str, Any]] = []
        for index in range(1, int(self.args.baseline_window_count) + 1):
            window = self.collect_window(
                operation_id=operation_label,
                phase=f"BASELINE_{index:02d}",
                wait_s=float(self.args.baseline_window_s),
            )
            window["baseline_index"] = index
            baselines.append(window)
        action_window = self.collect_window(
            operation_id=operation_label,
            phase="ACTION",
            wait_s=float(self.args.action_window_s),
            action=action,
        )
        post_window = self.collect_window(
            operation_id=operation_label,
            phase="POST_ACTION",
            wait_s=float(self.args.post_window_s),
        )
        return {
            "schema_version": "douyu.operation-sample.v1",
            "status": "success",
            "sample_id": f"douyu_{trial_id}_{operation_label.lower()}",
            "app_id": "douyu_pc",
            "trial_id": trial_id,
            "session_id": self.session_id,
            "label_id": label_id,
            "operation_label": operation_label,
            "operation_family": family,
            "precondition": precondition,
            "execution_id": execution_id,
            "baseline_window_count": len(baselines),
            "action_window_s": float(self.args.action_window_s),
            "post_window_s": float(self.args.post_window_s),
            "baseline_windows": baselines,
            "operation_windows": [action_window, post_window],
            "device_target": self.device.target,
            "collector_version": "mem_analyze-v6-with-vma",
            "state_after_action": self.state,
            "sample_started_at": baselines[0]["window_started_at"],
            "sample_ended_at": post_window["window_ended_at"],
        }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-Target", "--target", default="", help="hdc target serial")
    parser.add_argument("-Out", "--out", required=True, type=Path, help="trial raw output directory")
    parser.add_argument("-DeviceDir", "--device-dir", default=DEFAULT_DEVICE_DIR)
    parser.add_argument("-NoBuild", "--no-build", action="store_true")
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
    return parser
