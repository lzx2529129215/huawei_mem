#!/usr/bin/env bash
set -euo pipefail

HANDOFF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HANDOFF_DIR/../.." && pwd)
readonly HANDOFF_DIR ROOT

LINUX_VERSION=6.17
LINUX_TAG=v6.17
LINUX_COMMIT=e5f0a698b34ed76002dc5cff3804a61c80233a7a
LINUX_ARCHIVE=linux-6.17.tar.xz
LINUX_URL=https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.17.tar.xz
LINUX_ARCHIVE_SHA256=9b607166a1c999d8326098121222feb080a20a3253975fcdfa2de96ba7f757a7

log() { printf '[handoff] %s\n' "$*"; }
warn() { printf '[handoff][WARN] %s\n' "$*" >&2; }
die() { printf '[handoff][ERROR] %s\n' "$*" >&2; exit 1; }
usage_header() { echo 'Linux L0.2 cross-device handoff helper.'; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
sha256_file() { sha256sum -- "$1" | awk '{print $1}'; }
absolute_path() { realpath -m -- "$1"; }

verify_sha256() {
    local file=$1 expected=$2 actual
    [[ -f "$file" ]] || die "file not found for SHA256 verification: $file"
    actual=$(sha256_file "$file")
    [[ "$actual" == "$expected" ]] || die "SHA256 mismatch for $file: expected $expected, got $actual"
}

require_empty_or_absent() {
    local dir=$1
    if [[ -e "$dir" && ! -d "$dir" ]]; then die "target exists and is not a directory: $dir"; fi
    if [[ -d "$dir" ]] && [[ -n "$(find "$dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        die "target must be absent or empty; refusing non-empty directory: $dir"
    fi
}

require_safe_generated_dir() {
    local dir=$1
    [[ "$dir" != / && "$dir" != "$ROOT" && "$dir" != "$ROOT/Linux6.17" ]] ||
        die "refusing broad or protected generated path: $dir"
}

cpu_jobs() {
    local n mem
    n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
    mem=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
    if (( mem < 6144 )); then echo 2; elif (( n < 4 )); then echo "$n"; else echo 4; fi
}

kernelrelease() { make -s -C "$1" O="$2" kernelrelease; }

manifest_line() {
    local root=$1 path=$2 mode hash target
    mode=$(stat -c '%a' -- "$root/$path")
    [[ ${#mode} -eq 3 ]] && mode="0$mode"
    if [[ -L "$root/$path" ]]; then
        target=$(readlink -- "$root/$path")
        hash=$(printf '%s' "$target" | sha256sum | awk '{print $1}')
        printf '120000 %s %s LINK=%s\n' "$path" "$hash" "$target"
    else
        hash=$(sha256_file "$root/$path")
        printf '%s %s %s\n' "$mode" "$path" "$hash"
    fi
}

write_source_manifest() {
    local root=$1 output=$2
    python3 - "$root" "$output" <<'PY'
import hashlib
import os
import stat
import sys

root, output = sys.argv[1:]
rows = []
for base, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
        path = os.path.join(base, name)
        if not os.path.isfile(path) and not os.path.islink(path):
            continue
        rel = os.path.relpath(path, root)
        file_stat = os.lstat(path)
        if stat.S_ISLNK(file_stat.st_mode):
            target = os.readlink(path)
            digest = hashlib.sha256(target.encode()).hexdigest()
            rows.append(f"120000 {rel} {digest} LINK={target}")
        else:
            digest = hashlib.sha256()
            with open(path, "rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            rows.append(f"{stat.S_IMODE(file_stat.st_mode):04o} {rel} {digest.hexdigest()}")
with open(output, "w", encoding="utf-8") as destination:
    destination.write("\n".join(sorted(set(rows))) + "\n")
PY
}

verify_source_manifest() {
    local root=$1 manifest=$2 generated
    [[ -d "$root" ]] || die "source directory not found: $root"
    [[ -f "$manifest" ]] || die "pristine manifest not found: $manifest"
    generated=$(mktemp)
    write_source_manifest "$root" "$generated"
    if ! cmp -s "$manifest" "$generated"; then
        diff -u "$manifest" "$generated" | head -80 >&2 || true
        rm -f -- "$generated"
        die "source tree does not match pristine manifest"
    fi
    rm -f -- "$generated"
}

manifest_path() { printf '%s/docs/handoff/checksums/linux617-pristine-files.sha256\n' "$ROOT"; }
patch_path() {
    case "$1" in
        0002) printf '%s/patches/0002-linux617-myself-kswapd-l01.patch\n' "$ROOT";;
        0003) printf '%s/patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch\n' "$ROOT";;
        *) die "unknown patch: $1";;
    esac
}
