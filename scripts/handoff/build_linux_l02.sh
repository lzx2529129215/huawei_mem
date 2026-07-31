#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source_dir="$ROOT/work/linux-6.17"; build_dir="$ROOT/builds/linux-6.17-l02"; jobs="$(cpu_jobs)"
while (($#)); do case "$1" in --help) usage_header; echo "Usage: $0 [--source-dir DIR] [--build-dir DIR] [--jobs N]"; exit 0;; --source-dir) source_dir=$2; shift 2;; --build-dir) build_dir=$2; shift 2;; --jobs) jobs=$2; shift 2;; *) die "unknown argument: $1";; esac; done
source_dir=$(absolute_path "$source_dir"); build_dir=$(absolute_path "$build_dir")
[[ -f "$build_dir/.config" ]] || die 'missing configured build; run configure_linux_l02.sh first'; require_safe_generated_dir "$build_dir"
log "building with jobs=$jobs"; start=$(date +%s); logfile="$build_dir/build.log"
{ make -C "$source_dir" O="$build_dir" olddefconfig prepare modules_prepare; make -C "$source_dir" O="$build_dir" -j"$jobs" bzImage modules; } 2>&1 | tee "$logfile"
release=$(kernelrelease "$source_dir" "$build_dir"); elapsed=$(( $(date +%s) - start )); printf 'kernelrelease=%s\nsource=%s\nbuild=%s\njobs=%s\nduration_seconds=%s\n' "$release" "$source_dir" "$build_dir" "$jobs" "$elapsed" > "$build_dir/BUILD-METADATA.txt"
sha256sum "$build_dir/arch/x86/boot/bzImage" "$build_dir/vmlinux" "$build_dir/System.map" "$build_dir/Module.symvers" > "$build_dir/SHA256SUMS"; log "build PASS: $release in ${elapsed}s"
