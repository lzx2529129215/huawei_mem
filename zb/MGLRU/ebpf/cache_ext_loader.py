#!/usr/bin/env python3
"""Build and run the libbpf cache_ext eBPF policy loader."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path


HIST_LEN = 4
BTF_VMLINUX = Path("/sys/kernel/btf/vmlinux")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_markov_csv() -> Path:
    return repo_root() / "zb" / "MGLRU" / "generated" / "cache_ext_markov_transition.csv"


def default_profile_csv() -> Path:
    return repo_root() / "zb" / "MGLRU" / "generated" / "cache_ext_page_profile.csv"


def expand_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def parse_markov_csv(path: Path, limit: int | None) -> dict[tuple[int, int, int, int, int], tuple[int, int]]:
    top1: dict[tuple[int, int, int, int, int], tuple[int, int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"app_id", "ctx0", "ctx1", "ctx2", "ctx3", "next_op", "count"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing fields: {', '.join(sorted(missing))}")

        for row in reader:
            key = (
                int(row["app_id"]),
                int(row["ctx0"]),
                int(row["ctx1"]),
                int(row["ctx2"]),
                int(row["ctx3"]),
            )
            next_op = int(row["next_op"])
            count = int(row["count"])
            old = top1.get(key)
            if old is None or count > old[1] or (count == old[1] and next_op < old[0]):
                top1[key] = (next_op, count)

    if limit is not None:
        return dict(list(top1.items())[:limit])
    return top1


def parse_profile_csv(path: Path) -> dict[tuple[int, int, int, int, int], tuple[int, int, int]]:
    profiles: dict[tuple[int, int, int, int, int], tuple[int, int, int]] = {}
    if not path.is_file() or path.stat().st_size == 0:
        print(
            "WARNING: profile CSV not found or empty; kernel debugfs profile hints will be empty.",
            file=sys.stderr,
        )
        return profiles

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "app_id",
            "op_id",
            "dev_major",
            "dev_minor",
            "ino",
            "index_start",
            "index_end",
            "priority",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing fields: {', '.join(sorted(missing))}")

        for row in reader:
            key = (
                int(row["app_id"]),
                int(row["op_id"]),
                int(row["dev_major"]),
                int(row["dev_minor"]),
                int(row["ino"]),
            )
            start = int(row["index_start"])
            end = int(row["index_end"])
            priority = int(row["priority"])
            if start > end:
                raise ValueError(f"{path}: index_start > index_end for key {key}")
            old = profiles.get(key)
            if old is None:
                profiles[key] = (start, end, priority)
            else:
                profiles[key] = (min(old[0], start), max(old[1], end), min(old[2], priority))

    if not profiles:
        print(
            "WARNING: profile CSV not found or empty; kernel debugfs profile hints will be empty.",
            file=sys.stderr,
        )
    return profiles


def require_tool(name: str) -> str:
    tool = shutil.which(name)
    if tool is None:
        raise RuntimeError(f"required tool not found in PATH: {name}")
    return tool


def run_checked(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"failed to run command: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        print("command failed:", file=sys.stderr)
        print(" ".join(cmd), file=sys.stderr)
        raise RuntimeError(f"command exited with status {exc.returncode}") from exc


def validate_bpf_inputs(bpf_dir: Path, kernel_src: Path, kernel_build: Path) -> None:
    policy_c = bpf_dir / "cache_ext_policy.bpf.c"
    common_h = bpf_dir / "cache_ext_bpf_common.h"
    c_loader = bpf_dir / "cache_ext_libbpf_loader.c"
    libbpf_a = kernel_src / "tools" / "lib" / "bpf" / "libbpf.a"

    for path, desc in (
        (policy_c, "BPF source"),
        (common_h, "BPF common header"),
        (c_loader, "libbpf loader source"),
    ):
        if not path.is_file():
            raise RuntimeError(f"Missing {desc}: {path}")

    if not (kernel_src / "include").is_dir():
        raise RuntimeError(f"Missing kernel source include directory: {kernel_src / 'include'}")
    if not (kernel_build / "include").is_dir():
        raise RuntimeError(f"Missing kernel build include directory: {kernel_build / 'include'}")
    if not libbpf_a.is_file():
        raise RuntimeError(
            "libbpf.a missing. Build with:\n"
            f"make -C {kernel_src / 'tools' / 'lib' / 'bpf'} -j$(nproc)"
        )


def ensure_vmlinux_header(bpf_dir: Path, bpftool: Path | None) -> None:
    target = bpf_dir / "vmlinux.h"
    if target.is_file():
        return

    hint_tool = str(bpftool) if bpftool is not None else "bpftool"
    hint = (
        "vmlinux.h missing. Generate with:\n"
        f"{hint_tool} btf dump file /sys/kernel/btf/vmlinux format c > {target}"
    )
    if bpftool is None:
        raise RuntimeError(hint)
    if not bpftool.is_file():
        raise RuntimeError(f"{hint}\n\nbpftool not found: {bpftool}")
    if not BTF_VMLINUX.is_file():
        raise RuntimeError(f"{hint}\n\nBTF file not found: {BTF_VMLINUX}")

    result = subprocess.run(
        [str(bpftool), "btf", "dump", "file", str(BTF_VMLINUX), "format", "c"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    target.write_text(result.stdout, encoding="utf-8")


def compile_bpf_object(bpf_dir: Path, kernel_src: Path, kernel_build: Path) -> Path:
    require_tool("clang")
    obj = bpf_dir / "cache_ext_policy.bpf.o"
    cmd = [
        "clang",
        "-O2",
        "-g",
        "-target",
        "bpf",
        "-D__TARGET_ARCH_x86",
        f"-I{bpf_dir}",
        f"-I{kernel_src / 'tools' / 'lib'}",
        f"-I{kernel_src / 'tools' / 'lib' / 'bpf'}",
        f"-I{kernel_src / 'include'}",
        f"-I{kernel_src / 'include' / 'uapi'}",
        f"-I{kernel_src / 'arch' / 'x86' / 'include'}",
        f"-I{kernel_src / 'arch' / 'x86' / 'include' / 'uapi'}",
        f"-I{kernel_build / 'include'}",
        f"-I{kernel_build / 'include' / 'generated'}",
        f"-I{kernel_build / 'include' / 'generated' / 'uapi'}",
        f"-I{kernel_build / 'arch' / 'x86' / 'include'}",
        f"-I{kernel_build / 'arch' / 'x86' / 'include' / 'generated'}",
        f"-I{kernel_build / 'arch' / 'x86' / 'include' / 'generated' / 'uapi'}",
        "-c",
        str(bpf_dir / "cache_ext_policy.bpf.c"),
        "-o",
        str(obj),
    ]
    print("clang command:")
    print(" ".join(cmd))
    run_checked(cmd)
    return obj


def compile_libbpf_loader(bpf_dir: Path, kernel_src: Path) -> Path:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        raise RuntimeError("required tool not found in PATH: cc or gcc")

    out = bpf_dir / "cache_ext_libbpf_loader"
    libbpf_a = kernel_src / "tools" / "lib" / "bpf" / "libbpf.a"
    cmd = [
        cc,
        "-O2",
        "-g",
        f"-I{bpf_dir}",
        f"-I{kernel_src / 'tools' / 'lib'}",
        f"-I{kernel_src / 'tools' / 'lib' / 'bpf'}",
        f"-I{kernel_src / 'tools' / 'include'}",
        f"-I{kernel_src / 'tools' / 'include' / 'uapi'}",
        f"-I{kernel_src / 'include' / 'uapi'}",
        f"-I{kernel_src / 'arch' / 'x86' / 'include' / 'uapi'}",
        str(bpf_dir / "cache_ext_libbpf_loader.c"),
        str(libbpf_a),
        "-lelf",
        "-lz",
        "-o",
        str(out),
    ]
    run_checked(cmd)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markov-csv", type=Path, default=default_markov_csv())
    parser.add_argument("--profile-csv", type=Path, default=default_profile_csv())
    parser.add_argument("--debugfs", type=Path, default=Path("/sys/kernel/debug/cache_ext"))
    parser.add_argument("--kernel-src", type=Path, help="Linux kernel source directory")
    parser.add_argument("--kernel-build", type=Path, help="Linux kernel build/output directory")
    parser.add_argument("--bpftool", type=Path, help="Path to bpftool binary, used only if vmlinux.h is missing")
    parser.add_argument("--app-id", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--set-history",
        type=int,
        nargs=HIST_LEN,
        metavar=("CTX0", "CTX1", "CTX2", "CTX3"),
        help="write a fixed 4-op history and keep the libbpf loader alive",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.markov_csv = expand_path(args.markov_csv)
    args.profile_csv = expand_path(args.profile_csv)
    args.debugfs = expand_path(args.debugfs)
    args.kernel_src = expand_path(args.kernel_src)
    args.kernel_build = expand_path(args.kernel_build)
    args.bpftool = expand_path(args.bpftool)

    if args.markov_csv is None or args.profile_csv is None or args.debugfs is None:
        raise RuntimeError("--markov-csv, --profile-csv, and --debugfs are required")

    if args.dry_run:
        markov = parse_markov_csv(args.markov_csv, args.limit)
        profiles = parse_profile_csv(args.profile_csv)
        print(f"markov top-1 entries: {len(markov)}")
        print(f"profile entries: {len(profiles)}")
        print("profile CSV will be synced to kernel debugfs hints by the libbpf loader")
        for idx, (key, val) in enumerate(markov.items()):
            if idx >= 5:
                break
            print(f"markov sample: key={key} next_op={val[0]} count={val[1]}")
        for idx, (key, val) in enumerate(profiles.items()):
            if idx >= 5:
                break
            print(f"profile sample: key={key} index={val[0]}-{val[1]} priority={val[2]}")
        if args.set_history:
            print(f"history sample: app={args.app_id} ops=" + " ".join(str(op) for op in args.set_history))
        return 0

    if args.kernel_src is None:
        raise RuntimeError("--kernel-src is required")
    if args.kernel_build is None:
        raise RuntimeError("--kernel-build is required")

    bpf_dir = Path(__file__).resolve().parent
    validate_bpf_inputs(bpf_dir, args.kernel_src, args.kernel_build)
    ensure_vmlinux_header(bpf_dir, args.bpftool)

    bpf_obj = compile_bpf_object(bpf_dir, args.kernel_src, args.kernel_build)
    loader = compile_libbpf_loader(bpf_dir, args.kernel_src)

    cmd = [
        str(loader),
        "--app-id",
        str(args.app_id),
        "--markov-csv",
        str(args.markov_csv),
        "--profile-csv",
        str(args.profile_csv),
        "--debugfs",
        str(args.debugfs),
        "--bpf-obj",
        str(bpf_obj),
    ]
    if args.limit is not None:
        cmd.extend(["--limit", str(args.limit)])
    if args.set_history:
        cmd.extend(["--set-history", *(str(op) for op in args.set_history)])

    return subprocess.call(cmd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
