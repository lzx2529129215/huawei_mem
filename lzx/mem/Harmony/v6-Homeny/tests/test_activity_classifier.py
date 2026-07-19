from __future__ import annotations

import pytest

from operation_vma_mapping import classify_activity, estimate_background_activity, window_quality


@pytest.mark.parametrize(
    ("pages", "ratio", "expected"),
    [
        (64, 0.0, "STRONG"),
        (8, 0.05, "STRONG"),
        (4, 0.02, "WEAK"),
        (3.999, 1.0, "INACTIVE"),
        (8, 0.049, "WEAK"),
    ],
)
def test_activity_boundaries(config: dict[str, object], pages: float, ratio: float, expected: str) -> None:
    assert classify_activity(pages, ratio, config) == expected


def test_equal_window_background_estimate(config: dict[str, object]) -> None:
    result = estimate_background_activity(
        baseline_referenced_pages=10,
        operation_referenced_pages=30,
        baseline_window_s=5,
        operation_window_s=5,
        operation_rss_kib=400,
        page_size_bytes=4096,
        config=config,
    )
    assert result["estimated_background_pages"] == 10
    assert result["estimated_excess_referenced_pages"] == 20
    assert result["estimation_method"] == "TIME_NORMALIZED_REFERENCED_HEURISTIC"


def test_unequal_window_scales_and_clamps_to_zero(config: dict[str, object]) -> None:
    result = estimate_background_activity(
        baseline_referenced_pages=10,
        operation_referenced_pages=3,
        baseline_window_s=5,
        operation_window_s=10,
        operation_rss_kib=100,
        page_size_bytes=4096,
        config=config,
    )
    assert result["estimated_background_pages"] == 20
    assert result["estimated_excess_referenced_pages"] == 0


@pytest.mark.parametrize(
    ("baseline", "operation", "expected"),
    [(5, 5, "OK"), (5, 15, "WINDOW_MISMATCH"), (5, 25, "SEVERE_WINDOW_MISMATCH"), (0.5, 5, "BASELINE_WINDOW_TOO_SHORT"), (5, 0.5, "OPERATION_WINDOW_TOO_SHORT")],
)
def test_window_quality(config: dict[str, object], baseline: float, operation: float, expected: str) -> None:
    assert window_quality(baseline, operation, config) == expected
