from __future__ import annotations

from operation_vma_mapping import anonymous_auxiliary_feature


def test_anonymous_auxiliary_key_excludes_runtime_address_and_pid() -> None:
    vma = {
        "pid": 42245,
        "start_address": 0xABC000,
        "end_address": 0xABC000 + 1024 * 1024,
        "address_size_bytes": 1024 * 1024,
        "permissions": "rw-p",
        "mapping_type": "NAMED_ANON",
        "segment": "native heap",
        "path": "[anon:libc_malloc]",
        "normalized_path": "[anon:libc_malloc]",
    }
    feature = anonymous_auxiliary_feature(vma, "WPS_CEF_RENDERER", "cn.wps.office.hap")
    assert "42245" not in feature["anonymous_auxiliary_key"]
    assert str(0xABC000) not in feature["anonymous_auxiliary_key"]
    assert feature["usage"] == "OPERATION_RECOGNITION_AUXILIARY"
    assert feature["long_term_page_mapping"] is False
    assert feature["protection_eligible"] is False
    assert feature["prefetch_eligible"] is False
    assert feature["runtime_instance_only_address"] is True
    assert feature["vma_size_bucket"] == "1-4MiB"
