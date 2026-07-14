#!/usr/bin/env python3
"""Linux desktop application automation runner.

The runner executes a JSON scenario with actions such as launching apps,
switching windows, sending keys, clicking, typing, waiting, and closing apps.
It is intentionally thin: Linux desktop automation still depends on the
session's window system permissions and tools such as xdotool/wmctrl.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import signal
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AutomationError(RuntimeError):
    pass


@dataclass
class WindowInfo:
    window_id: str
    title: str = ""
    wm_class: str = ""
    pid: int = 0
    pid_comm: str = ""
    cgroup_path: str = ""
    cgroup_unit: str = ""
    mapped_app: str = "UNKNOWN"
    width: int = 0
    height: int = 0
    visible: bool = True


@dataclass
class Context:
    dry_run: bool
    processes: dict[str, subprocess.Popen[Any] | str] = field(default_factory=dict)
    """Tracked processes. Value is either a Popen object or a systemd unit name (str)."""
    trace: "TraceWriter | None" = None
    session_id: str = ""
    scenario_id: str = ""
    test_slice: str = ""
    validation_mode: bool = False


@dataclass(frozen=True)
class Scenario:
    actions: list[dict[str, Any]]
    keep_alive_after_s: float = 0.0
    validation_mode: bool = False


TRACE_FIELDS = [
    "session_id",
    "ts_ns",
    "ts_iso",
    "timestamp",
    "scenario_id",
    "step_id",
    "phase",
    "action",
    "op_type",
    "event_type",
    "app",
    "app_key",
    "label",
    "status",
    "validation_mode",
    "optional",
    "command",
    "window_match",
    "pid",
    "tgid",
    "cgroup_path",
    "window_id",
    "window_title",
    "error",
]


class TraceWriter:
    def __init__(self, path: str | Path, session_id: str, scenario_id: str) -> None:
        self.path = Path(path)
        self.session_id = session_id
        self.scenario_id = scenario_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=TRACE_FIELDS)
        self._writer.writeheader()
        self._file.flush()

    def write(self, row: dict[str, Any]) -> None:
        now_ns = time.time_ns()
        payload = {
            "session_id": self.session_id,
            "ts_ns": now_ns,
            "ts_iso": dt.datetime.now().isoformat(timespec="microseconds"),
            "scenario_id": self.scenario_id,
            **row,
        }
        payload.setdefault("timestamp", payload["ts_iso"])
        self._writer.writerow({field: payload.get(field, "") for field in TRACE_FIELDS})
        self._file.flush()

    def close(self) -> None:
        self._file.flush()
        self._file.close()


# ---------------------------------------------------------------------------
# cgroup helpers (systemd-run --user)
# ---------------------------------------------------------------------------

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize_unit_name(name: str) -> str:
    sanitized = _SANITIZE_RE.sub("-", name).strip("-._")
    return sanitized or "unnamed"


def _systemd_user_available() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-units"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _cgroup_available() -> bool:
    return shutil.which("systemd-run") is not None and _systemd_user_available()


# Environment variable names that systemd-run should forward to the service
# so that GUI applications can connect to the display and session bus.
_GUI_ENV_KEYS = frozenset({
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP",
    "GDK_BACKEND", "QT_QPA_PLATFORM", "MOZ_ENABLE_WAYLAND",
    "GTK_MODULES", "DESKTOP_AUTOPLAY",
    "HOME", "USER", "LOGNAME", "PATH",
})


def _sanitize_unit(name: str) -> str:
    return f"automation-{_sanitize_unit_name(name)}"


def _inject_env(args: list[str], env: dict[str, str]) -> list[str]:
    """Prepend ``--setenv=KEY=VALUE`` arguments for every GUI-relevant env var."""
    result = list(args)
    for key in sorted(env):
        if key in _GUI_ENV_KEYS and env[key]:
            result.insert(1, f"--setenv={key}={env[key]}")
    return result


def _cgroup_launch(command: str, name: str, env: dict[str, str], test_slice: str = "") -> str:
    """Launch *command* (simple, no shell syntax) in a systemd scope.

    Uses ``--scope`` so the cgroup stays alive as long as **any** child
    process is running — essential for GUI apps that daemonise on startup.

    If *test_slice* is set, the scope is placed under that slice via ``--slice``.
    Returns the unit name (``.scope`` suffix).
    """
    unit_name = _sanitize_unit(name)
    unit = f"{unit_name}.scope"
    base = ["systemd-run", "--user", "--scope", f"--unit={unit_name}"]
    if test_slice:
        base.append(f"--slice={test_slice}")
    args = _inject_env(base, env)
    args.extend(shlex.split(command))
    # systemd-run --scope blocks as long as the scope has processes.
    # Run in the background so the automation can continue.
    subprocess.Popen(args, env=env)
    return unit


def _cgroup_launch_shell(command: str, name: str, env: dict[str, str], test_slice: str = "") -> str:
    """Launch a full *shell* command in a systemd scope.

    ``nohup`` and trailing ``&`` are stripped — systemd already daemonises.
    If *test_slice* is set, the scope is placed under that slice via ``--slice``.
    """
    cmd = command.strip()
    if cmd.startswith("nohup "):
        cmd = cmd[len("nohup "):]
    if cmd.endswith("&"):
        cmd = cmd.rstrip("&").rstrip()
    unit_name = _sanitize_unit(name)
    unit = f"{unit_name}.scope"
    base = ["systemd-run", "--user", "--scope", f"--unit={unit_name}"]
    if test_slice:
        base.append(f"--slice={test_slice}")
    args = _inject_env(base, env)
    args.extend(["sh", "-c", cmd])
    subprocess.Popen(args, env=env)
    return unit


def _cgroup_stop(unit: str) -> None:
    """Stop a systemd user unit (scope or service) — kills every process in its cgroup."""
    subprocess.run(
        ["systemctl", "--user", "stop", unit],
        check=False, capture_output=True,
    )


def _cgroup_kill(unit: str, sig: str = "SIGTERM") -> None:
    """Send a signal to every process in the unit's cgroup."""
    subprocess.run(
        ["systemctl", "--user", "kill", unit, f"--signal={sig}"],
        check=False, capture_output=True,
    )


def _cgroup_unit_active(unit: str) -> bool:
    """Return True if the systemd unit is still active."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        check=False, capture_output=True, text=True,
    )
    return result.stdout.strip() == "active"


def log(message: str) -> None:
    print(f"[automation] {message}", flush=True)


def infer_app(action: dict[str, Any]) -> str:
    text = " ".join(
        str(action.get(key, ""))
        for key in ("name", "class", "command", "shell_command", "title")
    ).lower()
    if "wps" in text or "wpsoffice" in text:
        return "WPS"
    if "linuxqq" in text or "qq" in text:
        return "QQ"
    if "nautilus" in text or "files" in text:
        return "FILES"
    if "bilibili" in text or "哔哩哔哩" in text:
        return "BILIBILI"
    if "firefox" in text:
        return "FIREFOX"
    return "UNKNOWN"


def default_label(action: dict[str, Any], app: str) -> str:
    action_type = str(action.get("type", "")).strip()
    if action.get("label"):
        return str(action["label"])
    if action_type == "launch" and app == "WPS":
        return "WPS_LAUNCH"
    if action_type == "shell" and app == "QQ":
        return "QQ_LAUNCH"
    if action_type == "shell" and app == "FILES":
        return "FILES_LAUNCH"
    if action_type == "switch" and app in {"WPS", "QQ", "FILES"}:
        return f"APP_SWITCH_{app}"
    if action_type == "focus" and app == "WPS":
        return "APP_FOCUS_WPS"
    if action_type == "close" and app == "WPS":
        return "WPS_CLOSE"
    if action_type == "close" and app == "QQ":
        return "QQ_CLOSE"
    if action_type == "close" and app == "FILES":
        return "FILES_CLOSE"
    if action_type == "close" and app == "BILIBILI":
        return "BILIBILI_CLOSE"
    if action_type in {"switch", "focus", "verify_foreground"} and app == "BILIBILI":
        return f"APP_{action_type.upper()}_BILIBILI"
    if action_type in {"key", "hotkey"}:
        return "APP_KEY"
    if action_type == "wait":
        return "WAIT"
    return f"ACTION_{action_type.upper() or 'UNKNOWN'}"


def action_command(action: dict[str, Any]) -> str:
    for key in ("command", "shell_command", "key", "text"):
        value = action.get(key)
        if value:
            return str(value)
    return ""


def action_window_match(action: dict[str, Any]) -> str:
    parts = []
    if action.get("class"):
        parts.append(f"class={action['class']}")
    if action.get("title"):
        parts.append(f"title={action['title']}")
    if action.get("name"):
        parts.append(f"name={action['name']}")
    return ";".join(parts)


def proc_meta_for_pid(pid: int) -> dict[str, str]:
    if pid <= 0:
        return {}
    status = read_proc_text(Path("/proc") / str(pid) / "status")
    tgid = ""
    for line in status.splitlines():
        if line.startswith("Tgid:"):
            tgid = line.split(":", 1)[1].strip()
            break
    cgroup_path = read_proc_text(Path("/proc") / str(pid) / "cgroup")
    return {"pid": str(pid), "tgid": tgid, "cgroup_path": cgroup_path.replace("\n", "|")}


def cgroup_unit_from_path(path: str) -> str:
    for part in reversed(path.replace("|", "/").strip("/").split("/")):
        if "." in part:
            return part
    return ""


def map_window_app(title: str, wm_class: str, pid_comm: str, cgroup_path: str = "") -> str:
    text = " ".join([title, wm_class, pid_comm, cgroup_path]).lower()
    if "wps" in text or "wpsoffice" in text or "kingsoft" in text:
        return "WPS"
    if "linuxqq" in text or "tencent" in text or "腾讯" in text or "qq" in text:
        return "QQ"
    if (
        "org.gnome.nautilus" in text
        or "nautilus" in text
        or "files" in text
        or "文件" in text
        or "home" in text
        or "主文件夹" in text
    ):
        return "FILES"
    if "bilibili" in text or "哔哩哔哩" in text:
        return "BILIBILI"
    return "UNKNOWN"


def read_window_info(window_id: str) -> WindowInfo:
    info = WindowInfo(window_id=window_id)
    try:
        title = subprocess.run(
            ["xdotool", "getwindowname", window_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
        info.title = title
    except OSError:
        pass
    props = subprocess.run(
        ["xprop", "-id", window_id, "WM_CLASS", "_NET_WM_NAME", "WM_NAME", "_NET_WM_PID"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for line in props.stdout.splitlines():
        if line.startswith("WM_CLASS") and "=" in line:
            info.wm_class = "|".join(part.strip().strip('"') for part in line.split("=", 1)[1].split(","))
        elif (line.startswith("_NET_WM_NAME") or line.startswith("WM_NAME")) and not info.title and "=" in line:
            info.title = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("_NET_WM_PID") and "=" in line:
            try:
                info.pid = int(line.split("=", 1)[1].strip())
            except ValueError:
                info.pid = 0
    if not info.pid:
        try:
            pid_text = subprocess.run(
                ["xdotool", "getwindowpid", window_id],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            ).stdout.strip()
            info.pid = int(pid_text) if pid_text else 0
        except (OSError, ValueError):
            info.pid = 0
    if info.pid:
        info.pid_comm = read_proc_text(Path("/proc") / str(info.pid) / "comm")
        info.cgroup_path = read_proc_text(Path("/proc") / str(info.pid) / "cgroup")
        info.cgroup_unit = cgroup_unit_from_path(info.cgroup_path)
    try:
        geo = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", window_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        ).stdout
        for line in geo.splitlines():
            if line.startswith("WIDTH="):
                info.width = int(line.split("=", 1)[1])
            elif line.startswith("HEIGHT="):
                info.height = int(line.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    info.mapped_app = map_window_app(info.title, info.wm_class, info.pid_comm, info.cgroup_path)
    return info


def format_window_info(info: WindowInfo) -> str:
    return (
        f"id={info.window_id} title={info.title!r} class={info.wm_class!r} "
        f"pid={info.pid} comm={info.pid_comm!r} unit={info.cgroup_unit!r} "
        f"mapped={info.mapped_app} size={info.width}x{info.height}"
    )


def list_window_candidates(action: dict[str, Any], app: str = "") -> list[WindowInfo]:
    if not shutil.which("xdotool"):
        raise AutomationError("需要安装 xdotool")
    title = get_str(action, "title")
    window_class = get_str(action, "class")
    name = get_str(action, "name")
    queries: list[list[str]] = []
    if window_class:
        queries.append(["xdotool", "search", "--onlyvisible", "--class", window_class])
    if title:
        queries.append(["xdotool", "search", "--onlyvisible", "--name", title])
    if name:
        queries.append(["xdotool", "search", "--onlyvisible", "--name", name])
    if app == "QQ":
        queries.extend([
            ["xdotool", "search", "--onlyvisible", "--class", "qq|QQ|linuxqq"],
            ["xdotool", "search", "--onlyvisible", "--name", "QQ"],
        ])
    seen: set[str] = set()
    ids: list[str] = []
    for query in queries:
        result = subprocess.run(query, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0:
            for window_id in result.stdout.splitlines():
                window_id = window_id.strip()
                if window_id and window_id not in seen:
                    seen.add(window_id)
                    ids.append(window_id)
    return [read_window_info(window_id) for window_id in ids]


def best_window_candidate(action: dict[str, Any], app: str) -> WindowInfo | None:
    candidates = list_window_candidates(action, app)
    if not candidates:
        return None
    indexed = list(enumerate(candidates))
    indexed.sort(
        key=lambda item: (
            item[1].mapped_app == app,
            bool(item[1].title),
            item[1].width * item[1].height,
            item[1].cgroup_unit == f"automation-{app.lower()}.scope",
            item[0],
        ),
        reverse=True,
    )
    return indexed[0][1]


def get_foreground_window_info() -> WindowInfo:
    active_id = ""
    result = subprocess.run(
        ["xdotool", "getactivewindow"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        active_id = result.stdout.strip()
    active = read_window_info(active_id) if active_id else WindowInfo("")
    stacking = subprocess.run(
        ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if "#" in stacking.stdout:
        ids = [item.strip() for item in stacking.stdout.split("#", 1)[1].split(",") if item.strip()]
        for window_id in reversed(ids):
            info = read_window_info(window_id)
            if info.mapped_app != "UNKNOWN":
                return info
    return active


def quiet_window_trace(action: dict[str, Any]) -> dict[str, str]:
    display = os.environ.get("DISPLAY")
    if not display or shutil.which("xdotool") is None:
        return {}
    title = get_str(action, "title")
    window_class = get_str(action, "class")
    name = get_str(action, "name")
    queries: list[list[str]] = []
    if window_class:
        queries.append(["xdotool", "search", "--onlyvisible", "--class", window_class])
    if title:
        queries.append(["xdotool", "search", "--onlyvisible", "--name", title])
    if name:
        queries.append(["xdotool", "search", "--onlyvisible", "--name", name])
    window_id = ""
    for query in queries:
        result = subprocess.run(query, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0 and result.stdout.strip():
            window_id = result.stdout.strip().splitlines()[-1]
            break
    if not window_id:
        return {}
    out = {"window_id": window_id}
    props = subprocess.run(
        ["xprop", "-id", window_id, "_NET_WM_PID", "_NET_WM_NAME", "WM_NAME"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout
    pid = 0
    for line in props.splitlines():
        if line.startswith("_NET_WM_PID"):
            try:
                pid = int(line.split("=", 1)[1].strip())
            except ValueError:
                pid = 0
        elif line.startswith("_NET_WM_NAME") or line.startswith("WM_NAME"):
            if "=" in line and not out.get("window_title"):
                out["window_title"] = line.split("=", 1)[1].strip().strip('"')
    out.update(proc_meta_for_pid(pid))
    return out


def trace_marker(
    ctx: Context,
    *,
    event_type: str,
    status: str,
    step_id: int = 0,
    action: dict[str, Any] | None = None,
    op_type: str = "",
    error: str = "",
) -> None:
    if ctx.trace is None:
        return
    action = action or {}
    app = infer_app(action)
    row: dict[str, Any] = {
        "step_id": step_id,
        "phase": "marker",
        "action": get_str(action, "type"),
        "op_type": op_type or get_str(action, "type"),
        "event_type": event_type,
        "app": app,
        "app_key": app,
        "label": default_label(action, app),
        "status": status,
        "validation_mode": str(ctx.validation_mode).lower(),
        "optional": "true" if bool(action.get("optional")) else "false",
        "command": action_command(action),
        "window_match": action_window_match(action),
        "error": error,
    }
    ctx.trace.write(row)


def trace_action(ctx: Context, step_id: int, phase: str, status: str, action: dict[str, Any], error: str = "") -> None:
    if ctx.trace is None:
        return
    app = infer_app(action)
    event_type = "OP_START" if phase == "start" else "OP_DONE"
    row: dict[str, Any] = {
        "step_id": step_id,
        "phase": phase,
        "action": get_str(action, "type"),
        "op_type": get_str(action, "type"),
        "event_type": event_type,
        "app": app,
        "app_key": app,
        "label": default_label(action, app),
        "status": status,
        "validation_mode": str(ctx.validation_mode).lower(),
        "optional": "true" if bool(action.get("optional")) else "false",
        "command": action_command(action),
        "window_match": action_window_match(action),
        "error": error,
    }
    if phase == "end":
        row.update(quiet_window_trace(action))
        name = get_str(action, "name")
        tracked = ctx.processes.get(name) if name else None
        if isinstance(tracked, str):
            row.setdefault("cgroup_path", tracked)
    ctx.trace.write(row)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AutomationError(f"需要安装 {name}。Ubuntu/Debian 可执行：sudo apt install {name}")
    return path


def detect_display() -> str:
    if os.environ.get("DISPLAY"):
        return str(os.environ["DISPLAY"])
    x11_dir = Path("/tmp/.X11-unix")
    if not x11_dir.is_dir():
        return ""
    for item in sorted(x11_dir.glob("X*")):
        suffix = item.name[1:]
        if suffix.isdigit():
            return f":{suffix}"
    return ""


def detect_xauthority(display: str) -> str:
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    mutter_auths = sorted(runtime_dir.glob(".mutter-Xwaylandauth.*"))
    if mutter_auths:
        return str(mutter_auths[-1])

    if display:
        try:
            ps_output = subprocess.run(
                ["ps", "-eo", "args"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            ).stdout
        except OSError:
            ps_output = ""
        for line in ps_output.splitlines():
            if "Xwayland" not in line or display not in line:
                continue
            parts = shlex.split(line)
            for index, part in enumerate(parts):
                if part == "-auth" and index + 1 < len(parts):
                    return parts[index + 1]

    candidate = Path.home() / ".Xauthority"
    if candidate.exists():
        return str(candidate)
    return ""


def configure_display(display: str = "", xauthority: str = "") -> None:
    chosen_display = display or detect_display()
    if chosen_display and not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = chosen_display
        log(f"DISPLAY={chosen_display}")
    elif display:
        os.environ["DISPLAY"] = display
        log(f"DISPLAY={display}")

    chosen_xauthority = xauthority or os.environ.get("XAUTHORITY", "") or detect_xauthority(chosen_display)
    if chosen_xauthority:
        os.environ["XAUTHORITY"] = chosen_xauthority
        log(f"XAUTHORITY={chosen_xauthority}")


def require_xdotool() -> None:
    require_tool("xdotool")
    if not os.environ.get("DISPLAY"):
        raise AutomationError(
            "当前终端没有 DISPLAY，xdotool 无法连接图形会话。"
            "请在桌面终端运行，或传入 --display :0；如果是 Wayland 原生会话，xdotool 可能无法控制原生窗口。"
        )


def run(args: list[str], ctx: Context, *, check: bool = True) -> subprocess.CompletedProcess[str] | None:
    rendered = " ".join(shlex.quote(part) for part in args)
    if ctx.dry_run:
        log(f"dry-run: {rendered}")
        return None
    log(rendered)
    return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_shell(command: str, ctx: Context, *, check: bool = True) -> subprocess.CompletedProcess[str] | None:
    if ctx.dry_run:
        log(f"dry-run: {command}")
        return None
    log(command)
    return subprocess.run(command, shell=True, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def get_str(action: dict[str, Any], key: str, default: str = "") -> str:
    value = action.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise AutomationError(f"{key} 必须是字符串")
    return value


def get_float(action: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(action.get(key, default))
    except (TypeError, ValueError) as exc:
        raise AutomationError(f"{key} 必须是数字") from exc


def get_int(action: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(action.get(key, default))
    except (TypeError, ValueError) as exc:
        raise AutomationError(f"{key} 必须是整数") from exc


def get_str_list(action: dict[str, Any], key: str) -> list[str]:
    value = action.get(key, [])
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise AutomationError(f"{key} 必须是字符串或字符串数组")


def _expand_actions(actions: list[Any], *, prefix: str = "") -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise AutomationError(f"{prefix}第 {index} 个 action 必须是对象")
        action_type = str(action.get("type", "")).strip()
        if action_type == "repeat":
            times = get_int(action, "times", get_int(action, "count", 1))
            nested = action.get("actions", [])
            if times < 1:
                continue
            if not isinstance(nested, list):
                raise AutomationError(f"{prefix}repeat.actions 必须是 action 数组")
            for repeat_index in range(1, times + 1):
                for nested_action in _expand_actions(nested, prefix=f"{prefix}repeat {index}: "):
                    copied = dict(nested_action)
                    copied.setdefault("_repeat_index", repeat_index)
                    copied.setdefault("_repeat_total", times)
                    expanded.append(copied)
            continue
        expanded.append(dict(action))
    return expanded


def load_scenario(path: Path) -> Scenario:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        raw_actions = data
        keep_alive_after_s = 0.0
        validation_mode = False
    elif isinstance(data, dict) and isinstance(data.get("actions"), list):
        raw_actions = data["actions"]
        try:
            keep_alive_after_s = float(data.get("keep_alive_after_s", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise AutomationError("keep_alive_after_s 必须是数字") from exc
        validation_mode = bool(data.get("validation_mode", False))
    else:
        raise AutomationError("场景文件必须是 action 数组，或包含 actions 数组的对象")
    actions = _expand_actions(raw_actions)
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise AutomationError(f"第 {index} 个 action 必须是对象")
    return Scenario(
        actions=actions,
        keep_alive_after_s=keep_alive_after_s,
        validation_mode=validation_mode,
    )


def keep_alive(seconds: float, ctx: Context) -> None:
    if seconds <= 0:
        return
    trace_marker(ctx, event_type="KEEP_ALIVE_START", status="running", op_type="keep_alive")
    log(f"keep_alive_after_s {seconds:g}s")
    if not ctx.dry_run:
        time.sleep(seconds)
    trace_marker(ctx, event_type="KEEP_ALIVE_DONE", status="success", op_type="keep_alive")


def launch(action: dict[str, Any], ctx: Context) -> None:
    command = get_str(action, "command")
    name = get_str(action, "name") or command
    if not command:
        raise AutomationError("launch 需要 command")
    if ctx.dry_run:
        log(f"dry-run: launch {command}")
        return
    env = os.environ.copy()
    if _cgroup_available():
        unit_name = _cgroup_launch(command, name, env, test_slice=ctx.test_slice)
        log(f"launch {command}  (cgroup: {unit_name})")
        ctx.processes[name] = unit_name
    else:
        log(f"launch {command}")
        proc = subprocess.Popen(shlex.split(command), env=env)
        ctx.processes[name] = proc


def wait(action: dict[str, Any], ctx: Context) -> None:
    seconds = get_float(action, "seconds", 1.0)
    log(f"wait {seconds:g}s")
    if not ctx.dry_run:
        time.sleep(seconds)


def key(action: dict[str, Any], ctx: Context) -> None:
    value = get_str(action, "key")
    if not value:
        raise AutomationError("key 需要 key，例如 ctrl+o 或 Escape")
    if not ctx.dry_run:
        require_xdotool()
    run(["xdotool", "key", value], ctx)


def type_text(action: dict[str, Any], ctx: Context) -> None:
    text = get_str(action, "text")
    delay = str(get_int(action, "delay_ms", 20))
    if not ctx.dry_run:
        require_xdotool()
    run(["xdotool", "type", "--delay", delay, text], ctx)


def click(action: dict[str, Any], ctx: Context) -> None:
    x = str(get_int(action, "x"))
    y = str(get_int(action, "y"))
    button = str(get_int(action, "button", 1))
    if not ctx.dry_run:
        require_xdotool()
    run(["xdotool", "mousemove", x, y, "click", button], ctx)


def click_window(action: dict[str, Any], ctx: Context) -> None:
    app = infer_app(action)
    button = str(get_int(action, "button", 1))
    if ctx.dry_run:
        log(f"dry-run: click_window {app}")
        return
    require_xdotool()
    candidate = best_window_candidate(action, app)
    if candidate is None:
        candidates = list_window_candidates(action, app)
        raise AutomationError(f"click_window {app}: no candidate; candidates={[format_window_info(item) for item in candidates]}")
    x = get_int(action, "x", -1)
    y = get_int(action, "y", -1)
    if x < 0:
        x = int(candidate.width * get_float(action, "x_ratio", 0.5))
    if y < 0:
        y = int(candidate.height * get_float(action, "y_ratio", 0.82))
    log(f"click_window {app}: {format_window_info(candidate)} at {x},{y}")
    run(["xdotool", "mousemove", "--window", candidate.window_id, str(x), str(y), "click", button], ctx)


def drag(action: dict[str, Any], ctx: Context) -> None:
    x1 = str(get_int(action, "x1"))
    y1 = str(get_int(action, "y1"))
    x2 = str(get_int(action, "x2"))
    y2 = str(get_int(action, "y2"))
    delay = str(get_int(action, "duration_ms", 500))
    if not ctx.dry_run:
        require_xdotool()
    run(["xdotool", "mousemove", x1, y1, "mousedown", "1", "mousemove", "--sync", x2, y2, "sleep", str(int(delay) / 1000), "mouseup", "1"], ctx)


def find_window(action: dict[str, Any], ctx: Context) -> str:
    if not ctx.dry_run:
        require_xdotool()
    title = get_str(action, "title")
    window_class = get_str(action, "class")
    name = get_str(action, "name")
    search_args = ["xdotool", "search", "--onlyvisible"]
    if window_class:
        search_args.extend(["--class", window_class])
    elif title:
        search_args.extend(["--name", title])
    elif name:
        search_args.extend(["--name", name])
    else:
        raise AutomationError("窗口操作需要 title、class 或 name")

    result = run(search_args, ctx, check=False)
    if ctx.dry_run:
        return "DRY_RUN_WINDOW"
    if (result is None or result.returncode != 0 or not result.stdout.strip()) and window_class and title:
        result = run(["xdotool", "search", "--onlyvisible", "--name", title], ctx, check=False)
    if result is None or result.returncode != 0 or not result.stdout.strip():
        raise AutomationError(f"找不到窗口：{title or window_class or name}")
    return result.stdout.strip().splitlines()[-1]


def focus(action: dict[str, Any], ctx: Context) -> None:
    window_id = find_window(action, ctx)
    if window_id == "DRY_RUN_WINDOW":
        log("dry-run: focus window")
        return
    run(["xdotool", "windowactivate", "--sync", window_id], ctx)


def robust_switch_to_app(action: dict[str, Any], ctx: Context, app: str) -> None:
    if ctx.dry_run:
        log(f"dry-run: robust switch {app}")
        return
    require_xdotool()
    errors: list[str] = []
    for attempt in range(1, 4):
        candidates = list_window_candidates(action, app)
        if not candidates:
            errors.append(f"attempt {attempt}: no candidates")
            time.sleep(0.5)
            continue
        candidate = best_window_candidate(action, app)
        if candidate is None:
            errors.append(f"attempt {attempt}: no best candidate")
            time.sleep(0.5)
            continue
        log(f"switch {app} candidate: {format_window_info(candidate)}")
        subprocess.run(["xdotool", "windowactivate", "--sync", candidate.window_id], check=False)
        subprocess.run(["xdotool", "windowraise", candidate.window_id], check=False)
        time.sleep(0.2)
        active = get_foreground_window_info()
        if active.mapped_app == app:
            log(f"switch {app} verified: {format_window_info(active)}")
            return
        errors.append(
            f"attempt {attempt}: active={format_window_info(active)} "
            f"candidates={[format_window_info(item) for item in candidates]}"
        )
        time.sleep(0.5)
    raise AutomationError("; ".join(errors))


def switch(action: dict[str, Any], ctx: Context) -> None:
    app = infer_app(action)
    if app == "QQ":
        try:
            robust_switch_to_app(action, ctx, app)
            return
        except AutomationError:
            command = get_str(action, "command")
            if command:
                run_shell(command, ctx, check=False)
                time.sleep(1)
                robust_switch_to_app(action, ctx, app)
                return
            raise
    try:
        focus(action, ctx)
        return
    except AutomationError:
        shell_command = get_str(action, "shell_command")
        if shell_command:
            run_shell(shell_command, ctx, check=False)
            return
        command = get_str(action, "command")
        if not command:
            raise
        launch(action, ctx)


def wait_window(action: dict[str, Any], ctx: Context) -> None:
    app = infer_app(action)
    timeout = get_float(action, "timeout", 15.0)
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() <= deadline:
        candidates = list_window_candidates(action, app)
        matched = [item for item in candidates if item.mapped_app == app]
        if matched:
            best = best_window_candidate(action, app) or matched[-1]
            log(f"wait_window {app} found: {format_window_info(best)}")
            return
        last_error = f"candidates={[format_window_info(item) for item in candidates]}"
        time.sleep(0.5)
    raise AutomationError(f"wait_window {app} timeout after {timeout:g}s; {last_error}")


def verify_foreground(action: dict[str, Any], ctx: Context) -> None:
    app = infer_app(action)
    active = get_foreground_window_info()
    if active.mapped_app != app:
        raise AutomationError(f"foreground verify failed: expected={app} active={format_window_info(active)}")
    log(f"verify_foreground {app}: {format_window_info(active)}")


def read_proc_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def read_proc_link(path: Path) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return ""


def find_matching_pids(process_names: list[str], path_contains: list[str], cmdline_contains: list[str] | None = None) -> list[int]:
    names = set(process_names)
    cmdline_tokens = cmdline_contains or []
    current_pid = os.getpid()
    matches: list[int] = []
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        pid = int(item.name)
        if pid == current_pid:
            continue
        comm = read_proc_text(item / "comm")
        exe = read_proc_link(item / "exe")
        cmdline = read_proc_text(item / "cmdline").replace("\x00", " ")
        if (
            comm in names
            or any(token and token in exe for token in path_contains)
            or any(token and token in cmdline for token in cmdline_tokens)
        ):
            matches.append(pid)
    return sorted(matches)


def signal_from_name(name: str) -> signal.Signals:
    normalized = name.upper().removeprefix("SIG")
    try:
        return signal.Signals[f"SIG{normalized}"]
    except KeyError as exc:
        raise AutomationError(f"不支持的 signal: {name}") from exc


def kill_pids(pids: list[int], sig: signal.Signals, ctx: Context) -> None:
    for pid in pids:
        if ctx.dry_run:
            log(f"dry-run: kill -{sig.name} {pid}")
            continue
        try:
            log(f"kill -{sig.name} {pid}")
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            log(f"skip pid {pid}: {exc}")


def close(action: dict[str, Any], ctx: Context) -> None:
    command = get_str(action, "command")
    if command:
        run_shell(command, ctx, check=False)
        return

    title = get_str(action, "title")
    window_class = get_str(action, "class")
    name = get_str(action, "name")
    process_names = get_str_list(action, "process_names")
    path_contains = get_str_list(action, "path_contains")
    cmdline_contains = get_str_list(action, "cmdline_contains")
    if title or window_class:
        if not ctx.dry_run:
            require_xdotool()
        try:
            window_id = find_window(action, ctx)
            if window_id == "DRY_RUN_WINDOW":
                log("dry-run: close window")
            else:
                run(["xdotool", "windowclose", window_id], ctx, check=False)
        except AutomationError as exc:
            log(f"window close skipped: {exc}")
        wait_seconds = get_float(action, "wait_after_window_close", 2.0)
        if wait_seconds > 0:
            wait({"seconds": wait_seconds}, ctx)
        if not process_names and not path_contains and not cmdline_contains and not name:
            return

    # --- cgroup / tracked-process cleanup ---
    cgroup_cleaned_up = False
    if name and name in ctx.processes:
        tracked = ctx.processes[name]
        if isinstance(tracked, str) and tracked.startswith("automation-"):
            # systemd unit — kill entire cgroup in one shot
            unit_name = tracked
            log(f"stop cgroup unit: {unit_name}")
            if not ctx.dry_run:
                _cgroup_stop(unit_name)
                if _cgroup_unit_active(unit_name):
                    time.sleep(1.0)
                    _cgroup_kill(unit_name, "SIGKILL")
                    _cgroup_stop(unit_name)
            del ctx.processes[name]
            cgroup_cleaned_up = True
        else:
            # old-style Popen tracking
            proc = tracked
            if proc.poll() is None:
                if ctx.dry_run:
                    log(f"dry-run: terminate {name}")
                else:
                    log(f"terminate {name}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            del ctx.processes[name]

    if cgroup_cleaned_up and not process_names and not path_contains and not cmdline_contains:
        return  # cgroup already killed everything, no further cleanup needed

    if process_names or path_contains or cmdline_contains:
        sig = signal_from_name(get_str(action, "signal", "TERM"))
        pids = find_matching_pids(process_names, path_contains, cmdline_contains)
        if pids:
            log(f"matched pids: {','.join(str(pid) for pid in pids)}")
            kill_pids(pids, sig, ctx)
        else:
            log("matched pids: none")
        force_after = get_float(action, "force_after_seconds", 0.0)
        if force_after > 0:
            wait({"seconds": force_after}, ctx)
            remaining = find_matching_pids(process_names, path_contains, cmdline_contains)
            if remaining:
                log(f"force kill pids: {','.join(str(pid) for pid in remaining)}")
                kill_pids(remaining, signal.SIGKILL, ctx)
        return

    if name:
        run(["pkill", "-x", name], ctx, check=False)
        return

    raise AutomationError("close 需要 name、title、class、process_names、path_contains、cmdline_contains 或 command")


ACTION_HANDLERS = {
    "launch": launch,
    "wait": wait,
    "key": key,
    "hotkey": key,
    "type": type_text,
    "text": type_text,
    "click": click,
    "tap": click,
    "click_window": click_window,
    "drag": drag,
    "swipe": drag,
    "focus": focus,
    "switch": switch,
    "wait_window": wait_window,
    "verify_foreground": verify_foreground,
    "close": close,
    "shell": lambda action, ctx: _handle_shell(action, ctx),
}


def _handle_shell(action: dict[str, Any], ctx: Context) -> None:
    """Execute a shell command, optionally tracking it in a cgroup."""
    command = get_str(action, "command")
    name = get_str(action, "name")
    if not command:
        raise AutomationError("shell 需要 command")
    if ctx.dry_run:
        log(f"dry-run: {command}")
        return
    if name and _cgroup_available():
        unit_name = _cgroup_launch_shell(command, name, os.environ.copy(), test_slice=ctx.test_slice)
        log(f"shell (cgroup: {unit_name}): {command}")
        ctx.processes[name] = unit_name
    else:
        run_shell(command, ctx)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Linux 应用自动化：打开、操作、关闭、切换应用。")
    parser.add_argument("scenario", type=Path, help="JSON 场景文件")
    parser.add_argument("--dry-run", action="store_true", help="只打印动作，不实际执行")
    parser.add_argument("--display", default="", help="指定 X11 DISPLAY，例如 :0。默认会从环境或 /tmp/.X11-unix 自动探测")
    parser.add_argument("--xauthority", default="", help="指定 XAUTHORITY，例如 /home/lzx/.Xauthority")
    parser.add_argument("--trace-output", default="", help="写出 automation_trace.csv")
    parser.add_argument("--session-id", default="", help="实验 session id")
    parser.add_argument("--scenario-id", default="", help="场景 id，默认使用 scenario 文件名")
    parser.add_argument("--test-slice", default="huawei-test.slice", help="systemd --slice 参数，所有自动化 scope 挂到此 slice 下")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        configure_display(args.display, args.xauthority)
        scenario = load_scenario(args.scenario)
        actions = scenario.actions
        scenario_id = args.scenario_id or args.scenario.stem
        session_id = args.session_id or dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        trace = TraceWriter(args.trace_output, session_id, scenario_id) if args.trace_output else None
        ctx = Context(
            dry_run=args.dry_run,
            processes={},
            trace=trace,
            session_id=session_id,
            scenario_id=scenario_id,
            test_slice=args.test_slice,
            validation_mode=scenario.validation_mode,
        )
        log(f"scenario={args.scenario}")
        try:
            trace_marker(ctx, event_type="SCENARIO_START", status="running", op_type="scenario")
            for index, action in enumerate(actions, start=1):
                action_type = get_str(action, "type")
                handler = ACTION_HANDLERS.get(action_type)
                if handler is None:
                    raise AutomationError(f"不支持的 action type: {action_type}")
                log(f"action #{index}: {action_type}")
                trace_action(ctx, index, "start", "running", action)
                try:
                    handler(action, ctx)
                    trace_action(ctx, index, "end", "success", action)
                    is_named_app_action = bool(get_str(action, "name")) or action_type == "launch"
                    if is_named_app_action and action_type in {"launch", "shell"} and infer_app(action) != "UNKNOWN":
                        trace_marker(
                            ctx,
                            event_type="APP_LAUNCH",
                            status="success",
                            step_id=index,
                            action=action,
                            op_type=action_type,
                        )
                    elif is_named_app_action and action_type in {"focus", "switch", "verify_foreground"} and infer_app(action) != "UNKNOWN":
                        trace_marker(
                            ctx,
                            event_type="APP_FOCUS",
                            status="success",
                            step_id=index,
                            action=action,
                            op_type=action_type,
                        )
                except (AutomationError, subprocess.CalledProcessError) as exc:
                    if isinstance(exc, subprocess.CalledProcessError):
                        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
                    else:
                        message = str(exc)
                    trace_action(ctx, index, "end", "failed", action, message)
                    if action.get("optional"):
                        log(f"optional action skipped: {message}")
                        continue
                    raise
            keep_alive(scenario.keep_alive_after_s, ctx)
            trace_marker(ctx, event_type="SCENARIO_DONE", status="success", op_type="scenario")
            log("done")
            return 0
        finally:
            if ctx.trace is not None:
                ctx.trace.close()
    except (AutomationError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            if "Can't open display" in message:
                message += "\n提示：尝试在桌面终端运行，或执行 python3 app_automation.py <scenario> --display :0"
        else:
            message = str(exc)
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
