#!/usr/bin/env python3
"""Resolve stable WPS/CEF process roles from process snapshot evidence."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


BUNDLE = "cn.wps.office.hap"

PROCESS_ROLES = (
    "WPS_MAIN",
    "WPS_CEF_ZYGOTE",
    "WPS_CEF_GPU",
    "WPS_CEF_NETWORK",
    "WPS_CEF_RENDERER",
    "WPS_CLOUD_SERVICE",
    "WPS_LIBADAPTER",
    "WPS_OTHER",
)


def parse_proc_stat_starttime(text: str) -> int | None:
    """Return Linux `/proc/<pid>/stat` field 22 without parsing comm by spaces."""
    right_paren = text.rfind(")")
    left_paren = text.find("(")
    if left_paren <= 0 or right_paren <= left_paren:
        return None
    fields_from_state = text[right_paren + 1 :].strip().split()
    if len(fields_from_state) <= 19:
        return None
    try:
        value = int(fields_from_state[19])
    except ValueError:
        return None
    return value if value >= 0 else None


def _evidence(row: Mapping[str, Any]) -> str:
    values = (
        row.get("args", ""),
        row.get("cmdline", ""),
        row.get("comm", ""),
        row.get("exe_path", ""),
    )
    return " ".join(str(value) for value in values if value).lower()


def resolve_process_role(
    row: Mapping[str, Any],
    all_rows: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    """Classify one row using deterministic, most-specific-first rules."""
    del all_rows  # Reserved for PPID-aware rules after direct evidence.
    evidence = _evidence(row)

    if "--type=renderer" in evidence:
        return {"process_role": "WPS_CEF_RENDERER", "role_match_rule": "cef_renderer"}
    if "--type=gpu-process" in evidence:
        return {"process_role": "WPS_CEF_GPU", "role_match_rule": "cef_gpu"}
    if "--type=zygote" in evidence:
        return {"process_role": "WPS_CEF_ZYGOTE", "role_match_rule": "cef_zygote"}
    if (
        "networkservice" in evidence
        or "network_service" in evidence
        or "network service" in evidence
        or ("--type=utility" in evidence and "network" in evidence)
    ):
        return {"process_role": "WPS_CEF_NETWORK", "role_match_rule": "cef_network_service"}
    if "libadapter" in evidence:
        return {"process_role": "WPS_LIBADAPTER", "role_match_rule": "libadapter"}
    if "cloud" in evidence or "wps_service" in evidence or "wps-service" in evidence:
        return {"process_role": "WPS_CLOUD_SERVICE", "role_match_rule": "cloud_service"}
    if BUNDLE in evidence and "--type=" not in evidence:
        executable = str(row.get("exe_path", "")).lower()
        comm = str(row.get("comm", "")).lower()
        if "worker" not in evidence and "helper" not in evidence and (
            "wps" in executable or "wps" in comm or "bundle-name" in evidence
        ):
            return {"process_role": "WPS_MAIN", "role_match_rule": "main_bundle"}
    return {"process_role": "WPS_OTHER", "role_match_rule": "wps_other"}


def enrich_process_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return copied snapshot rows with normalized starttime and role evidence."""
    originals = [dict(row) for row in rows]
    enriched: list[dict[str, Any]] = []
    for row in originals:
        starttime = row.get("process_starttime")
        available = bool(row.get("starttime_available")) and isinstance(starttime, int)
        row["process_starttime"] = starttime if available else None
        row["starttime_available"] = available
        row.update(resolve_process_role(row, originals))
        enriched.append(row)
    return enriched
