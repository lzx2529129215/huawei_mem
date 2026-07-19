from __future__ import annotations

from pathlib import Path

from build_workload_feature_vector import FEATURE_ORDER, build_vector, parse_report


ROOT = Path(__file__).resolve().parents[1]


def test_old_markdown_segment_summary_still_builds_exactly_56_dimensions() -> None:
    report = parse_report(ROOT / "referenced.md")
    result = build_vector([report])
    assert len(FEATURE_ORDER) == 56
    assert result["feature_dimension"] == 56
    assert len(result["raw_vector"]) == 56
    assert len(result["log1p_vector"]) == 56
