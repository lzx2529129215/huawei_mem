#!/usr/bin/env python3
"""Print a real WPS process-role snapshot for device smoke evidence."""

from __future__ import annotations

import json
import sys
import datetime as dt
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wps_v6_session import Device, find_hdc, list_targets, process_snapshot  # noqa: E402


def main() -> int:
    hdc = find_hdc()
    targets = list_targets(hdc)
    if len(targets) != 1:
        print(json.dumps({"status": "BLOCKED", "targets": targets}, ensure_ascii=False, indent=2))
        return 2
    rows = process_snapshot(Device(hdc, targets[0]))
    payload = {"status": "OK" if rows else "BLOCKED", "target": targets[0], "processes": rows}
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "hdc_out" / f"process_role_smoke_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "process_roles.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["output"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
