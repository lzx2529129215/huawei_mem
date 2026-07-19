from __future__ import annotations

import pytest

from process_role_resolver import (
    enrich_process_rows,
    parse_proc_stat_starttime,
    resolve_process_role,
)


def row(args: str, *, pid: str = "100", ppid: str = "1", comm: str = "wps") -> dict[str, object]:
    return {
        "pid": pid,
        "ppid": ppid,
        "args": args,
        "cmdline": args,
        "comm": comm,
        "exe_path": "/system/bin/wps",
        "process_starttime": 1234,
        "starttime_available": True,
    }


def test_parse_proc_stat_starttime_with_spaces_and_parentheses_in_comm() -> None:
    prefix = "42245 (WPS helper (GPU)) S"
    fields_4_to_21 = [str(value) for value in range(4, 22)]
    text = " ".join([prefix, *fields_4_to_21, "987654", "0", "0"])
    assert parse_proc_stat_starttime(text) == 987654


@pytest.mark.parametrize("text", ["", "12 broken", "12 (comm) S 1 2"])
def test_parse_proc_stat_starttime_returns_none_when_unavailable(text: str) -> None:
    assert parse_proc_stat_starttime(text) is None


@pytest.mark.parametrize(
    ("args", "expected_role", "expected_rule"),
    [
        ("/system/bin/wps --bundle-name cn.wps.office.hap", "WPS_MAIN", "main_bundle"),
        ("wps --type=renderer --bundle-name cn.wps.office.hap", "WPS_CEF_RENDERER", "cef_renderer"),
        ("wps --type=gpu-process --bundle-name cn.wps.office.hap", "WPS_CEF_GPU", "cef_gpu"),
        ("wps --type=zygote --bundle-name cn.wps.office.hap", "WPS_CEF_ZYGOTE", "cef_zygote"),
        (
            "wps --type=utility --utility-sub-type=network.mojom.NetworkService --bundle-name cn.wps.office.hap",
            "WPS_CEF_NETWORK",
            "cef_network_service",
        ),
        ("/system/bin/wps_libadapter cn.wps.office.hap", "WPS_LIBADAPTER", "libadapter"),
        ("/system/bin/wps_cloud_service cn.wps.office.hap", "WPS_CLOUD_SERVICE", "cloud_service"),
        ("/system/bin/wps_worker cn.wps.office.hap", "WPS_OTHER", "wps_other"),
    ],
)
def test_resolve_process_role(args: str, expected_role: str, expected_rule: str) -> None:
    resolved = resolve_process_role(row(args), [])
    assert resolved["process_role"] == expected_role
    assert resolved["role_match_rule"] == expected_rule


def test_renderer_precedence_over_main_bundle_marker() -> None:
    resolved = resolve_process_role(
        row("/system/bin/wps --bundle-name cn.wps.office.hap --type=renderer"),
        [],
    )
    assert resolved["process_role"] == "WPS_CEF_RENDERER"


def test_enrich_process_rows_marks_unavailable_starttime() -> None:
    original = row("/system/bin/wps --bundle-name cn.wps.office.hap")
    original["process_starttime"] = None
    original["starttime_available"] = False
    enriched = enrich_process_rows([original])
    assert enriched[0]["process_starttime"] is None
    assert enriched[0]["starttime_available"] is False
    assert enriched[0]["process_role"] == "WPS_MAIN"
