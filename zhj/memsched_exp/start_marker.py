from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write an exact monotonic launch marker, then exec an application")
    parser.add_argument("--marker", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    marker = Path(args.marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    value = {"monotonic_ns": time.monotonic_ns(), "pid": os.getpid(), "command": command}
    temporary = marker.with_name(marker.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, marker)
    os.execvp(command[0], command)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
