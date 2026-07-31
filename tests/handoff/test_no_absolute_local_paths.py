from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
needle = "/" + "home/"
for base in (ROOT / "scripts" / "handoff", ROOT / "tests" / "handoff"):
    for path in base.rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".py"} and needle in path.read_text(errors="replace"):
            raise SystemExit(f"absolute local path found in {path}")
print("handoff scripts/tests contain no absolute local paths: PASS")
