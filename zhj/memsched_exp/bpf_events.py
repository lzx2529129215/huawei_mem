from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def parse_events(
    path: str | Path,
    stderr_path: str | Path | None = None,
    window_start_ns: int | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_comm: dict[str, Counter[str]] = defaultdict(Counter)
    duration_ns = 0
    parse_errors = 0
    open_reclaims: Counter[int] = Counter()
    pairing_errors: list[str] = []
    with Path(path).open(encoding="utf-8") as stream:
        for raw in stream:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            event_type = str(event.get("type", "unknown"))
            if window_start_ns is not None and event_type not in {"collector_start", "collector_stop"}:
                timestamp = int(event.get("ts_ns", 0))
                window_end_ns = window_start_ns + int((duration_s or 0) * 1e9)
                if timestamp < window_start_ns or timestamp >= window_end_ns:
                    continue
            counts[event_type] += 1
            by_comm[str(event.get("comm", "unknown"))][event_type] += 1
            if event_type == "direct_reclaim_begin":
                tid = int(event.get("tid", -1))
                if open_reclaims[tid]:
                    pairing_errors.append(f"nested direct reclaim begin for tid {tid}")
                open_reclaims[tid] += 1
            if event_type == "direct_reclaim_end":
                tid = int(event.get("tid", -1))
                if open_reclaims[tid] == 0:
                    pairing_errors.append(f"direct reclaim end without begin for tid {tid}")
                else:
                    open_reclaims[tid] -= 1
                duration_ns += int(event.get("duration_ns", 0))
    begin_count = counts["direct_reclaim_begin"]
    end_count = counts["direct_reclaim_end"]
    invalid_reasons: list[str] = []
    if counts["collector_start"] != 1:
        invalid_reasons.append(f"expected one collector_start event, observed {counts['collector_start']}")
    if counts["collector_stop"] != 1:
        invalid_reasons.append(f"expected one collector_stop event, observed {counts['collector_stop']}")
    if begin_count != end_count:
        invalid_reasons.append(f"direct reclaim begin/end mismatch: {begin_count}/{end_count}")
    for tid, count in open_reclaims.items():
        if count:
            pairing_errors.append(f"{count} direct reclaim begin event(s) left open for tid {tid}")
    invalid_reasons.extend(pairing_errors)
    if parse_errors:
        invalid_reasons.append(f"JSON parse errors: {parse_errors}")
    lost_events_detected = False
    stderr_excerpt: list[str] = []
    if stderr_path is not None and Path(stderr_path).exists():
        stderr = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
        lost_pattern = re.compile(r"(?:lost|dropped)\s+\d*\s*(?:event|record|sample)", re.IGNORECASE)
        lost_events_detected = bool(lost_pattern.search(stderr))
        if lost_events_detected:
            invalid_reasons.append("bpftrace reported lost or dropped events")
        stderr_excerpt = [line for line in stderr.splitlines() if line.strip()][-20:]
    return {
        "valid": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "event_counts": dict(counts),
        "direct_reclaim_count": begin_count if not invalid_reasons else None,
        "direct_reclaim_total_duration_ms": duration_ns / 1e6,
        "kswapd_wake_count": counts["kswapd_wake"],
        "oom_mark_victim_count": counts["oom_mark_victim"],
        "by_comm": {comm: dict(counter) for comm, counter in sorted(by_comm.items())},
        "parse_errors": parse_errors,
        "pairing_errors": pairing_errors,
        "lost_events_detected": lost_events_detected,
        "stderr_excerpt": stderr_excerpt,
        "window_start_ns": window_start_ns,
        "window_duration_s": duration_s,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stderr")
    parser.add_argument("--start-file")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args(argv)
    start_ns = None
    if args.start_file:
        marker = json.loads(Path(args.start_file).read_text(encoding="utf-8"))
        start_ns = int(marker["monotonic_ns"])
    result = parse_events(args.input, args.stderr, start_ns, args.duration)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
