#!/usr/bin/env bash
set -euo pipefail

PFN=${1:-2150528}

sudo env PFN="$PFN" python3 - <<'PY'
import os
import re
import struct

pfn = int(os.environ["PFN"], 0)

def unescape_lru_gen_path(path):
    def repl(match):
        return chr(int(match.group(1), 16))

    return re.sub(r"\\x([0-9a-fA-F]{2})", repl, path)

def cgroup_relative_path(path):
    root = "/sys/fs/cgroup"

    if path == root:
        return "/"
    if path.startswith(root + "/"):
        return path[len(root):]

    return path

def find_memcg_path(inode):
    for root, dirs, files in os.walk("/sys/fs/cgroup"):
        try:
            if os.stat(root).st_ino == inode:
                return root
        except PermissionError:
            pass

    return None

def find_mem_cgroup_id(memcg_path):
    rel_path = cgroup_relative_path(memcg_path)

    try:
        with open("/sys/kernel/debug/lru_gen", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("memcg"):
                    continue

                parts = line.rstrip("\n").split(None, 2)
                if len(parts) < 3:
                    continue

                memcg_id = parts[1]
                lru_path = unescape_lru_gen_path(parts[2])

                if lru_path == rel_path:
                    return memcg_id
    except FileNotFoundError:
        print("mem_cgroup_id: unavailable (/sys/kernel/debug/lru_gen not found)")
        return None
    except PermissionError:
        print("mem_cgroup_id: unavailable (permission denied reading /sys/kernel/debug/lru_gen)")
        return None

    return None

with open("/proc/kpagecgroup", "rb") as f:
    f.seek(pfn * 8)
    data = f.read(8)

if len(data) != 8:
    raise SystemExit("read /proc/kpagecgroup failed")

ino = struct.unpack("Q", data)[0]
print("pfn:", pfn)
print("memcg_inode:", ino)

if ino == 0:
    print("no memcg charge or unavailable")
    raise SystemExit(0)

memcg_path = find_memcg_path(ino)
if not memcg_path:
    print("memcg path not found under /sys/fs/cgroup")
    raise SystemExit(0)

print("memcg_path:", memcg_path)

memcg_id = find_mem_cgroup_id(memcg_path)
if memcg_id is None:
    print("mem_cgroup_id:", "not found in /sys/kernel/debug/lru_gen")
else:
    print("mem_cgroup_id:", memcg_id)
PY
