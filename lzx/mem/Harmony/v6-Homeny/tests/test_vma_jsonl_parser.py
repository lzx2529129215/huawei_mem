from __future__ import annotations

import json
from pathlib import Path

import pytest

from operation_vma_mapping import VmaJsonError, load_vma_jsonl


def record(path: str, *, deleted: bool = False, ratio: float | None = 0.5) -> dict[str, object]:
    return {
        "schema_version": "homeny.vma.v1",
        "record_type": "vma",
        "pid": 10,
        "page_size_bytes": 4096,
        "start_address": 4096,
        "end_address": 8192,
        "address_size_bytes": 4096,
        "permissions": "rw-p",
        "file_offset_bytes": 0,
        "file_offset_end_bytes": 4096,
        "device": "00:00",
        "dev_major": 0,
        "dev_minor": 0,
        "inode": 0,
        "path": path + (" (deleted)" if deleted else ""),
        "normalized_path": path,
        "path_deleted": deleted,
        "segment": "AnonPage other",
        "mapping_type": "ANON_OTHER",
        "size_kib": 4,
        "rss_kib": 4,
        "referenced_kib": 2,
        "referenced_pages": 1,
        "referenced_size_ratio": ratio,
        "referenced_rss_ratio": ratio,
    }


def write(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items), encoding="utf-8")


def test_parser_preserves_chinese_deleted_and_empty_paths(tmp_path: Path) -> None:
    source = tmp_path / "sample.jsonl"
    write(source, [record("/文档/测试.docx", deleted=True), record("")])
    parsed = load_vma_jsonl([source])
    assert parsed[0]["normalized_path"] == "/文档/测试.docx"
    assert parsed[0]["path_deleted"] is True
    assert parsed[1]["path"] == ""
    assert parsed[1]["inode"] == 0


def test_parser_rejects_ratio_outside_zero_to_one(tmp_path: Path) -> None:
    source = tmp_path / "bad.jsonl"
    write(source, [record("", ratio=1.2)])
    with pytest.raises(VmaJsonError, match="ratio"):
        load_vma_jsonl([source])
