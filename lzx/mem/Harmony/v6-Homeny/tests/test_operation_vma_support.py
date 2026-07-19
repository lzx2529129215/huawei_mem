from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from analyze_operation_vma_mapping import analyze, classify_support


@pytest.mark.parametrize(
    ("support", "expected"),
    [(0.8, "CORE"), (0.799, "COMMON"), (0.5, "COMMON"), (0.499, "OCCASIONAL"), (0.2, "OCCASIONAL"), (0.199, "NOISE")],
)
def test_support_classification_boundaries(config: dict[str, object], support: float, expected: str) -> None:
    assert classify_support(support, config) == expected


def write_trial(root: Path, index: int, *, valid: bool, active_keys: set[str]) -> None:
    trial = root / f"trial_{index:02d}"
    mapping = trial / "vma_mapping"
    mapping.mkdir(parents=True)
    with (trial / "operations.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "stage", "success", "baseline_status", "vma_mapping_status", "collection_quality",
            "process_match_quality", "baseline_quality", "window_quality", "activity_quality",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "stage": "03_write_metadata",
            "success": "true",
            "baseline_status": "ENABLED" if valid else "NO_BASELINE",
            "vma_mapping_status": "OK" if valid else "NO_BASELINE",
            "collection_quality": "OK",
            "process_match_quality": "OK",
            "baseline_quality": "OK" if valid else "NO_BASELINE",
            "window_quality": "OK",
            "activity_quality": "OK" if valid else "NO_BASELINE",
        })
    keys = {"core", "common", "occasional", "noise"}
    with (mapping / "operation_file_vma_samples.jsonl").open("w", encoding="utf-8") as handle:
        for key in keys:
            level = "STRONG" if key in active_keys else "INACTIVE"
            handle.write(json.dumps({
                "stage": "03_write_metadata",
                "semantic_file_key": key,
                "activity_level": level,
                "estimated_excess_referenced_pages": 16 if level == "STRONG" else 0,
                "estimated_excess_rss_ratio": 0.1 if level == "STRONG" else 0,
                "process_role": "WPS_MAIN",
                "identity_confidence": "HIGH",
                "file_instance_key": f"instance-{key}",
                "granularity": "FILE_VMA_OFFSET_INTERVAL",
                "protection_eligible": False,
                "baseline_quality": "OK" if valid else "NO_BASELINE",
                "collection_quality": "OK",
                "process_match_quality": "OK",
                "window_quality": "OK",
                "activity_quality": "OK" if valid else "NO_BASELINE",
            }) + "\n")
    (mapping / "operation_anon_vma_samples.jsonl").write_text(
        json.dumps({
            "stage": "03_write_metadata",
            "anonymous_auxiliary_key": "anon-one",
            "activity_level": "WEAK" if "core" in active_keys else "INACTIVE",
            "estimated_excess_referenced_pages": 5,
            "estimated_excess_rss_ratio": 0.03,
            "process_role": "WPS_CEF_RENDERER",
            "identity_confidence": "MEDIUM",
            "long_term_page_mapping": False,
            "protection_eligible": False,
            "prefetch_eligible": False,
            "baseline_quality": "OK" if valid else "NO_BASELINE",
            "collection_quality": "OK",
            "process_match_quality": "OK",
            "window_quality": "OK",
            "activity_quality": "OK" if valid else "NO_BASELINE",
        }) + "\n",
        encoding="utf-8",
    )


def test_analyze_uses_only_valid_executions_in_support_denominator(tmp_path: Path) -> None:
    write_trial(tmp_path, 1, valid=True, active_keys={"core", "common", "occasional"})
    write_trial(tmp_path, 2, valid=True, active_keys={"core", "common"})
    write_trial(tmp_path, 3, valid=True, active_keys={"core", "common"})
    write_trial(tmp_path, 4, valid=True, active_keys={"core"})
    write_trial(tmp_path, 5, valid=False, active_keys=set())

    result = analyze(tmp_path, expected_repeats=5)
    rows = {row["semantic_file_key"]: row for row in result["file_support"]}
    assert rows["core"]["valid_execution_count"] == 4
    assert rows["core"]["active_execution_count"] == 4
    assert rows["core"]["support_class"] == "CORE"
    assert rows["common"]["active_support"] == 0.75
    assert rows["common"]["support_class"] == "COMMON"
    assert rows["occasional"]["active_support"] == 0.25
    assert rows["occasional"]["support_class"] == "OCCASIONAL"
    assert rows["noise"]["active_support"] == 0
    assert rows["noise"]["support_class"] == "NOISE"
    assert result["quality"]["invalid_execution_count"] == 1
    assert (tmp_path / "operation_file_vma_support.csv").is_file()
    assert (tmp_path / "operation_anon_vma_support.csv").is_file()
    assert (tmp_path / "operation_vma_analysis.md").is_file()
    report = (tmp_path / "operation_vma_analysis.md").read_text(encoding="utf-8")
    for heading in (
        "Code baseline",
        "Stage windows",
        "Baseline completeness",
        "PID and role distribution",
        "New PID without baseline",
        "File VMA pairing",
        "Anonymous VMA pairing",
        "Split/merge",
        "Window mismatch",
        "Referenced before and after estimate",
        "Per-operation file activity",
        "Per-operation anonymous features",
        "Shared-library top mappings",
        "Current-document top mappings",
        "Semantic file support",
        "Anonymous auxiliary support",
        "Support class distribution",
        "File mapping suitability",
        "Operation recognition suitability",
        "Current limitations",
    ):
        assert f"## {heading}" in report
    assert result["readiness"]["ready_for_operation_recognition"] is False
    assert result["readiness"]["ready_for_apply"] is False


def test_readiness_rejects_incomplete_identity_and_unsafe_anon_flags(tmp_path: Path) -> None:
    write_trial(tmp_path, 1, valid=True, active_keys={"core"})
    file_path = tmp_path / "trial_01" / "vma_mapping" / "operation_file_vma_samples.jsonl"
    file_items = [json.loads(line) for line in file_path.read_text(encoding="utf-8").splitlines()]
    file_items[0].pop("file_instance_key")
    file_path.write_text("".join(json.dumps(item) + "\n" for item in file_items), encoding="utf-8")
    anon_path = tmp_path / "trial_01" / "vma_mapping" / "operation_anon_vma_samples.jsonl"
    anon = json.loads(anon_path.read_text(encoding="utf-8"))
    anon["protection_eligible"] = True
    anon_path.write_text(json.dumps(anon) + "\n", encoding="utf-8")

    result = analyze(tmp_path, expected_repeats=1)
    assert result["readiness"]["ready_for_idle_baseline_collection"] is True
    assert result["readiness"]["ready_for_file_vma_mapping"] is False
    assert result["readiness"]["ready_for_anon_aux_features"] is False
