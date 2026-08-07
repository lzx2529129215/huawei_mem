from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .frames import analyze_frame_times
from .metrics import summarize
from .snapshot import host_metadata, take_snapshot


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    cgroup = Path(args.cgroup) if args.cgroup else None
    extra_metadata = {}
    if args.metadata_file:
        extra_metadata = json.loads(Path(args.metadata_file).read_text(encoding="utf-8"))
    metadata = {
        **host_metadata(output),
        "name": args.name,
        "requested_duration_s": args.duration,
        "sample_interval_s": args.interval,
        "cache_state": args.cache_state,
        "scenario": args.scenario,
        "experiment": extra_metadata,
    }
    _write_json(output / "metadata.json", metadata)

    if args.start_file:
        marker = Path(args.start_file)
        deadline = time.monotonic() + args.start_timeout
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not marker.exists():
            metadata["valid"] = False
            metadata["invalid_reason"] = "collection start marker was not observed"
            _write_json(output / "metadata.json", metadata)
            return 6
        metadata["start_marker"] = str(marker)
        metadata["valid"] = True
        _write_json(output / "metadata.json", metadata)

    before = take_snapshot(Path(args.proc_root), cgroup).to_dict()
    _write_json(output / "before.json", before)
    deadline = time.monotonic() + args.duration
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file:
        stop_file.unlink(missing_ok=True)
    with (output / "samples.jsonl").open("w", encoding="utf-8") as samples:
        while True:
            snap = take_snapshot(Path(args.proc_root), cgroup).to_dict()
            samples.write(json.dumps(snap, ensure_ascii=False) + "\n")
            samples.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (stop_file is not None and stop_file.exists()):
                break
            time.sleep(min(args.interval, remaining))
    after = take_snapshot(Path(args.proc_root), cgroup).to_dict()
    _write_json(output / "after.json", after)
    _write_json(output / "summary.json", summarize(before, after, metadata["cpu_count"]))
    print(output / "summary.json")
    return 0


def analyze(args: argparse.Namespace) -> int:
    run = Path(args.run)
    before = json.loads((run / "before.json").read_text(encoding="utf-8"))
    after = json.loads((run / "after.json").read_text(encoding="utf-8"))
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    summary = summarize(before, after, int(metadata.get("cpu_count", 1)))
    _write_json(run / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def frames(args: argparse.Namespace) -> int:
    result = analyze_frame_times(args.csv, args.budget_ms, args.window_start_ns, args.window_end_ns)
    if args.output:
        _write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memsched-exp")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_p = sub.add_parser("collect", help="collect system and optional cgroup metrics")
    collect_p.add_argument("--name", required=True)
    collect_p.add_argument("--duration", type=float, required=True)
    collect_p.add_argument("--interval", type=float, default=1.0)
    collect_p.add_argument("--output", required=True)
    collect_p.add_argument("--cgroup", help="absolute cgroup v2 path")
    collect_p.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    collect_p.add_argument("--cache-state", default="unspecified", choices=("unspecified", "process-cold", "strict-cold", "warm"))
    collect_p.add_argument("--scenario")
    collect_p.add_argument("--metadata-file")
    collect_p.add_argument("--start-file", help="wait for this marker before taking the before snapshot")
    collect_p.add_argument("--start-timeout", type=float, default=60.0)
    collect_p.add_argument("--stop-file", help="finish early and take the after snapshot when this marker appears")
    collect_p.set_defaults(func=collect)

    analyze_p = sub.add_parser("analyze", help="recompute a run summary")
    analyze_p.add_argument("--run", required=True)
    analyze_p.set_defaults(func=analyze)

    frames_p = sub.add_parser("frames", help="analyze frame timestamp/duration CSV")
    frames_p.add_argument("--csv", required=True)
    frames_p.add_argument("--budget-ms", type=float, default=16.7)
    frames_p.add_argument("--output")
    frames_p.add_argument("--window-start-ns", type=int)
    frames_p.add_argument("--window-end-ns", type=int)
    frames_p.set_defaults(func=frames)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
