from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mem_analyze-v6.c"


def run_bash(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["wsl.exe", "--exec", "bash", "-lc", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=60,
        )
    except FileNotFoundError:
        pytest.skip("WSL bash is unavailable")
    if check and result.returncode != 0:
        pytest.fail(f"bash failed ({result.returncode}):\n{result.stdout}")
    return result


def wsl_path(path: Path) -> str:
    result = run_bash(f"wslpath -a {shlex.quote(str(path))}")
    clean = result.stdout.replace("\x00", "")
    candidates = [line.strip() for line in clean.splitlines() if line.strip().startswith("/")]
    assert candidates, clean
    return candidates[-1]


def test_json_escape_is_valid_and_preserves_utf8(tmp_path: Path) -> None:
    source = wsl_path(SOURCE)
    harness = tmp_path / "json_escape_harness.c"
    binary = tmp_path / "json_escape_harness"
    output = tmp_path / "escaped.json"
    harness.write_text(
        "#define main mem_analyze_main\n"
        f'#include "{source}"\n'
        "#undef main\n"
        "int main(void) {\n"
        '  json_write_string(stdout, "quote=\\\" slash=\\\\ tab=\\t newline=\\n return=\\r control=" "\\x01" " 中文");\n'
        "  return 0;\n"
        "}\n",
        encoding="utf-8",
    )
    result = run_bash(
        f"cc -std=c11 -Wall -Wextra -Werror -o {shlex.quote(wsl_path(binary))} "
        f"{shlex.quote(wsl_path(harness))} && {shlex.quote(wsl_path(binary))} > {shlex.quote(wsl_path(output))}"
    )
    assert result.returncode == 0
    decoded = json.loads(output.read_text(encoding="utf-8"))
    assert decoded == 'quote=" slash=\\ tab=\t newline=\n return=\r control=\x01 中文'


def test_collector_emits_one_valid_json_object_for_every_vma(tmp_path: Path) -> None:
    binary = tmp_path / "mem_analyze-v6"
    markdown = tmp_path / "report.md"
    jsonl = tmp_path / "report.jsonl"
    script = "\n".join(
        [
            f"cc -std=c11 -Wall -Wextra -Werror -o {shlex.quote(wsl_path(binary))} {shlex.quote(wsl_path(SOURCE))}",
            "sleep 30 & target=$!",
            "trap 'kill $target 2>/dev/null || true' EXIT",
            (
                f"{shlex.quote(wsl_path(binary))} $target -o {shlex.quote(wsl_path(markdown))} "
                f"--jsonl-output {shlex.quote(wsl_path(jsonl))} --with-vma"
            ),
        ]
    )
    result = run_bash(script)
    records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    markdown_text = markdown.read_text(encoding="utf-8")
    vma_count = int(re.search(r"\| VMA 数 \| `(\d+)` \|", markdown_text).group(1))

    assert len(records) == vma_count
    assert records
    assert any(record["referenced_kib"] == 0 for record in records)
    assert "REPORT_MD=" in result.stdout
    assert "REPORT_JSONL=" in result.stdout
    required = {
        "schema_version",
        "record_type",
        "pid",
        "process_name",
        "exe_path",
        "page_size_bytes",
        "start_address",
        "end_address",
        "start_address_hex",
        "end_address_hex",
        "address_size_bytes",
        "permissions",
        "file_offset_bytes",
        "file_offset_end_bytes",
        "device",
        "dev_major",
        "dev_minor",
        "inode",
        "path",
        "normalized_path",
        "path_deleted",
        "segment",
        "mapping_type",
        "size_kib",
        "rss_kib",
        "pss_kib",
        "referenced_kib",
        "referenced_pages",
        "swap_kib",
        "referenced_size_ratio",
        "referenced_rss_ratio",
        "sample_wall_time",
        "sample_monotonic_ns",
    }
    assert required <= records[0].keys()
    assert all(record["schema_version"] == "homeny.vma.v1" for record in records)
    assert all(record["record_type"] == "vma" for record in records)
    assert all(0 <= record["referenced_size_ratio"] <= 1 for record in records if record["referenced_size_ratio"] is not None)
    assert all(0 <= record["referenced_rss_ratio"] <= 1 for record in records if record["referenced_rss_ratio"] is not None)


def test_multi_pid_outputs_preserve_markdown_and_jsonl_extensions(tmp_path: Path) -> None:
    binary = tmp_path / "mem_analyze-v6"
    markdown = tmp_path / "multi.md"
    jsonl = tmp_path / "multi.jsonl"
    script = "\n".join(
        [
            f"cc -std=c11 -Wall -Wextra -Werror -o {shlex.quote(wsl_path(binary))} {shlex.quote(wsl_path(SOURCE))}",
            "sleep 30 & first=$!",
            "sleep 30 & second=$!",
            "trap 'kill $first $second 2>/dev/null || true' EXIT",
            (
                f"{shlex.quote(wsl_path(binary))} $first $second -o {shlex.quote(wsl_path(markdown))} "
                f"--jsonl-output {shlex.quote(wsl_path(jsonl))} --with-vma"
            ),
            f"test -s {shlex.quote(wsl_path(tmp_path))}/multi_pid_${{first}}.md",
            f"test -s {shlex.quote(wsl_path(tmp_path))}/multi_pid_${{second}}.md",
            f"test -s {shlex.quote(wsl_path(tmp_path))}/multi_pid_${{first}}.jsonl",
            f"test -s {shlex.quote(wsl_path(tmp_path))}/multi_pid_${{second}}.jsonl",
        ]
    )
    result = run_bash(script)
    assert result.returncode == 0
