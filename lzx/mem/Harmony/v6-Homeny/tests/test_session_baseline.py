from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from wps_v6_session import Session


def sample_payload(kind: str) -> dict[str, Any]:
    prefix = {"BASELINE": "baseline", "OPERATION": "operation", "POST_LAUNCH": "post_launch"}[kind]
    markdown = f"/{prefix}.md"
    jsonl = f"/{prefix}.jsonl"
    return {
        "sample_kind": kind,
        "report": markdown if kind != "BASELINE" else "",
        "report_count": 1 if kind != "BASELINE" else 0,
        f"{prefix}_report": markdown,
        f"{prefix}_report_count": 1,
        f"{prefix}_jsonl_report": jsonl,
        f"{prefix}_jsonl_report_count": 1,
        "markdown_reports": [markdown],
        "jsonl_reports": [jsonl],
        "collection_started_at": "start",
        "collection_ended_at": "end",
        "collection_elapsed_s": 0.01,
        "report_pull_started_at": "pull-start",
        "report_pull_ended_at": "pull-end",
        "report_pull_elapsed_s": 0.01,
        "device_report_count": 2,
        "local_report_count": 2,
        "matched_report_count": 2,
        "hash_mismatch_count": 0,
    }


def make_session() -> tuple[Session, list[str], list[dict[str, Any]]]:
    session = Session.__new__(Session)
    session.args = SimpleNamespace(idle_baseline=True, baseline_window_s=0.001, disable_vma_mapping=True)
    session.failures = []
    session.warnings = []
    session.saved_document = None
    clear_calls: list[str] = []
    sample_calls: list[dict[str, Any]] = []
    written: list[dict[str, Any]] = []
    process_rows = [{"pid": "10", "process_starttime": 100, "starttime_available": True, "process_role": "WPS_MAIN"}]
    session.snapshot = lambda: [dict(item) for item in process_rows]  # type: ignore[method-assign]
    session.clear_refs = lambda: clear_calls.append("clear")  # type: ignore[method-assign]

    def sample(index: int, stage: str, kind: str, processes: list[dict[str, Any]]) -> dict[str, Any]:
        sample_calls.append({"index": index, "stage": stage, "kind": kind, "processes": processes})
        return sample_payload(kind)

    session.sample = sample  # type: ignore[method-assign]
    session.write_operation = lambda record: written.append(dict(record))  # type: ignore[method-assign]
    session._written = written  # type: ignore[attr-defined]
    return session, clear_calls, sample_calls


def test_measured_stage_collects_baseline_then_operation_and_preserves_report() -> None:
    session, clear_calls, sample_calls = make_session()
    actions: list[str] = []
    success = session.measured_stage(3, "03_write_metadata", "metadata", "write", lambda: actions.append("write"), 0)
    record = session._written[0]  # type: ignore[attr-defined]

    assert success is True
    assert clear_calls == ["clear", "clear"]
    assert [item["kind"] for item in sample_calls] == ["BASELINE", "OPERATION"]
    assert actions == ["write"]
    assert record["baseline_report"] == "/baseline.md"
    assert record["baseline_jsonl_report"] == "/baseline.jsonl"
    assert record["report"] == "/operation.md"
    assert record["operation_jsonl_report"] == "/operation.jsonl"
    assert record["baseline_window_s"] > 0
    assert record["operation_window_s"] >= 0
    assert record["baseline_status"] == "ENABLED"
