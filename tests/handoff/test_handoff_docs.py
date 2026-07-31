from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
docs = ROOT / "docs" / "handoff"
required = [
    docs / "Linux-L0.2-工作交接.md",
    docs / "Linux-L0.2-快速复现.md",
    docs / "Linux-L0.2-故障排查.md",
    docs / "Linux-L0.2-文件与提交清单.md",
    docs / "Linux-L0.2-交接验证报告.md",
    docs / "checksums" / "linux617-source-archive.sha256",
    docs / "checksums" / "linux617-pristine-files.sha256",
    docs / "checksums" / "patches.sha256",
    docs / "checksums" / "reference-build.sha256",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    raise SystemExit("missing handoff files: " + ", ".join(missing))
for doc in required[:5]:
    text = doc.read_text()
    for ref in re.findall(r"(?:scripts/handoff|docs/handoff|patches)/[^`\s)]+", text):
        if ref.endswith(".sh") or ref.endswith(".patch"):
            if not (ROOT / ref).exists():
                raise SystemExit(f"broken handoff reference {ref} in {doc}")
print("handoff documentation references: PASS")
