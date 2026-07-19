from __future__ import annotations

from operation_vma_mapping import exact_file_instance_key, semantic_file_key


def file_vma(*, start: int, inode: int, path: str = "/system/lib64/libwps.so") -> dict[str, object]:
    return {
        "start_address": start,
        "end_address": start + 0x4000,
        "file_offset_bytes": 0x2000,
        "file_offset_end_bytes": 0x6000,
        "dev_major": 8,
        "dev_minor": 1,
        "inode": inode,
        "permissions": "r-xp",
        "mapping_type": "SHARED_LIBRARY",
        "normalized_path": path,
        "path": path,
    }


def test_exact_key_survives_aslr_and_excludes_virtual_address() -> None:
    first = exact_file_instance_key(file_vma(start=0x1000, inode=99), "WPS_MAIN")
    second = exact_file_instance_key(file_vma(start=0x900000, inode=99), "WPS_MAIN")
    assert first == second
    assert "4096" not in first
    assert "9437184" not in first


def test_semantic_document_key_survives_inode_change() -> None:
    first_vma = file_vma(start=0x1000, inode=99, path="/Docs/Desktop/test-one.docx")
    second_vma = file_vma(start=0x8000, inode=100, path="/Docs/Desktop/test-two.docx")
    first_vma["mapping_type"] = "DOCUMENT_FILE"
    second_vma["mapping_type"] = "DOCUMENT_FILE"
    context = {"current_test_document": True}
    assert semantic_file_key(first_vma, "WPS_MAIN", context) == semantic_file_key(second_vma, "WPS_MAIN", context)


def test_semantic_key_does_not_replace_exact_identity() -> None:
    item = file_vma(start=0x1000, inode=99)
    assert exact_file_instance_key(item, "WPS_MAIN") != semantic_file_key(item, "WPS_MAIN", {})
