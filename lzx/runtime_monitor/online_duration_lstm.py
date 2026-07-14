"""Online duration-aware LSTM trigger and CSV output for Runtime Monitor v0."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from core.writer import CsvWriter
from predictor_duration import OnlineLSTMDurationPredictor


MODEL_CALL_TRACE_FIELDS = [
    "call_id",
    "session_id",
    "feature_window_id",
    "sample_timestamp",
    "wall_time",
    "latency_from_sample_ms",
    "trigger_type",
    "transition_from_raw",
    "transition_to_raw",
    "transition_from_mapped",
    "transition_to_mapped",
    "raw_foreground_app",
    "mapped_foreground_app",
    "raw_open_apps",
    "mapped_opened_apps",
    "raw_history_apps",
    "mapped_history_apps",
    "input_history_apps",
    "input_history_durations_s",
    "input_history_mask",
    "current_app_dwell_s",
    "user_group",
    "top_k",
    "score_mode",
    "device",
    "model_type",
    "checkpoint",
    "predict_latency_ms",
    "output_horizon_3",
    "output_horizon_5",
    "output_horizon_10",
    "status",
    "error",
]

REVIEW_CALL_TRACE_FIELDS = [
    "call_id",
    "time",
    "trigger_type",
    "foreground_app",
    "mapped_foreground_app",
    "opened_apps",
    "mapped_opened_apps",
    "history",
    "history_durations_s",
    "history_mask",
    "current_app_dwell_s",
    "top3_3min",
    "top3_5min",
    "top3_10min",
    "predict_latency_ms",
    "status",
    "note",
]

PREDICTION_FIELDS = [
    "session_id",
    "feature_window_id",
    "timestamp",
    "trigger_type",
    "raw_foreground_app",
    "mapped_foreground_app",
    "raw_open_apps",
    "mapped_opened_apps",
    "history_apps",
    "history_durations_s",
    "history_mask",
    "horizon",
    "rank",
    "app_id",
    "app_key",
    "runtime_app_id",
    "app",
    "raw_score",
    "raw_logit",
    "probability",
    "probability_fixed",
    "next_use_probability",
    "next_use_probability_fixed",
    "probability_source",
    "prediction_horizon_ms",
    "prediction_ttl_ms",
    "score_mode",
    "status",
    "skip_reason",
]

TIMELINE_FIELDS = [
    "time",
    "trigger_type",
    "foreground_app",
    "mapped_foreground_app",
    "opened_apps",
    "mapped_opened_apps",
    "history_apps",
    "history_durations_s",
    "horizon",
    "top1",
    "top3",
    "status",
    "note",
]

APP_NAME_MAP = {
    "WPS": "WPS",
    "QQ": "腾讯QQ",
    "FILES": "图库",
    "BILIBILI": "哔哩哔哩",
}
UNKNOWN_VALUES = {"", "UNKNOWN", "None", "none", "null", "NULL"}


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def format_time(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def fmt_duration(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")


def split_apps(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def map_app(raw_app: str | None) -> str:
    raw = "" if raw_app is None else str(raw_app).strip()
    if raw in UNKNOWN_VALUES:
        return "<UNKNOWN>"
    return APP_NAME_MAP.get(raw, "<UNKNOWN>")


def map_open_apps(raw_open_apps: str) -> list[str]:
    return dedupe_keep_order([map_app(app) for app in split_apps(raw_open_apps)])


def padded_history(apps: list[str], durations: list[float], history_len: int) -> tuple[list[str], list[str], list[str]]:
    apps = apps[-history_len:]
    durations = durations[-history_len:]
    pad_count = max(0, history_len - len(apps))
    return (
        ["<PAD>"] * pad_count + apps,
        ["0"] * pad_count + [fmt_duration(duration) for duration in durations],
        ["0"] * pad_count + ["1"] * len(apps),
    )


def json_rows_for_horizon(outputs: list[dict[str, Any]], horizon: int) -> str:
    rows = [
        {
            "rank": int(row["rank"]),
            "app_id": int(row["app_id"]),
            "app": str(row["app"]),
            "probability": float(row["probability"]),
            "raw_logit": float(row.get("raw_logit", row.get("raw_score", 0.0))),
            "probability_fixed": int(row.get("next_use_probability_fixed", 0)),
        }
        for row in outputs
        if int(row.get("horizon", -1)) == horizon
    ]
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def top_names(outputs: list[dict[str, Any]], horizon: int, limit: int = 3) -> str:
    rows = [row for row in outputs if int(row.get("horizon", -1)) == horizon]
    rows.sort(key=lambda row: int(row.get("rank", 0)))
    return "|".join(str(row.get("app", "")) for row in rows[:limit] if row.get("app"))


class OnlineDurationLSTMRunner:
    def __init__(self, args: argparse.Namespace, model_dir: Path, review_dir: Path) -> None:
        self.args = args
        self.model_dir = model_dir
        self.review_dir = review_dir
        configured_map = getattr(args, "app_key_to_vocab_name", {}) or {}
        self.app_name_map = dict(APP_NAME_MAP)
        self.app_name_map.update(_load_app_mapping_aliases(getattr(args, "app_mapping", "")))
        self.app_name_map.update({str(key): str(value) for key, value in configured_map.items()})
        self.vocab_name_to_app_key = {
            str(value): str(key) for key, value in configured_map.items()
        }
        runtime_scope = getattr(args, "loaded_runtime_scope", None)
        self.app_key_to_runtime_app_id = (
            runtime_scope.app_key_to_app_id if runtime_scope is not None else {}
        )
        self.call_id = 0
        self.skipped: Counter[str] = Counter()
        self.completed_segments: list[dict[str, Any]] = []
        self.current_segment: dict[str, Any] | None = None
        self.previous_row: dict[str, Any] | None = None
        self.previous_dwell_s = 0.0
        self.last_prediction_time: dt.datetime | None = None
        self.predictor_error = ""
        self.predictor: OnlineLSTMDurationPredictor | None = None

        self.model_call_writer = CsvWriter(model_dir / "online_lstm_duration_call_trace.csv", MODEL_CALL_TRACE_FIELDS)
        self.review_call_writer = CsvWriter(review_dir / "online_lstm_duration_call_trace.csv", REVIEW_CALL_TRACE_FIELDS)
        self.prediction_writer = CsvWriter(model_dir / "online_app_predictions_duration_1s.csv", PREDICTION_FIELDS)
        self.timeline_writer = CsvWriter(review_dir / "online_app_predictions_duration_timeline.csv", TIMELINE_FIELDS)

        try:
            self.predictor = OnlineLSTMDurationPredictor(
                checkpoint=args.lstm_checkpoint,
                app_vocab=args.app_vocab,
                group_vocab=args.group_vocab,
                user_group=args.user_group,
                history_len=args.history_len,
                duration_cap_s=args.duration_cap_s,
                top_k=args.top_k,
                score_mode=args.score_mode,
                device_name=args.device,
            )
        except Exception as exc:
            self.predictor_error = f"predictor_error:{exc}"
            print(f"warning: online duration LSTM disabled: {exc}")

    def close(self) -> None:
        self.model_call_writer.close()
        self.review_call_writer.close()
        self.prediction_writer.close()
        self.timeline_writer.close()

    def process_sample(self, feature_row: dict[str, Any]) -> dict[str, Any]:
        sample_time = parse_time(str(feature_row["timestamp"]))
        raw_fg = str(feature_row.get("foreground_app", ""))
        mapped_fg = self.map_app(raw_fg)
        raw_open_apps = str(feature_row.get("open_apps", ""))
        mapped_opened = self.map_open_apps(raw_open_apps)

        self._update_segments(feature_row, sample_time, raw_fg, mapped_fg)
        history_segments = self._history_segments(sample_time)
        raw_history = [str(item["raw_app"]) for item in history_segments]
        mapped_history = [str(item["mapped_app"]) for item in history_segments]
        durations = [float(item["dwell_s"]) for item in history_segments]
        input_history_apps, input_durations, input_mask = padded_history(mapped_history, durations, self.args.history_len)

        trigger_type, skip_reason = self._trigger(feature_row, sample_time, mapped_fg, mapped_opened)
        if trigger_type == "event_cooldown":
            skip_reason = "event_cooldown"
        if not any(mask == "1" for mask in input_mask):
            skip_reason = "no_valid_history"
        if trigger_type == "":
            skip_reason = "no_prediction_trigger"
        if self.predictor is None and not skip_reason:
            skip_reason = self.predictor_error

        base_prediction = {
            "session_id": feature_row.get("session_id", ""),
            "feature_window_id": feature_row.get("feature_window_id", ""),
            "timestamp": feature_row.get("timestamp", ""),
            "trigger_type": "" if trigger_type == "event_cooldown" else trigger_type,
            "raw_foreground_app": raw_fg,
            "mapped_foreground_app": mapped_fg,
            "raw_open_apps": raw_open_apps,
            "mapped_opened_apps": "|".join(mapped_opened),
            "history_apps": "|".join(input_history_apps),
            "history_durations_s": "|".join(input_durations),
            "history_mask": "|".join(input_mask),
            "score_mode": self.args.score_mode,
        }

        if skip_reason:
            self.skipped[skip_reason] += 1
            self.prediction_writer.write_row({**base_prediction, "status": "skipped", "skip_reason": skip_reason})
            self.previous_row = dict(feature_row)
            self.previous_dwell_s = self._current_dwell(sample_time)
            return {
                "status": "skipped",
                "skip_reason": skip_reason,
                "outputs": [],
                "mapped_foreground_app": mapped_fg,
                "raw_foreground_app": raw_fg,
            }

        assert self.predictor is not None
        status = "success"
        error = ""
        outputs: list[dict[str, Any]] = []
        all_probabilities: list[dict[str, Any]] = []
        bundle: dict[str, Any] = {"probability_source": "unavailable"}
        wall_dt = dt.datetime.now()
        wall_mono = time.perf_counter()
        try:
            bundle = self.predictor.predict_bundle(
                mapped_history,
                durations,
                mapped_opened,
                str(feature_row["timestamp"]),
            )
            outputs = list(bundle.get("top_k_outputs", []))
            all_probabilities = list(bundle.get("all_probabilities", []))
            if not outputs:
                status = "skipped"
                error = "predictor_returned_no_rows"
                self.skipped[error] += 1
        except Exception as exc:
            status = "error"
            error = f"predictor_error:{exc}"
            self.skipped[error] += 1
        predict_latency_ms = (time.perf_counter() - wall_mono) * 1000.0
        latency_from_sample_ms = max(0.0, (wall_dt - sample_time).total_seconds() * 1000.0)

        if status == "success":
            self.last_prediction_time = sample_time
            for output in all_probabilities:
                app_name = str(output.get("app", ""))
                app_key = self.vocab_name_to_app_key.get(app_name, "")
                self.prediction_writer.write_row({
                    **base_prediction,
                    "horizon": output.get("horizon", ""),
                    "rank": output.get("rank", ""),
                    "app_id": output.get("app_id", ""),
                    "app_key": app_key,
                    "runtime_app_id": self.app_key_to_runtime_app_id.get(app_key, ""),
                    "app": output.get("app", ""),
                    "raw_score": output.get("raw_score", ""),
                    "raw_logit": output.get("raw_logit", output.get("raw_score", "")),
                    "probability": output.get("probability", ""),
                    "probability_fixed": output.get("probability_fixed", output.get("next_use_probability_fixed", "")),
                    "next_use_probability": output.get("next_use_probability", ""),
                    "next_use_probability_fixed": output.get("next_use_probability_fixed", ""),
                    "probability_source": output.get("probability_source", "unavailable"),
                    "prediction_horizon_ms": int(output.get("horizon", 0)) * 60_000,
                    "prediction_ttl_ms": int(round(self.args.prediction_ttl_s * 1000)),
                    "score_mode": output.get("score_mode", self.args.score_mode),
                    "status": "success",
                    "skip_reason": "",
                })
            for horizon in [3, 5, 10]:
                self.timeline_writer.write_row({
                    "time": feature_row.get("timestamp", ""),
                    "trigger_type": trigger_type,
                    "foreground_app": raw_fg,
                    "mapped_foreground_app": mapped_fg,
                    "opened_apps": raw_open_apps,
                    "mapped_opened_apps": "|".join(mapped_opened),
                    "history_apps": "|".join(input_history_apps),
                    "history_durations_s": "|".join(input_durations),
                    "horizon": horizon,
                    "top1": top_names(outputs, horizon, 1),
                    "top3": top_names(outputs, horizon, 3),
                    "status": "success",
                    "note": "online duration-aware switch LSTM",
                })
        else:
            self.prediction_writer.write_row({**base_prediction, "status": status, "skip_reason": error})

        previous_raw = self.previous_row.get("foreground_app", "") if self.previous_row else ""
        previous_mapped = self.map_app(previous_raw) if self.previous_row else ""
        model_row = {
            "call_id": self.call_id,
            "session_id": feature_row.get("session_id", ""),
            "feature_window_id": feature_row.get("feature_window_id", ""),
            "sample_timestamp": feature_row.get("timestamp", ""),
            "wall_time": format_time(wall_dt),
            "latency_from_sample_ms": f"{latency_from_sample_ms:.3f}",
            "trigger_type": trigger_type,
            "transition_from_raw": previous_raw,
            "transition_to_raw": raw_fg,
            "transition_from_mapped": previous_mapped,
            "transition_to_mapped": mapped_fg,
            "raw_foreground_app": raw_fg,
            "mapped_foreground_app": mapped_fg,
            "raw_open_apps": raw_open_apps,
            "mapped_opened_apps": "|".join(mapped_opened),
            "raw_history_apps": "|".join(raw_history[-self.args.history_len:]),
            "mapped_history_apps": "|".join(mapped_history[-self.args.history_len:]),
            "input_history_apps": "|".join(input_history_apps),
            "input_history_durations_s": "|".join(input_durations),
            "input_history_mask": "|".join(input_mask),
            "current_app_dwell_s": fmt_duration(self._current_dwell(sample_time)),
            "user_group": self.args.user_group,
            "top_k": self.args.top_k,
            "score_mode": self.args.score_mode,
            "device": str(getattr(self.predictor, "device", self.args.device)),
            "model_type": "AppLSTMDurationV3",
            "checkpoint": self.args.lstm_checkpoint,
            "predict_latency_ms": f"{predict_latency_ms:.3f}",
            "output_horizon_3": json_rows_for_horizon(outputs, 3),
            "output_horizon_5": json_rows_for_horizon(outputs, 5),
            "output_horizon_10": json_rows_for_horizon(outputs, 10),
            "status": status,
            "error": error,
        }
        self.model_call_writer.write_row(model_row)
        self.review_call_writer.write_row({
            "call_id": self.call_id,
            "time": feature_row.get("timestamp", ""),
            "trigger_type": trigger_type,
            "foreground_app": raw_fg,
            "mapped_foreground_app": mapped_fg,
            "opened_apps": raw_open_apps,
            "mapped_opened_apps": "|".join(mapped_opened),
            "history": "|".join(input_history_apps),
            "history_durations_s": "|".join(input_durations),
            "history_mask": "|".join(input_mask),
            "current_app_dwell_s": fmt_duration(self._current_dwell(sample_time)),
            "top3_3min": top_names(outputs, 3),
            "top3_5min": top_names(outputs, 5),
            "top3_10min": top_names(outputs, 10),
            "predict_latency_ms": f"{predict_latency_ms:.3f}",
            "status": status,
            "note": "online duration-aware switch LSTM",
        })
        self.call_id += 1
        self.previous_row = dict(feature_row)
        self.previous_dwell_s = self._current_dwell(sample_time)
        return {
            "status": status,
            "skip_reason": error,
            "outputs": outputs,
            "all_probabilities": all_probabilities if status == "success" else [],
            "probability_source": (
                bundle.get("probability_source", "unavailable")
                if status == "success"
                else "unavailable"
            ),
            "mapped_foreground_app": mapped_fg,
            "raw_foreground_app": raw_fg,
        }

    def _update_segments(self, row: dict[str, Any], sample_time: dt.datetime, raw_fg: str, mapped_fg: str) -> None:
        if self.current_segment is None:
            self.current_segment = {
                "raw_app": raw_fg,
                "mapped_app": mapped_fg,
                "start_time": sample_time,
                "last_time": sample_time,
            }
            return
        if self.current_segment["mapped_app"] != mapped_fg:
            completed = dict(self.current_segment)
            completed["dwell_s"] = max(1.0, (completed["last_time"] - completed["start_time"]).total_seconds())
            self.completed_segments.append(completed)
            self.current_segment = {
                "raw_app": raw_fg,
                "mapped_app": mapped_fg,
                "start_time": sample_time,
                "last_time": sample_time,
            }
        else:
            self.current_segment["last_time"] = sample_time

    def _history_segments(self, sample_time: dt.datetime) -> list[dict[str, Any]]:
        segments = list(self.completed_segments)
        if self.current_segment is not None:
            current = dict(self.current_segment)
            current["dwell_s"] = self._current_dwell(sample_time)
            segments.append(current)
        return segments

    def _current_dwell(self, sample_time: dt.datetime) -> float:
        if self.current_segment is None:
            return 0.0
        return max(1.0, (sample_time - self.current_segment["start_time"]).total_seconds())

    def _trigger(
        self,
        row: dict[str, Any],
        sample_time: dt.datetime,
        mapped_fg: str,
        mapped_opened: list[str],
    ) -> tuple[str, str]:
        if self.last_prediction_time is None:
            return "initial_prediction", ""
        previous_mapped_fg = self.map_app(self.previous_row.get("foreground_app", "")) if self.previous_row else mapped_fg
        previous_opened = self.map_open_apps(str(self.previous_row.get("open_apps", ""))) if self.previous_row else mapped_opened
        event_triggers: list[str] = []
        if previous_mapped_fg != mapped_fg:
            event_triggers.append("foreground_transition")
        if set(previous_opened) != set(mapped_opened):
            event_triggers.append("opened_apps_change")
        if event_triggers:
            elapsed = (sample_time - self.last_prediction_time).total_seconds()
            if elapsed < self.args.min_event_cooldown_s:
                return "event_cooldown", "event_cooldown"
            return "+".join(dedupe_keep_order(event_triggers)), ""
        elapsed = (sample_time - self.last_prediction_time).total_seconds()
        if self.args.trigger_mode == "event_plus_ttl" and elapsed >= self.args.prediction_ttl_s:
            return f"periodic_ttl_refresh_{fmt_duration(self.args.periodic_refresh_s)}s", ""
        return "", "no_prediction_trigger"

    def map_app(self, raw_app: str | None) -> str:
        raw = "" if raw_app is None else str(raw_app).strip()
        if raw in UNKNOWN_VALUES:
            return "<UNKNOWN>"
        return self.app_name_map.get(raw, "<UNKNOWN>")

    def map_open_apps(self, raw_open_apps: str) -> list[str]:
        return dedupe_keep_order([self.map_app(app) for app in split_apps(raw_open_apps)])


def _load_app_mapping_aliases(path_value: str | Path | None) -> dict[str, str]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    aliases: dict[str, str] = {}
    for rule in config.get("rules", []):
        if not isinstance(rule, dict):
            continue
        app = str(rule.get("app", "")).strip()
        if not app:
            continue
        aliases[app] = app
        for key in ("gtk_app_id", "wm_class", "process", "title_contains"):
            raw_values = rule.get(key, [])
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            for value in values:
                alias = str(value).strip()
                if alias:
                    aliases[alias] = app
                    aliases[alias.upper()] = app
    return aliases
