"""User-space writer for the MGLRU workload Markov debugfs interface."""

from __future__ import annotations

import csv
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Iterable


MGLRU_MARKOV_WRITE_FIELDS = [
    "session_id",
    "timestamp",
    "event_type",
    "command",
    "status",
    "error",
    "foreground_app_key",
    "foreground_app_id",
    "foreground_cgroup_id",
    "predicted_app_ids",
    "predicted_confidences",
    "debugfs_path",
]

RANK_BASED_CONFIDENCE = [8000, 5000, 3000, 1000]


def resolve_scope_cgroup_id(slice_name: str, scope_name: str) -> int | None:
    """Resolve a user systemd scope path and return its cgroup inode."""
    if not slice_name or not scope_name:
        return None
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", slice_name, "-p", "ControlGroup", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: failed to resolve cgroup control group for {slice_name}: {exc}", file=sys.stderr)
        return None
    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"warning: systemctl failed for {slice_name}: {stderr}", file=sys.stderr)
        return None
    control_group = result.stdout.strip()
    if not control_group:
        print(f"warning: empty ControlGroup for {slice_name}", file=sys.stderr)
        return None
    scope_path = Path("/sys/fs/cgroup") / control_group.lstrip("/") / scope_name
    try:
        return int(scope_path.stat().st_ino)
    except OSError as exc:
        print(f"warning: cgroup scope missing for {scope_name}: {scope_path}: {exc}", file=sys.stderr)
        return None


def fixed_point_confidence(value: object, rank: int) -> int:
    """Convert probability-like values to 0..10000, with rank fallback."""
    fallback = RANK_BASED_CONFIDENCE[rank] if rank < len(RANK_BASED_CONFIDENCE) else 1000
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return fallback
    if prob <= 0:
        return fallback
    if prob <= 1:
        return max(0, min(10000, int(round(prob * 10000))))
    if prob <= 10000:
        return max(0, min(10000, int(round(prob))))
    return fallback


class MGLRUMarkovDebugfsWriter:
    def __init__(
        self,
        *,
        enabled: bool,
        strict: bool,
        debugfs_path: str | Path,
        session_id: str,
        model_dir: Path,
        review_dir: Path,
        ttl_ms: int,
    ) -> None:
        self.enabled = bool(enabled)
        self.strict = bool(strict)
        self.debugfs_path = Path(debugfs_path)
        self.session_id = session_id
        self.ttl_ms = int(ttl_ms)
        self.csv_path = model_dir / "mglru_markov_debugfs_writes.csv"
        self.summary_path = review_dir / "mglru_markov_debugfs_summary.md"
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.csv_path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=MGLRU_MARKOV_WRITE_FIELDS)
        self._writer.writeheader()
        self._file.flush()

        self.debugfs_exists = self._debugfs_exists()
        self.total_write_attempts = 0
        self.current_app_write_ok = 0
        self.predicted_apps_write_ok = 0
        self.debugfs_missing_count = 0
        self.write_error_count = 0
        self.skipped_prediction_count = 0
        self.disabled_count = 0
        self.dry_run_count = 0
        self.confidence_source = "rank_based"

        if self.enabled and not self.debugfs_exists:
            msg = f"mglru markov debugfs not found: {self.debugfs_path}"
            print(f"warning: {msg}", file=sys.stderr)
            self.debugfs_missing_count += 1

    def close(self) -> None:
        self._file.flush()
        self._file.close()
        self.write_summary()

    def write_current_app(self, app_key: str, app_id: int, cgroup_id: int | None, ttl_ms: int | None = None) -> None:
        ttl = self.ttl_ms if ttl_ms is None else int(ttl_ms)
        if not cgroup_id:
            self._record(
                event_type="current_app",
                command="",
                status="dry_run",
                error="missing_cgroup_id",
                foreground_app_key=app_key,
                foreground_app_id=app_id,
                foreground_cgroup_id="",
            )
            return
        command = f"app current {int(app_id)} {int(cgroup_id)} {ttl}"
        status, error = self._write_command(command)
        if status == "ok":
            self.current_app_write_ok += 1
        self._record(
            event_type="current_app",
            command=command,
            status=status,
            error=error,
            foreground_app_key=app_key,
            foreground_app_id=app_id,
            foreground_cgroup_id=cgroup_id,
        )

    def write_predicted_apps(self, predictions: Iterable[tuple[int, int]], ttl_ms: int | None = None) -> None:
        ttl = self.ttl_ms if ttl_ms is None else int(ttl_ms)
        pairs = [(int(app_id), int(conf)) for app_id, conf in predictions if int(app_id) > 0]
        if not pairs:
            self.skipped_prediction_count += 1
            self._record(
                event_type="predicted_apps",
                command="",
                status="dry_run",
                error="no_valid_predictions",
            )
            return
        args = " ".join(f"{app_id} {max(0, min(10000, conf))}" for app_id, conf in pairs)
        command = f"app predict {ttl} {args}"
        status, error = self._write_command(command)
        if status == "ok":
            self.predicted_apps_write_ok += 1
        self._record(
            event_type="predicted_apps",
            command=command,
            status=status,
            error=error,
            predicted_app_ids="|".join(str(app_id) for app_id, _ in pairs),
            predicted_confidences="|".join(str(conf) for _, conf in pairs),
        )

    def skip_prediction(self, reason: str) -> None:
        self.skipped_prediction_count += 1
        self._record(
            event_type="predicted_apps",
            command="",
            status="dry_run",
            error=reason,
        )

    def _write_command(self, command: str) -> tuple[str, str]:
        self.total_write_attempts += 1
        if not self.enabled:
            self.disabled_count += 1
            return "disabled", ""
        if not self._debugfs_exists():
            self.debugfs_exists = False
            self.debugfs_missing_count += 1
            return "debugfs_missing", f"debugfs path does not exist: {self.debugfs_path}"
        self.debugfs_exists = True
        try:
            self.debugfs_path.write_text(command + "\n", encoding="utf-8")
        except OSError as exc:
            self.write_error_count += 1
            return "write_error", str(exc)
        return "ok", ""

    def _record(
        self,
        *,
        event_type: str,
        command: str,
        status: str,
        error: str,
        foreground_app_key: str = "",
        foreground_app_id: int | str = "",
        foreground_cgroup_id: int | str = "",
        predicted_app_ids: str = "",
        predicted_confidences: str = "",
    ) -> None:
        if status == "dry_run":
            self.dry_run_count += 1
        self._writer.writerow(
            {
                "session_id": self.session_id,
                "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": event_type,
                "command": command,
                "status": status,
                "error": error,
                "foreground_app_key": foreground_app_key,
                "foreground_app_id": foreground_app_id,
                "foreground_cgroup_id": foreground_cgroup_id,
                "predicted_app_ids": predicted_app_ids,
                "predicted_confidences": predicted_confidences,
                "debugfs_path": str(self.debugfs_path),
            }
        )
        self._file.flush()

    def final_result(self) -> str:
        if not self.enabled:
            return "PASS"
        if self.strict:
            if self._debugfs_exists() and self.current_app_write_ok > 0 and self.predicted_apps_write_ok > 0:
                return "PASS"
            return "FAIL"
        if self.write_error_count:
            return "PASS_WITH_WARNINGS"
        return "PASS_WITH_WARNINGS" if self.debugfs_missing_count else "PASS"

    def write_summary(self) -> None:
        self.debugfs_exists = self._debugfs_exists()
        lines = [
            "# MGLRU Markov debugfs summary",
            "",
            f"- enabled: {str(self.enabled).lower()}",
            f"- debugfs_path: `{self.debugfs_path}`",
            f"- debugfs_exists: {str(self.debugfs_exists).lower()}",
            f"- strict: {str(self.strict).lower()}",
            f"- total_write_attempts: {self.total_write_attempts}",
            f"- current_app_write_ok: {self.current_app_write_ok}",
            f"- predicted_apps_write_ok: {self.predicted_apps_write_ok}",
            f"- debugfs_missing_count: {self.debugfs_missing_count}",
            f"- write_error_count: {self.write_error_count}",
            f"- skipped_prediction_count: {self.skipped_prediction_count}",
            f"- confidence_source: {self.confidence_source}",
            f"- csv_path: `{self.csv_path}`",
            f"- final_result: {self.final_result()}",
        ]
        self.summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _debugfs_exists(self) -> bool:
        try:
            return self.debugfs_path.exists()
        except OSError as exc:
            print(f"warning: cannot access MGLRU Markov debugfs path {self.debugfs_path}: {exc}", file=sys.stderr)
            return False
