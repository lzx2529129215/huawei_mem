#!/usr/bin/env python3
"""Runtime Monitor v0: local PC state collector for dataset generation.

Output directory (per session):
  outputs/runtime_monitor/<session_id>/
  ├── model/     — machine-training data (9 CSVs)
  └── review/    — human-inspection data (7 files)

No prefetch, eviction, swap, or kernel policy action is performed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MONITOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MONITOR_DIR.parent
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from collectors.file_events import FileEventCollector
from collectors.foreground import ForegroundCollector
from collectors.memory import read_meminfo, read_vmstat
from collectors.process import ProcessCollector
from core.app_feature_builder import AppFeatureBuilder
from core.app_mapper import AppMapper, load_config
from core.app_registry import AppRegistry
from core.feature_builder import FeatureBuilder
from core.lifecycle import LifecycleEventBuilder
from core.mglru_markov_debugfs import (
    MGLRUMarkovDebugfsWriter,
    RANK_BASED_CONFIDENCE,
    resolve_scope_cgroup_id,
)
from core.mglru_lstm_reclaim_policy import MGLRULSTMReclaimPolicyController
from core.operation_tracker import OperationTracker
from core.review_builder import ReviewBuilder
from core.runtime_scope import RuntimeAppScope, load_runtime_app_scope
from core.workload_classifier import ClassificationResult, classify_session
from core.workload_markov_builder import MarkovBuildResult, build_workload_markov
from core.schema import (
    APP_LIFECYCLE_EVENT_FIELDS,
    APP_STATE_1S_FIELDS,
    FOREGROUND_DEBUG_FIELDS,
    FOREGROUND_EVENT_FIELDS,
    GLOBAL_STATE_1S_FIELDS,
    OPERATION_EVENT_FIELDS,
    OPERATION_LABEL_FIELDS,
    PROCESS_EVENT_FIELDS,
)
from core.writer import CsvWriter
from online_duration_lstm import OnlineDurationLSTMRunner


class RuntimeMonitorV0:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.config = load_config(args.config)
        self.runtime_scope = _load_runtime_scope(args)
        if self.runtime_scope is not None:
            self.config = self.runtime_scope.as_process_mapper_config(self.config)
            self.target_apps = self.runtime_scope.target_apps
            if self.target_apps:
                self.args.target_app = self.target_apps[0]
            if self.runtime_scope.slice_name:
                self.args.test_slice = self.runtime_scope.slice_name
                self.args.cgroup_workload_slice = self.runtime_scope.slice_name
            if self.runtime_scope.workload_scopes:
                self.args.cgroup_workload_scopes = ",".join(self.runtime_scope.workload_scopes)
            self.args.app_key_to_vocab_name = self.runtime_scope.app_key_to_vocab_name
            self.args.loaded_runtime_scope = self.runtime_scope
            for warning in self.runtime_scope.vocab_warnings:
                print(f"warning: app scope vocab validation: {warning}", file=sys.stderr)
        else:
            self.target_apps = _parse_app_list(args.target_apps) or [args.target_app]
            self.args.app_key_to_vocab_name = {}
            self.args.loaded_runtime_scope = None
        self.session_id = _resolve_session_id(args)
        self.stop_requested = False

        # Directory structure
        requested_output = Path(args.output_dir)
        self.output_dir = requested_output if requested_output.name == self.session_id else requested_output / self.session_id
        self.model_dir = self.output_dir / "model"
        self.review_dir = self.output_dir / "review"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)

        # Collectors
        self.mapper = AppMapper(self.config, target_app=args.target_app, target_apps=self.target_apps)
        self.process_collector = ProcessCollector(
            mapper=self.mapper,
            target_app=args.target_app,
            target_apps=self.target_apps,
            target_pid=args.target_pid,
            target_comm=args.target_comm,
            test_slice=args.test_slice,
        )
        manual_pid = args.target_pid or 0
        self.foreground_collector = ForegroundCollector(
            backend=args.foreground_backend,
            manual_app=args.target_app if args.foreground_backend == "manual" else "",
            manual_pid=manual_pid,
            app_window_keywords=self.runtime_scope.window_keywords if self.runtime_scope else None,
        )
        self.file_collector = FileEventCollector(path_mode=args.path_mode)

        # Builders
        self.feature_builder = FeatureBuilder(
            label=args.label, session_id=self.session_id, test_slice=args.test_slice,
        )
        self.app_registry = AppRegistry(
            target_apps=self.target_apps,
            test_slice=args.test_slice,
            close_grace_windows=args.close_grace_windows,
        )
        self.app_feature_builder = AppFeatureBuilder(
            session_id=self.session_id, test_slice=args.test_slice,
        )
        self.lifecycle_builder = LifecycleEventBuilder(
            target_app=args.target_app,
            session_id=self.session_id,
            close_grace_windows=args.close_grace_windows,
            test_slice=args.test_slice,
        )

        # Operation tracker (reads automation_trace.csv if present)
        self.operation_tracker = OperationTracker(self.model_dir, self.session_id)

        # Review builder (generated at session end)
        self.review_builder = ReviewBuilder(self.model_dir, self.review_dir, self.session_id)

        # model/ CSV writers (7 files)
        self.global_state_writer = CsvWriter(
            self.model_dir / "global_state_1s.csv", GLOBAL_STATE_1S_FIELDS,
        )
        self.app_state_writer = CsvWriter(
            self.model_dir / "app_state_1s.csv", APP_STATE_1S_FIELDS,
        )
        self.foreground_events_writer = CsvWriter(
            self.model_dir / "foreground_events.csv", FOREGROUND_EVENT_FIELDS,
        )
        self.process_events_writer = CsvWriter(
            self.model_dir / "process_events.csv", PROCESS_EVENT_FIELDS,
        )
        self.app_lifecycle_writer = CsvWriter(
            self.model_dir / "app_lifecycle_events.csv", APP_LIFECYCLE_EVENT_FIELDS,
        )
        self.operation_events_writer = CsvWriter(
            self.model_dir / "operation_events.csv", OPERATION_EVENT_FIELDS,
        )
        self.operation_labels_writer = CsvWriter(
            self.model_dir / "operation_labels.csv", OPERATION_LABEL_FIELDS,
        )
        self.foreground_debug_writer = CsvWriter(
            self.model_dir / "foreground_debug.csv", FOREGROUND_DEBUG_FIELDS,
        )
        self.online_lstm = OnlineDurationLSTMRunner(args, self.model_dir, self.review_dir) if args.enable_online_lstm else None
        self.mglru_markov_writer = MGLRUMarkovDebugfsWriter(
            enabled=(
                args.enable_mglru_markov_debugfs
                or args.enable_mglru_lstm_reclaim_policy
            ),
            strict=args.mglru_markov_strict,
            debugfs_path=args.mglru_markov_debugfs_path,
            session_id=self.session_id,
            model_dir=self.model_dir,
            review_dir=self.review_dir,
            ttl_ms=args.mglru_markov_ttl_ms,
        )
        policy_config_path = _resolve_project_path(
            args.mglru_lstm_reclaim_policy_config, legacy_base=MONITOR_DIR
        )
        self.mglru_lstm_policy = MGLRULSTMReclaimPolicyController(
            enabled=args.enable_mglru_lstm_reclaim_policy,
            strict=args.mglru_lstm_policy_strict,
            config_path=policy_config_path,
            session_id=self.session_id,
            model_dir=self.model_dir,
            review_dir=self.review_dir,
            debugfs_writer=self.mglru_markov_writer,
        )
        self.last_mglru_foreground_app_key = ""
        self.last_mglru_binding_refresh_monotonic = 0.0
        self._scope_cgroup_cache: dict[tuple[str, str], int | None] = {}
        self.cgroup_workload_process: subprocess.Popen[Any] | None = None
        self.cgroup_workload_process_started = False
        self.cgroup_workload_exit_code: int | None = None
        self.cgroup_workload_raw_csv = self.model_dir / "cgroup_memory_workload_1s.csv"
        self.cgroup_workload_delta_csv = self.model_dir / "cgroup_memory_workload_delta_1s.csv"
        self.cgroup_workload_summary = self.review_dir / "cgroup_memory_workload_summary.md"
        self.cgroup_workload_log = self.review_dir / "cgroup_memory_workload_collector.log"
        self.workload_classifier_enabled = (
            args.enable_cgroup_workload and not args.disable_workload_classifier
        )
        self.workload_classifier_result: ClassificationResult | None = None
        self.cgroup_workload_state_csv = self.model_dir / "cgroup_workload_state_1s.csv"
        self.cgroup_workload_state_summary = self.review_dir / "cgroup_workload_state_summary.md"
        self.workload_markov_builder_enabled = (
            self.workload_classifier_enabled
            and not args.disable_workload_markov_builder
        )
        self.workload_markov_result: MarkovBuildResult | None = None
        self.workload_markov_transitions_csv = (
            self.model_dir / "workload_markov_transitions.csv"
        )
        self.workload_markov_summary = (
            self.review_dir / "workload_markov_summary.md"
        )

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------

    def run(self) -> int:
        signal.signal(signal.SIGINT, self._request_stop)
        signal.signal(signal.SIGTERM, self._request_stop)
        start = time.monotonic()
        next_tick = start
        print(f"Runtime Monitor v0 started. session_id={self.session_id}")
        print(f"  model: {self.model_dir}")
        print(f"  review: {self.review_dir}")
        if self.online_lstm is not None:
            print("  online duration LSTM: enabled")
            print(f"  online duration checkpoint: {self.args.lstm_checkpoint}")
        else:
            print("  online duration LSTM: disabled")
        if self.args.enable_cgroup_workload:
            self._start_cgroup_workload_collector()
            print("  cgroup workload collector: enabled")
            print(f"  cgroup workload raw_csv: {self.cgroup_workload_raw_csv}")
            print(f"  cgroup workload delta_csv: {self.cgroup_workload_delta_csv}")
        else:
            print("  cgroup workload collector: disabled")
        if self.args.enable_mglru_markov_debugfs:
            print("  MGLRU Markov debugfs writer: enabled")
            print(f"  MGLRU Markov debugfs path: {self.args.mglru_markov_debugfs_path}")
        else:
            print("  MGLRU Markov debugfs writer: disabled")
        if self.args.enable_mglru_lstm_reclaim_policy:
            self.mglru_lstm_policy.configure_kernel()
            self._maybe_refresh_mglru_app_bindings(force=True)
            print("  MGLRU LSTM app reclaim policy: enabled")
            print(f"  policy config: {self.mglru_lstm_policy.config_path}")
        else:
            print("  MGLRU LSTM app reclaim policy: disabled")
        print("No prefetch, active eviction, swap, generation, or anon/file policy action will be performed.")
        try:
            while not self.stop_requested:
                now = time.monotonic()
                if self.args.duration and now - start >= self.args.duration:
                    break
                if now < next_tick:
                    time.sleep(min(0.1, next_tick - now))
                    continue
                self.sample_once()
                next_tick += self.args.sample_interval
        finally:
            self._close_writers(close_mglru=False)
            self._stop_cgroup_workload_collector()
            self._run_workload_classifier()
            self._write_workload_state_changes()
            self._run_workload_markov_builder()
            self._write_workload_markov_sets()
            self.mglru_lstm_policy.close()
            self.mglru_markov_writer.close()
            self._generate_review()
            self._append_cgroup_workload_summary()
            print(
                f"Runtime Monitor v0 stopped."
                f" model={self.model_dir} review={self.review_dir}"
            )
        if self.args.mglru_lstm_policy_strict:
            return 0 if self.mglru_lstm_policy.strict_result() == "PASS" else 1
        return 0

    def sample_once(self) -> None:
        self._maybe_refresh_mglru_app_bindings()
        window_start_ns = time.time_ns()
        window_end_ns = window_start_ns + int(self.args.sample_interval * 1_000_000_000)

        # 1. Collect raw data
        samples = self.process_collector.sample()
        file_events = self.file_collector.poll(samples)  # in-memory only, not written to disk

        meminfo = read_meminfo()
        vmstat = read_vmstat()
        foreground = self.foreground_collector.sample()
        feature_window_id = self.feature_builder.feature_window_id

        # 2. Foreground debug CSV
        self.foreground_debug_writer.write_row(
            self.foreground_collector.debug_row(self.session_id, feature_window_id)
        )

        windows = self.foreground_collector.sample_windows()

        # 3. Lifecycle events → three event streams
        lifecycle_events = self.lifecycle_builder.build_all(
            samples=samples, foreground=foreground, windows=windows,
        )
        self.process_events_writer.write_rows(lifecycle_events.process_events)
        self.foreground_events_writer.write_rows(lifecycle_events.foreground_events)
        self.app_lifecycle_writer.write_rows(lifecycle_events.app_lifecycle)

        # 4. App registry update
        self.app_registry.update(samples=samples, foreground=foreground)
        registry_summary = self.app_registry.summary()

        # 5. Operation tracking
        self.operation_tracker.refresh()
        op_context = self.operation_tracker.get_current(window_start_ns, window_end_ns)
        new_ops = self.operation_tracker.pop_new_operation_events(
            foreground.foreground_app,
            registry_summary.get("open_apps", ""),
        )
        self.operation_events_writer.write_rows(new_ops)

        # Build per-app operation contexts for app_state rows
        op_app_map: dict[str, dict[str, str]] = {}
        for app_id in self.app_registry.observed_apps:
            op_app_map[app_id] = dict(op_context)

        # 6. App features → app_state_1s.csv
        app_feature_rows = self.app_feature_builder.build_rows(
            feature_window_id=feature_window_id,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
            records=self.app_registry.records_for_output(),
            samples=samples,
            file_events=file_events,
            foreground=foreground,
            operation_contexts=op_app_map,
        )
        self.app_state_writer.write_rows(app_feature_rows)

        # 7. Global features → global_state_1s.csv
        test_mem = _read_test_slice_memory(self.args.test_slice)
        feature_row = self.feature_builder.build(
            foreground=foreground,
            meminfo=meminfo,
            vmstat=vmstat,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
            registry_summary=registry_summary,
            foreground_window_id=foreground.window_id,
            foreground_pid=foreground.foreground_pid,
            foreground_wm_class=foreground.foreground_app,
            operation_context=op_context,
            test_mem_current=test_mem.get("current", 0),
            test_mem_high=test_mem.get("high", 0),
            test_mem_max=test_mem.get("max", 0),
        )
        self.global_state_writer.write_row(feature_row)
        self._maybe_write_mglru_current_app(feature_row)
        if self.online_lstm is not None:
            prediction_result = self.online_lstm.process_sample(feature_row)
            self._maybe_write_mglru_predictions(prediction_result)

        if self.args.verbose:
            print(
                f"sample pids={len(samples)} events={len(file_events)} "
                f"mem_available={feature_row.get('global_mem_available_kb')}"
            )

    # ------------------------------------------------------------------
    # private
    # ------------------------------------------------------------------

    def _close_writers(self, *, close_mglru: bool = True) -> None:
        self.global_state_writer.close()
        self.app_state_writer.close()
        self.foreground_events_writer.close()
        self.process_events_writer.close()
        self.app_lifecycle_writer.close()
        self.operation_tracker.refresh()
        self.operation_events_writer.write_rows(self.operation_tracker.pop_new_operation_events("", ""))
        self.operation_events_writer.close()
        self.operation_labels_writer.write_rows(self.operation_tracker.operation_label_rows())
        self.operation_labels_writer.close()
        self.foreground_debug_writer.close()
        if self.online_lstm is not None:
            self.online_lstm.close()
        if close_mglru:
            self.mglru_markov_writer.close()

    def _generate_review(self) -> None:
        try:
            self.review_builder.generate()
        except Exception as exc:
            print(f"warning: review generation failed: {exc}", file=sys.stderr)

    def _request_stop(self, _signum: int, _frame: Any) -> None:
        self.stop_requested = True

    def _start_cgroup_workload_collector(self) -> None:
        script = MONITOR_DIR / "scripts" / "collect_cgroup_memory_workload.py"
        cmd = [
            sys.executable,
            str(script),
            "--session-dir",
            str(self.output_dir),
            "--slice",
            str(self.args.cgroup_workload_slice),
            "--interval-s",
            str(self.args.cgroup_workload_interval_s),
            "--scopes",
            str(self.args.cgroup_workload_scopes),
        ]
        self.review_dir.mkdir(parents=True, exist_ok=True)
        log_f = self.cgroup_workload_log.open("w", encoding="utf-8")
        try:
            self.cgroup_workload_process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=MONITOR_DIR.parent,
                text=True,
            )
            log_f.close()
            self.cgroup_workload_process_started = True
        except Exception as exc:
            log_f.write(f"failed to start cgroup workload collector: {exc}\n")
            log_f.close()
            self.cgroup_workload_process = None
            self.cgroup_workload_process_started = False
            self.cgroup_workload_exit_code = -1
            print(f"warning: failed to start cgroup workload collector: {exc}", file=sys.stderr)

    def _stop_cgroup_workload_collector(self) -> None:
        proc = self.cgroup_workload_process
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self.cgroup_workload_exit_code = proc.returncode

    def _run_workload_classifier(self) -> None:
        if not self.workload_classifier_enabled:
            return
        if not self.cgroup_workload_delta_csv.exists():
            print(
                f"warning: workload classifier input does not exist: "
                f"{self.cgroup_workload_delta_csv}",
                file=sys.stderr,
            )
            return
        try:
            self.workload_classifier_result = classify_session(
                self.output_dir,
                self.args.app_scope_config,
            )
            for field in self.workload_classifier_result.missing_fields:
                print(
                    f"warning: workload classifier field missing, using 0: {field}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"warning: workload classifier failed: {exc}", file=sys.stderr)

    def _write_workload_state_changes(self) -> None:
        if not self.args.enable_mglru_markov_debugfs:
            return
        if not self.cgroup_workload_state_csv.exists():
            print(
                f"warning: workload state CSV does not exist: "
                f"{self.cgroup_workload_state_csv}",
                file=sys.stderr,
            )
            return
        try:
            with self.cgroup_workload_state_csv.open(
                "r", encoding="utf-8", newline=""
            ) as f:
                for row in csv.DictReader(f):
                    if str(row.get("state_changed", "")).strip().lower() != "true":
                        continue
                    scope_name = str(row.get("scope_name", "")).strip()
                    cgroup_id = _optional_int(row.get("cgroup_id"))
                    if cgroup_id is None:
                        cgroup_id = self._resolve_mglru_scope_cgroup_id(scope_name)
                    self.mglru_markov_writer.write_workload_update(
                        cgroup_id=cgroup_id,
                        app_id=_optional_int(row.get("app_id")),
                        workload_id=_optional_int(row.get("workload_id")),
                        app_key=str(row.get("app_key", "")).strip(),
                        workload_name=str(row.get("workload_name", "")).strip(),
                    )
        except Exception as exc:
            print(
                f"warning: failed to write workload state changes: {exc}",
                file=sys.stderr,
            )

    def _run_workload_markov_builder(self) -> None:
        if not self.workload_markov_builder_enabled:
            return
        if not self.cgroup_workload_state_csv.exists():
            print(
                f"warning: workload Markov builder 输入不存在: "
                f"{self.cgroup_workload_state_csv}",
                file=sys.stderr,
            )
            return
        try:
            self.workload_markov_result = build_workload_markov(self.output_dir)
            for field in self.workload_markov_result.missing_fields:
                print(
                    f"warning: workload Markov builder 输入字段缺失: {field}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"warning: workload Markov builder 失败: {exc}", file=sys.stderr)

    def _write_workload_markov_sets(self) -> None:
        if not self.args.enable_mglru_markov_debugfs:
            return
        if not self.workload_markov_transitions_csv.exists():
            print(
                f"warning: workload Markov 转移 CSV 不存在: "
                f"{self.workload_markov_transitions_csv}",
                file=sys.stderr,
            )
            return
        groups: dict[
            tuple[str, str, str, str], list[dict[str, int]]
        ] = {}
        try:
            with self.workload_markov_transitions_csv.open(
                "r", encoding="utf-8", newline=""
            ) as f:
                for row in csv.DictReader(f):
                    key = (
                        str(row.get("app_key", "")).strip(),
                        str(row.get("app_id", "")).strip(),
                        str(row.get("prev_workload_id", "")).strip(),
                        str(row.get("current_workload_id", "")).strip(),
                    )
                    next_workload_id = _optional_int(
                        row.get("next_workload_id")
                    )
                    confidence = _optional_int(row.get("confidence"))
                    boost_level = _optional_int(row.get("boost_level"))
                    if (
                        next_workload_id is None
                        or confidence is None
                        or boost_level is None
                    ):
                        continue
                    groups.setdefault(key, []).append(
                        {
                            "next_workload_id": next_workload_id,
                            "confidence": confidence,
                            "boost_level": boost_level,
                        }
                    )
            for (
                app_key,
                app_id,
                prev_workload_id,
                current_workload_id,
            ), entries in groups.items():
                self.mglru_markov_writer.write_markov_set(
                    app_id=_optional_int(app_id),
                    prev_workload_id=_optional_int(prev_workload_id),
                    current_workload_id=_optional_int(current_workload_id),
                    entries=entries,
                    app_key=app_key,
                )
        except Exception as exc:
            print(
                f"warning: workload Markov set 写入失败: {exc}",
                file=sys.stderr,
            )

    def _append_cgroup_workload_summary(self) -> None:
        summary_path = self.review_dir / "session_summary.md"
        lines = [
            "",
            "## Runtime 应用范围",
        ]
        if self.runtime_scope is not None:
            lines.extend(self.runtime_scope.summary_lines())
        else:
            lines.extend([
                f"- app_scope_config: `{self.args.app_scope_config}`",
                "- loaded_apps: none",
                "- workload_scopes: none",
                "- prediction_apps: none",
                "- app_key_to_vocab_name: none",
                "- app_scope_vocab_warnings: none",
            ])
        lines.extend([
            "",
            "## Cgroup Workload 采集器",
            f"- cgroup_workload_enabled: {str(bool(self.args.enable_cgroup_workload)).lower()}",
            f"- cgroup_workload_process_started: {str(self.cgroup_workload_process_started).lower()}",
            f"- cgroup_workload_raw_csv: `{self.cgroup_workload_raw_csv}`",
            f"- cgroup_workload_delta_csv: `{self.cgroup_workload_delta_csv}`",
            f"- cgroup_workload_summary: `{self.cgroup_workload_summary}`",
            f"- cgroup_workload_exit_code: {'' if self.cgroup_workload_exit_code is None else self.cgroup_workload_exit_code}",
            "",
            "## Cgroup Workload 分类器",
            f"- workload_classifier_enabled: {str(self.workload_classifier_enabled).lower()}",
            f"- cgroup_workload_state_csv: `{self.cgroup_workload_state_csv}`",
            f"- cgroup_workload_state_summary: `{self.cgroup_workload_state_summary}`",
            f"- workload_classifier_final_result: {self.workload_classifier_result.final_result if self.workload_classifier_result else 'NOT_RUN'}",
            "",
            "## Workload Markov 构建器",
            f"- workload_markov_builder_enabled: {str(self.workload_markov_builder_enabled).lower()}",
            f"- workload_markov_transitions_csv: `{self.workload_markov_transitions_csv}`",
            f"- workload_markov_summary: `{self.workload_markov_summary}`",
            f"- workload_markov_builder_final_result: {self.workload_markov_result.final_result if self.workload_markov_result else 'NOT_RUN'}",
            f"- markov_set_write_ok: {self.mglru_markov_writer.markov_set_write_ok}",
            "",
            "## MGLRU Markov Debugfs",
            f"- mglru_markov_debugfs_enabled: {str(bool(self.args.enable_mglru_markov_debugfs)).lower()}",
            f"- mglru_markov_debugfs_path: `{self.args.mglru_markov_debugfs_path}`",
            f"- mglru_markov_debugfs_csv: `{self.mglru_markov_writer.csv_path}`",
            f"- mglru_markov_debugfs_summary: `{self.mglru_markov_writer.summary_path}`",
            f"- workload_update_write_attempts: {self.mglru_markov_writer.workload_update_write_attempts}",
            f"- workload_update_write_ok: {self.mglru_markov_writer.workload_update_write_ok}",
            f"- workload_update_write_error: {self.mglru_markov_writer.workload_update_write_error}",
            f"- workload_update_skipped: {self.mglru_markov_writer.workload_update_skipped}",
            f"- markov_set_write_attempts: {self.mglru_markov_writer.markov_set_write_attempts}",
            f"- markov_set_write_ok: {self.mglru_markov_writer.markov_set_write_ok}",
            f"- markov_set_write_error: {self.mglru_markov_writer.markov_set_write_error}",
            f"- markov_set_skipped: {self.mglru_markov_writer.markov_set_skipped}",
            f"- mglru_markov_debugfs_final_result: {self.mglru_markov_writer.final_result()}",
            "",
            "## MGLRU LSTM 应用级回收策略",
            f"- mglru_lstm_reclaim_policy_enabled: {str(bool(self.args.enable_mglru_lstm_reclaim_policy)).lower()}",
            f"- mglru_lstm_reclaim_policy_config: `{self.mglru_lstm_policy.config_path}`",
            f"- mglru_lstm_reclaim_policy_csv: `{self.mglru_lstm_policy.csv_path}`",
            f"- mglru_lstm_reclaim_policy_summary: `{self.mglru_lstm_policy.summary_path}`",
            f"- policy_config_write_ok: {self.mglru_lstm_policy.policy_config_write_ok}",
            f"- app_bind_write_ok: {self.mglru_lstm_policy.app_bind_write_ok}",
            f"- app_probability_write_ok: {self.mglru_lstm_policy.app_probability_write_ok}",
            f"- probability_source: {','.join(sorted(self.mglru_lstm_policy.probability_sources)) or 'none'}",
            f"- probability_is_rank_based: {str(self.mglru_lstm_policy.probability_is_rank_based()).lower()}",
            f"- mglru_lstm_policy_strict_result: {self.mglru_lstm_policy.strict_result()}",
        ])
        try:
            self.review_dir.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as exc:
            print(f"warning: failed to append cgroup workload summary: {exc}", file=sys.stderr)

    def _maybe_write_mglru_current_app(self, feature_row: dict[str, Any]) -> None:
        if not (
            self.args.enable_mglru_markov_debugfs
            or self.args.enable_mglru_lstm_reclaim_policy
        ) or self.runtime_scope is None:
            return
        app_key = str(feature_row.get("foreground_app", "")).strip()
        if not app_key or app_key == self.last_mglru_foreground_app_key:
            return
        app_id = self.runtime_scope.app_key_to_app_id.get(app_key)
        scope_name = self.runtime_scope.app_key_to_scope_name.get(app_key, "")
        if not app_id:
            print(f"warning: MGLRU Markov current app has no app_id: {app_key}", file=sys.stderr)
            return
        cgroup_id = self._resolve_mglru_scope_cgroup_id(scope_name)
        if self.args.enable_mglru_lstm_reclaim_policy and cgroup_id is not None:
            binding_ttl_ms = max(
                self.mglru_lstm_policy.ttl_ms,
                int(self.args.mglru_app_binding_refresh_s * 3000),
            )
            self.mglru_lstm_policy.refresh_bindings(
                [
                    app
                    for app in self.runtime_scope.apps
                    if app.app_key == app_key
                ],
                self._resolve_mglru_scope_cgroup_id,
                binding_ttl_ms,
            )
        self.mglru_markov_writer.write_current_app(
            app_key=app_key,
            app_id=app_id,
            cgroup_id=cgroup_id,
            ttl_ms=self.args.mglru_markov_ttl_ms,
        )
        if cgroup_id is not None:
            self.last_mglru_foreground_app_key = app_key

    def _maybe_write_mglru_predictions(self, prediction_result: dict[str, Any]) -> None:
        if self.runtime_scope is None:
            return
        if prediction_result.get("status") != "success":
            return
        outputs = prediction_result.get("outputs", [])
        if not isinstance(outputs, list):
            return
        if self.args.enable_mglru_markov_debugfs:
            rows = [row for row in outputs if int(row.get("horizon", -1)) == 3]
            rows.sort(key=lambda row: int(row.get("rank", 0)))
            predictions: list[tuple[int, int]] = []
            for row in rows:
                app_name = str(row.get("app", "")).strip()
                app_id = self.runtime_scope.vocab_name_to_app_id.get(app_name)
                if not app_id or app_id not in self.runtime_scope.prediction_enabled_app_ids:
                    self.mglru_markov_writer.skip_prediction(f"missing_or_disabled_app_id:{app_name}")
                    continue
                rank_index = len(predictions)
                confidence = RANK_BASED_CONFIDENCE[rank_index] if rank_index < len(RANK_BASED_CONFIDENCE) else 1000
                predictions.append((app_id, confidence))
                if len(predictions) >= len(RANK_BASED_CONFIDENCE):
                    break
            self.mglru_markov_writer.write_predicted_apps(
                predictions, ttl_ms=self.args.mglru_markov_ttl_ms
            )

        if self.args.enable_mglru_lstm_reclaim_policy:
            all_rows = prediction_result.get("all_probabilities", [])
            probability_rows: list[dict[str, Any]] = []
            for row in all_rows if isinstance(all_rows, list) else []:
                if int(row.get("horizon", -1)) != 3:
                    continue
                app_name = str(row.get("app", "")).strip()
                app_id = self.runtime_scope.vocab_name_to_app_id.get(app_name)
                if not app_id or app_id not in self.runtime_scope.prediction_enabled_app_ids:
                    continue
                app_key = next(
                    (
                        app.app_key
                        for app in self.runtime_scope.apps
                        if app.app_id == app_id
                    ),
                    "",
                )
                probability_rows.append(
                    {
                        "app_key": app_key,
                        "app_id": app_id,
                        "probability": row.get("next_use_probability", row.get("probability")),
                        "probability_source": row.get("probability_source", "unavailable"),
                    }
                )
            self.mglru_lstm_policy.write_probabilities(probability_rows)

    def _maybe_refresh_mglru_app_bindings(self, *, force: bool = False) -> None:
        if not self.args.enable_mglru_lstm_reclaim_policy or self.runtime_scope is None:
            return
        now = time.monotonic()
        if not force and now - self.last_mglru_binding_refresh_monotonic < self.args.mglru_app_binding_refresh_s:
            return
        ttl_ms = max(
            self.mglru_lstm_policy.ttl_ms,
            int(self.args.mglru_app_binding_refresh_s * 3000),
        )
        self.mglru_lstm_policy.refresh_bindings(
            self.runtime_scope.apps,
            self._resolve_mglru_scope_cgroup_id,
            ttl_ms,
        )
        if self.last_mglru_foreground_app_key:
            app_key = self.last_mglru_foreground_app_key
            app_id = self.runtime_scope.app_key_to_app_id.get(app_key)
            scope_name = self.runtime_scope.app_key_to_scope_name.get(app_key, "")
            cgroup_id = self._resolve_mglru_scope_cgroup_id(scope_name)
            if app_id and cgroup_id:
                self.mglru_markov_writer.write_current_app(
                    app_key=app_key,
                    app_id=app_id,
                    cgroup_id=cgroup_id,
                    ttl_ms=self.args.mglru_markov_ttl_ms,
                )
        self.last_mglru_binding_refresh_monotonic = now

    def _resolve_mglru_scope_cgroup_id(self, scope_name: str) -> int | None:
        slice_name = self.args.cgroup_workload_slice or self.args.test_slice
        key = (slice_name, scope_name)
        if key in self._scope_cgroup_cache:
            return self._scope_cgroup_cache[key]
        cgroup_id = resolve_scope_cgroup_id(slice_name, scope_name)
        if cgroup_id is not None:
            self._scope_cgroup_cache[key] = cgroup_id
        return cgroup_id


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runtime Monitor v0 PC state collector.")
    parser.add_argument("--config", default=PROJECT_ROOT / "configs" / "runtime" / "config.yaml")
    parser.add_argument("--app-scope-config", default=PROJECT_ROOT / "configs" / "runtime" / "runtime_app_scope.json")
    parser.add_argument("--target-app", default="WPS")
    parser.add_argument("--target-apps", default="", help="Comma-separated observed apps, e.g. WPS,QQ,FILES.")
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "outputs" / "runtime_monitor"))
    parser.add_argument("--path-mode", choices=["raw", "hash", "basename"], default="hash")
    parser.add_argument("--target-pid", type=int)
    parser.add_argument("--target-comm")
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--enable-ebpf", action="store_true", help="Reserved.")
    parser.add_argument("--disable-ebpf", action="store_true", help="Use procfs polling fallback.")
    parser.add_argument("--foreground-backend", choices=["x11", "wayland", "manual"], default="x11")
    parser.add_argument("--label", default="", help="Default manual label for all feature rows.")
    parser.add_argument("--session-id", default="", help="Session id; defaults to YYYYMMDD_HHMMSS.")
    parser.add_argument("--test-slice", default="", help="systemd slice to scope monitoring to.")
    parser.add_argument("--close-grace-windows", type=int, default=2, help="Consecutive empty windows before APP_CLOSE.")
    parser.add_argument("--enable-online-lstm", action="store_true", help="Enable online duration-aware switch LSTM prediction.")
    parser.add_argument("--enable-cgroup-workload", action="store_true", help="Enable lightweight cgroup v2 memory workload collector.")
    parser.add_argument(
        "--disable-workload-classifier",
        action="store_true",
        help="Disable offline cgroup workload state classification.",
    )
    parser.add_argument(
        "--disable-workload-markov-builder",
        action="store_true",
        help="禁用离线 workload 二阶 Markov 转移构建。",
    )
    parser.add_argument("--cgroup-workload-interval-s", type=float, default=1.0, help="Cgroup workload sampling interval in seconds.")
    parser.add_argument(
        "--cgroup-workload-scopes",
        default="automation-wps.scope,automation-qq.scope,automation-files.scope",
        help="Comma-separated app scope names under the cgroup workload slice.",
    )
    parser.add_argument("--cgroup-workload-slice", default="huawei-test.slice", help="User systemd slice for cgroup workload collection.")
    parser.add_argument("--enable-mglru-markov-debugfs", action="store_true", help="Write current app and online LSTM top-k apps to MGLRU Markov debugfs.")
    parser.add_argument("--mglru-markov-debugfs-path", default="/sys/kernel/debug/lru_gen_workload_markov")
    parser.add_argument("--mglru-markov-ttl-ms", type=int, default=180000)
    parser.add_argument("--mglru-markov-strict", action="store_true", help="Mark MGLRU Markov debugfs result FAIL if debugfs writes cannot succeed.")
    parser.add_argument(
        "--enable-mglru-lstm-reclaim-policy",
        action="store_true",
        help="启用基于 LSTM next-use 概率的应用级 MGLRU 扫描预算策略写入。",
    )
    parser.add_argument(
        "--mglru-lstm-reclaim-policy-config",
        default=PROJECT_ROOT / "configs" / "runtime" / "mglru_lstm_reclaim_policy.json",
    )
    parser.add_argument("--mglru-app-binding-refresh-s", type=float, default=30.0)
    parser.add_argument(
        "--mglru-lstm-policy-strict",
        action="store_true",
        help="要求策略配置、至少一个 app bind 和真实概率写入全部成功。",
    )
    parser.add_argument(
        "--lstm-checkpoint",
        default=MONITOR_DIR.parent / "operation_predictor" / "outputs" / "checkpoints" / "app_lstm_duration" / "lsapp_app_lstm_duration_switch.pt",
    )
    parser.add_argument(
        "--app-vocab",
        default=MONITOR_DIR.parent / "operation_predictor" / "data" / "vocab" / "app_vocab_duration.json",
    )
    parser.add_argument("--app-mapping", default=PROJECT_ROOT / "configs" / "runtime" / "app_mapping.json")
    parser.add_argument(
        "--group-vocab",
        default=MONITOR_DIR.parent / "operation_predictor" / "data" / "vocab" / "user_group_vocab.json",
    )
    parser.add_argument("--user-group", default="通用用户")
    parser.add_argument("--history-len", type=int, default=5)
    parser.add_argument("--duration-cap-s", type=float, default=600.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--score-mode", choices=["softmax", "sigmoid"], default="sigmoid")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--trigger-mode", choices=["event_plus_ttl", "event_only"], default="event_plus_ttl")
    parser.add_argument("--prediction-ttl-s", type=float, default=180.0)
    parser.add_argument("--periodic-refresh-s", type=float, default=180.0)
    parser.add_argument("--min-event-cooldown-s", type=float, default=5.0)
    parser.add_argument("--disable-dwell-bucket-trigger", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def _load_runtime_scope(args: argparse.Namespace) -> RuntimeAppScope | None:
    if not args.app_scope_config:
        return None
    path = _resolve_project_path(args.app_scope_config, legacy_base=MONITOR_DIR)
    if not path.exists():
        print(f"warning: app scope config not found: {path}", file=sys.stderr)
        return None
    return load_runtime_app_scope(path, args.app_vocab)


def _resolve_project_path(value: str | Path, legacy_base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    project_path = PROJECT_ROOT / path
    if project_path.exists():
        return project_path
    if legacy_base is not None:
        legacy_path = legacy_base / path
        if legacy_path.exists():
            return legacy_path
    return project_path


def _parse_app_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _resolve_session_id(args: argparse.Namespace) -> str:
    if args.session_id:
        return args.session_id
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _read_test_slice_memory(test_slice: str) -> dict[str, int]:
    """Read memory.current, memory.high, memory.max from a cgroup slice."""
    if not test_slice:
        return {"current": 0, "high": 0, "max": 0}
    # Resolve the real cgroup path via systemctl
    base = Path("/sys/fs/cgroup")
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", test_slice, "-p", "ControlGroup"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("ControlGroup="):
                    cg = line.split("=", 1)[1].strip()
                    if cg:
                        base = Path("/sys/fs/cgroup") / cg.lstrip("/")
    except (OSError, subprocess.TimeoutExpired):
        pass

    out: dict[str, int] = {"current": 0, "high": 0, "max": 0}
    for key in out:
        try:
            text = (base / f"memory.{key}").read_text(encoding="utf-8").strip()
            out[key] = int(text)
        except (OSError, ValueError):
            pass
    return out


# ------------------------------------------------------------------
# entry point
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.enable_ebpf:
        print("warning: --enable-ebpf is reserved; v0 uses procfs polling fallback.", file=sys.stderr)
    if args.foreground_backend == "wayland":
        print("warning: Wayland foreground collection is not reliable in v0; using manual fallback.", file=sys.stderr)
        args.foreground_backend = "manual"
    monitor = RuntimeMonitorV0(args)
    return monitor.run()


if __name__ == "__main__":
    raise SystemExit(main())
