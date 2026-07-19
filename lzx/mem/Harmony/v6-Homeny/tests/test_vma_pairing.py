from __future__ import annotations

from operation_vma_mapping import (
    map_operation_stage,
    pair_anonymous_vmas,
    pair_file_vmas,
    pair_processes,
)


def process(pid: int, starttime: int | None) -> dict[str, object]:
    return {
        "pid": str(pid),
        "process_starttime": starttime,
        "starttime_available": starttime is not None,
        "process_role": "WPS_MAIN",
    }


def vma(
    *,
    pid: int = 10,
    start: int = 0x1000,
    end: int = 0x2000,
    offset: int = 0,
    inode: int = 20,
    mapping_type: str = "FILE",
    path: str = "/tmp/file.bin",
    referenced_pages: int = 8,
) -> dict[str, object]:
    return {
        "pid": pid,
        "start_address": start,
        "end_address": end,
        "address_size_bytes": end - start,
        "file_offset_bytes": offset,
        "file_offset_end_bytes": offset + end - start,
        "device": "08:01",
        "dev_major": 8,
        "dev_minor": 1,
        "inode": inode,
        "permissions": "rw-p",
        "path": path,
        "normalized_path": path,
        "mapping_type": mapping_type,
        "segment": "FilePage other" if mapping_type == "FILE" else "AnonPage other",
        "size_kib": (end - start) // 1024,
        "rss_kib": (end - start) // 1024,
        "referenced_kib": referenced_pages * 4,
        "referenced_pages": referenced_pages,
        "page_size_bytes": 4096,
    }


def test_process_pairing_handles_reuse_pid_only_new_and_exit() -> None:
    result = pair_processes(
        [process(1, 100), process(2, None), process(3, 300), process(5, 500)],
        [process(1, 101), process(2, None), process(4, 400), process(5, 500)],
    )
    assert [item["quality"] for item in result["pairs"]] == ["PID_ONLY_MATCH", "OK"]
    assert [item["operation"]["pid"] for item in result["new_processes"]] == ["4"]
    assert [item["baseline"]["pid"] for item in result["exited_processes"]] == ["3"]
    assert [item["operation"]["pid"] for item in result["pid_reused"]] == ["1"]


def test_file_pairing_uses_offset_not_virtual_address() -> None:
    baseline = vma(start=0x1000, end=0x3000, offset=0, referenced_pages=4)
    operation = vma(start=0x900000, end=0x902000, offset=0, referenced_pages=12)
    result = pair_file_vmas([baseline], [operation])
    assert len(result["paired"]) == 1
    assert result["paired"][0]["vma_match_quality"] == "FILE_OFFSET_OVERLAP_MATCH"
    assert result["paired"][0]["allocated_baseline_referenced_pages"] == 4


def test_file_split_distributes_baseline_without_duplicate_deduction() -> None:
    baseline = vma(start=0x1000, end=0x5000, offset=0, referenced_pages=16)
    operations = [
        vma(start=0xA000, end=0xC000, offset=0, referenced_pages=10),
        vma(start=0xD000, end=0xF000, offset=0x2000, referenced_pages=10),
    ]
    result = pair_file_vmas([baseline], operations)
    allocations = [item["allocated_baseline_referenced_pages"] for item in result["paired"]]
    assert allocations == [8, 8]
    assert sum(allocations) == 16
    assert {item["vma_match_quality"] for item in result["paired"]} == {"VMA_SPLIT_MERGE_APPROXIMATION"}


def test_file_merge_preserves_all_baseline_contributions() -> None:
    baselines = [
        vma(start=0x1000, end=0x3000, offset=0, referenced_pages=4),
        vma(start=0x4000, end=0x6000, offset=0x2000, referenced_pages=6),
    ]
    operation = vma(start=0xA000, end=0xE000, offset=0, referenced_pages=20)
    result = pair_file_vmas(baselines, [operation])
    assert result["paired"][0]["allocated_baseline_referenced_pages"] == 10
    assert result["paired"][0]["baseline_vma_count"] == 2
    assert result["paired"][0]["vma_match_quality"] == "VMA_SPLIT_MERGE_APPROXIMATION"


def test_anonymous_pairing_uses_address_overlap_within_process_lifetime() -> None:
    baseline = vma(
        start=0x1000,
        end=0x5000,
        inode=0,
        mapping_type="ANON_OTHER",
        path="",
        referenced_pages=5,
    )
    operation = vma(
        start=0x3000,
        end=0x7000,
        inode=0,
        mapping_type="ANON_OTHER",
        path="",
        referenced_pages=9,
    )
    result = pair_anonymous_vmas([baseline], [operation])
    assert result["paired"][0]["vma_match_quality"] == "ANON_ADDRESS_OVERLAP_MATCH"
    assert result["paired"][0]["virtual_overlap_bytes"] == 0x2000


def test_pid_only_match_propagates_to_activity_quality(config: dict[str, object]) -> None:
    baseline_process = process(10, None)
    operation_process = process(10, None)
    baseline_vma = vma(pid=10, referenced_pages=4)
    operation_vma = vma(pid=10, start=0x900000, end=0x901000, referenced_pages=12)
    result = map_operation_stage(
        stage="03_write_metadata",
        baseline_processes=[baseline_process],
        operation_processes=[operation_process],
        baseline_vmas=[baseline_vma],
        operation_vmas=[operation_vma],
        baseline_window_s=5,
        operation_window_s=5,
        app_id="cn.wps.office.hap",
        config=config,
    )
    sample = result["file_samples"][0]
    assert sample["process_match_quality"] == "PID_ONLY_MATCH"
    assert sample["activity_quality"] == "PID_ONLY_MATCH"
