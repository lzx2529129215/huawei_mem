#!/usr/bin/env python3
"""Run WPS setup plus the real 03_write_metadata baseline smoke."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wps_v6_session import Session, list_targets, find_hdc, parse_args  # noqa: E402


def main() -> int:
    targets = list_targets(find_hdc())
    if len(targets) != 1:
        print(f"BLOCKED: expected one HDC target, got {targets}", file=sys.stderr)
        return 2
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT / "hdc_out" / f"wps_stage_smoke_{stamp}"
    args = parse_args([
        "--target", targets[0],
        "--out", str(output),
        "--session-id", f"stage_smoke_{stamp}",
        "--no-build",
        "--baseline-window-s", "5.0",
    ])
    session: Session | None = None
    return_code = 2
    try:
        session = Session(args)
        session.verify_access()
        session.build_and_push()
        session.record_document_baseline()
        opened = session.open_stage(1)
        created = opened and session.measured_stage(
            2,
            "02_new_word",
            "新建 Word 文档（Smoke 前置）",
            "创建空白 Word 文档",
            session.new_word,
            5,
        )
        measured = created and session.measured_stage(
            3,
            "03_write_metadata",
            "写入元数据（baseline Smoke）",
            "写入真实 WPS 测试元数据",
            session.write_metadata,
            5,
        )
        session.close_wps(4, "close_final")
        return_code = 0 if measured else 1
        print(f"stage_smoke_output={output}")
        return return_code
    finally:
        if session is not None:
            try:
                session.write_metadata_file(return_code)
            finally:
                session.close_files()


if __name__ == "__main__":
    raise SystemExit(main())
