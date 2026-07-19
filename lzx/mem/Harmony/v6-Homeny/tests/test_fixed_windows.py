from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from fixed_window_mapping import (
    COMPATIBILITY_ESTIMATION_METHOD,
    PRIMARY_ESTIMATION_METHOD,
    aggregate_execution,
    classify_fixed_window,
    cosine_similarity,
    map_fixed_window,
    median_baseline_vmas,
    normalize_segment_label,
    top_k_overlap,
    weighted_jaccard,
)
from analyze_fixed_windows import similarity_rows, summarize_similarity, support_rows
from run_wps_workload import build_session_command, parse_args as parse_workload_args
from wps_v6_session import LEGACY_OPERATION_FIELDS, NEW_OPERATION_FIELDS, Session, parse_args


def config(**fixed_overrides):
    fixed = {
        "enabled": True, "target_window_s": 5.0, "ok_tolerance_s": 0.5,
        "minor_tolerance_s": 1.0, "baseline_window_count": 2,
        "use_baseline_median": True, "exclude_partial_windows_from_support": True,
        "exclude_overrun_windows_from_support": True, "max_action_overrun_s": 2.0,
        "collect_after_each_window": True,
    }
    fixed.update(fixed_overrides)
    return {
        "schema_version": 1, "fixed_windows": fixed,
        "idle_baseline": {"min_valid_window_s": 1, "normal_duration_ratio_min": .5,
                          "normal_duration_ratio_max": 2, "mismatch_duration_ratio_min": .25,
                          "mismatch_duration_ratio_max": 4},
        "activity_thresholds": {"strong_absolute_pages": 10, "strong_min_pages": 5,
                                "strong_excess_rss_ratio": .1, "weak_min_pages": 1,
                                "weak_excess_rss_ratio": .01},
    }


@pytest.mark.parametrize(("actual", "quality", "eligible"), [
    (5.0, "OK", True), (5.5, "OK", True), (5.75, "MINOR_MISMATCH", True),
    (3.9, "PARTIAL_WINDOW", False), (6.1, "OVERRUN_WINDOW", False),
    (7.1, "SEVERE_OVERRUN", False),
])
def test_fixed_window_quality_classes(actual, quality, eligible):
    result = classify_fixed_window(actual, config())
    assert result["window_quality"] == quality
    assert result["support_eligible"] is eligible


def vma(pages: float, *, inode: int = 9, start: int = 4096, end: int = 8192):
    return {
        "pid": 10, "page_size_bytes": 4096, "start_address": start, "end_address": end,
        "address_size_bytes": end - start, "permissions": "r--p", "file_offset_bytes": 0,
        "file_offset_end_bytes": end - start, "device": "08:01", "dev_major": 8,
        "dev_minor": 1, "inode": inode, "path": "/x", "normalized_path": "/x",
        "segment": "File", "mapping_type": "FILE", "rss_kib": 40,
        "referenced_kib": pages * 4, "referenced_pages": pages,
        "referenced_size_ratio": 0.1, "referenced_rss_ratio": 0.1,
    }


def process(starttime=100):
    return {"pid": "10", "process_starttime": starttime, "starttime_available": True,
            "process_role": "WPS_MAIN"}


def baseline(window_id: str, pages: float, eligible=True):
    return {"window_id": window_id, "actual_window_s": 5.0, "support_eligible": eligible,
            "collection_quality": "OK", "processes": [process()], "vmas": [vma(pages)]}


def operation(pages: float, eligible=True):
    return {"window_id": "op-1", "operation_execution_id": "e1", "operation_id": "04_heavy",
            "segment_index": 1, "segment_label": "EDIT_BATCH_01", "baseline_group_id": "b1",
            "actual_window_s": 5.0, "window_quality": "OK", "support_eligible": eligible,
            "support_exclusion_reason": "", "collection_quality": "OK",
            "processes": [process()], "vmas": [vma(pages)]}


def test_two_baselines_use_per_vma_median():
    rows, duration, quality, valid = median_baseline_vmas([baseline("b1", 2), baseline("b2", 6)])
    assert rows[0]["referenced_pages"] == 4
    assert duration == 5
    assert quality == "OK" and len(valid) == 2


def test_single_baseline_is_explicitly_degraded():
    rows, _, quality, _ = median_baseline_vmas([baseline("b1", 2), baseline("b2", 6, False)])
    assert rows[0]["referenced_pages"] == 2
    assert quality == "SINGLE_BASELINE_WINDOW"


def test_no_valid_baseline_is_not_silently_inactive():
    result = map_fixed_window(baseline_windows=[baseline("b1", 2, False)], operation_window=operation(8),
                              app_id="wps", config=config())
    assert result["baseline_quality"] == "NO_VALID_BASELINE_WINDOWS"
    assert result["support_eligible"] is False
    assert result["paired_vmas"] == []


def test_fixed_excess_and_time_normalized_compatibility_fields():
    result = map_fixed_window(baseline_windows=[baseline("b1", 2), baseline("b2", 6)],
                              operation_window=operation(10), app_id="wps", config=config())
    sample = result["file_samples"][0]
    assert sample["estimated_excess_pages"] == 6
    assert sample["time_normalized_estimated_excess_pages"] == 6
    assert sample["primary_estimation_method"] == PRIMARY_ESTIMATION_METHOD
    assert sample["compatibility_estimation_method"] == COMPATIBILITY_ESTIMATION_METHOD


def test_fixed_excess_is_clamped_at_zero():
    result = map_fixed_window(baseline_windows=[baseline("b1", 8), baseline("b2", 10)],
                              operation_window=operation(2), app_id="wps", config=config())
    assert result["file_samples"][0]["estimated_excess_pages"] == 0


def test_window_annotations_and_normalized_edit_label_are_preserved():
    result = map_fixed_window(baseline_windows=[baseline("b1", 1), baseline("b2", 1)],
                              operation_window=operation(3), app_id="wps", config=config())
    sample = result["file_samples"][0]
    assert sample["window_id"] == "op-1"
    assert sample["baseline_group_id"] == "b1"
    assert sample["normalized_segment_label"] == "EDIT_BATCH"


def test_ineligible_operation_window_is_excluded_not_inactive():
    op = operation(8, False)
    op["support_exclusion_reason"] = "OVERRUN_WINDOW"
    result = map_fixed_window(baseline_windows=[baseline("b1", 1), baseline("b2", 1)],
                              operation_window=op, app_id="wps", config=config())
    assert not result["support_eligible"]
    assert all(not item["support_eligible"] for item in result["file_samples"])


def test_execution_aggregate_declares_non_unique_page_semantics():
    sample = {"semantic_file_key": "f", "estimated_excess_pages": 3, "activity_level": "WEAK"}
    result = aggregate_execution([{"support_eligible": True, "file_samples": [sample], "anonymous_samples": []},
                                  {"support_eligible": True, "file_samples": [sample], "anonymous_samples": []}])
    assert result["sum_estimated_excess_vma_pages"] == 6
    assert result["aggregation_semantics"] == "SUM_OF_VMA_WINDOW_SAMPLES_NOT_UNIQUE_PAGE_SET"


def test_invalid_window_does_not_enter_execution_aggregate():
    result = aggregate_execution([{"support_eligible": False, "file_samples": [
        {"semantic_file_key": "f", "estimated_excess_pages": 9}], "anonymous_samples": []}])
    assert result["eligible_window_count"] == 0
    assert result["feature_aggregates"] == []


def test_segment_normalization_only_removes_numeric_batch_suffix():
    assert normalize_segment_label("EDIT_BATCH_04") == "EDIT_BATCH"
    assert normalize_segment_label("EDIT_BATCH_04_CHUNK_03") == "EDIT_BATCH"
    assert normalize_segment_label("SCROLL_DOWN") == "SCROLL_DOWN"


def test_similarity_metrics():
    left, right = {"a": 2.0, "b": 1.0}, {"a": 2.0, "c": 1.0}
    assert weighted_jaccard(left, right) == pytest.approx(0.5)
    assert cosine_similarity(left, right) == pytest.approx(0.8)
    assert top_k_overlap(left, right, 1) == 1.0


def test_window_ids_are_unique_and_early_action_is_padded(tmp_path: Path):
    session = Session.__new__(Session)
    session.fixed_window_counter = 0
    session.fixed_window_records = []
    session.vma_mapping_dir = tmp_path
    session.vma_mapping_config = config(target_window_s=.02, ok_tolerance_s=.02, minor_tolerance_s=.03)
    session.clear_refs = lambda: None
    session.snapshot = lambda: [process()]
    session.sample = lambda *_args: {
        "markdown_reports": [], "jsonl_reports": [], "report": "", "collection_ended_at": "end",
        "collection_elapsed_s": 0, "hash_mismatch_count": 0,
    }
    started = time.perf_counter()
    first = session.run_fixed_window(operation_execution_id="e", operation_id="op", segment_index=1,
                                     segment_label="NO_UI", window_kind="OPERATION", target_duration_s=.02)
    second = session.run_fixed_window(operation_execution_id="e", operation_id="op", segment_index=2,
                                      segment_label="NO_UI", window_kind="OPERATION", target_duration_s=.02)
    assert time.perf_counter() - started >= .04
    assert first["window_id"] != second["window_id"]
    assert first["actual_window_s"] >= .019


def test_fixed_cli_defaults_and_passthrough():
    session_args = parse_args([])
    assert session_args.fixed_windows and session_args.fixed_window_s == 5.0
    args = parse_workload_args(["--fixed-window-s", "6", "--baseline-window-count", "3",
                                "--fixed-window-ok-tolerance-s", ".25"])
    command = build_session_command(args, "session.py", "trial", "id")
    assert command[command.index("--fixed-window-s") + 1] == "6.0"
    assert command[command.index("--baseline-window-count") + 1] == "3"


def test_operations_csv_extension_preserves_all_legacy_fields():
    combined = LEGACY_OPERATION_FIELDS + NEW_OPERATION_FIELDS
    assert combined[:len(LEGACY_OPERATION_FIELDS)] == LEGACY_OPERATION_FIELDS
    assert "fixed_windows_enabled" in NEW_OPERATION_FIELDS
    assert "window_sequence_path" in NEW_OPERATION_FIELDS


def test_window_jsonl_keeps_action_metadata(tmp_path: Path):
    session = Session.__new__(Session)
    session.fixed_window_counter = 0
    session.fixed_window_records = []
    session.vma_mapping_dir = tmp_path
    session.vma_mapping_config = config(target_window_s=.001, ok_tolerance_s=.01)
    session.clear_refs = lambda: None
    session.snapshot = lambda: [process()]
    session.sample = lambda *_args: {"markdown_reports": [], "jsonl_reports": [], "report": "",
                                    "collection_ended_at": "end", "collection_elapsed_s": 0,
                                    "hash_mismatch_count": 0}
    session.run_fixed_window(operation_execution_id="e", operation_id="op", segment_index=1,
                             segment_label="EDIT_BATCH_01", window_kind="OPERATION", target_duration_s=.001,
                             action_callback=lambda: {"action_count": 2, "content_range": [1, 2]})
    row = json.loads((tmp_path / "operation_window_samples.jsonl").read_text().splitlines()[0])
    assert row["action_count"] == 2
    assert row["action_metadata"]["content_range"] == [1, 2]


def test_segment_and_operation_support_use_valid_execution_denominators():
    windows = [
        {"window_id": "w1", "operation_execution_id": "e1", "operation_id": "edit",
         "segment_label": "EDIT_BATCH_01", "support_eligible": True},
        {"window_id": "w2", "operation_execution_id": "e2", "operation_id": "edit",
         "segment_label": "EDIT_BATCH_02", "support_eligible": True},
        {"window_id": "w3", "operation_execution_id": "e3", "operation_id": "edit",
         "segment_label": "EDIT_BATCH_03", "support_eligible": False},
    ]
    samples = [{"window_id": "w1", "operation_execution_id": "e1", "operation_id": "edit",
                "segment_label": "EDIT_BATCH_01", "support_eligible": True,
                "activity_level": "WEAK", "semantic_file_key": "f"}]
    rows = support_rows(windows, samples, "semantic_file_key")
    segment = next(item for item in rows if item["support_level"] == "SEGMENT")
    operation_row = next(item for item in rows if item["support_level"] == "OPERATION")
    assert segment["normalized_segment_label"] == "EDIT_BATCH"
    assert segment["valid_execution_count"] == 2 and segment["support"] == .5
    assert operation_row["valid_execution_count"] == 2 and operation_row["support"] == .5


def test_similarity_relations_and_three_feature_modes_are_emitted():
    windows = [
        {"window_id": "w1", "operation_id": "edit", "segment_label": "EDIT_BATCH_01", "support_eligible": True},
        {"window_id": "w2", "operation_id": "edit", "segment_label": "EDIT_BATCH_02", "support_eligible": True},
        {"window_id": "w3", "operation_id": "scroll", "segment_label": "SCROLL_DOWN", "support_eligible": True},
    ]
    files = [{"window_id": item["window_id"], "semantic_file_key": "f", "estimated_excess_pages": 1,
              "support_eligible": True} for item in windows]
    rows = similarity_rows(windows, files, [])
    assert {item["feature_mode"] for item in rows} == {"FILE_ONLY", "ANON_ONLY", "FILE_ANON"}
    assert {item["relation"] for item in rows} == {"SAME_SEGMENT", "DIFFERENT_OPERATION"}
    summary = summarize_similarity(rows)
    assert summary["SAME_SEGMENT"]["FILE_ONLY"]["weighted_jaccard"]["sample_count"] == 1
