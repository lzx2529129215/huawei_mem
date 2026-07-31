#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source_dir="$ROOT/work/linux-6.17"; build_dir="$ROOT/builds/linux-6.17-l02"; cache_dir="$ROOT/../linux-l02-source-cache"; config_args=(); jobs=""
while (($#)); do
    case "$1" in
        --help) usage_header; echo "Usage: $0 [--source-dir DIR] [--build-dir DIR] [--config FILE|--defconfig] [--lru-gen y|n] [--disable-btf] [--jobs N] [--cache-dir DIR]"; exit 0;;
        --source-dir) source_dir=$2; shift 2;; --build-dir) build_dir=$2; shift 2;; --config) config_args+=(--config "$2"); shift 2;; --defconfig) config_args+=(--defconfig); shift;; --lru-gen) config_args+=(--lru-gen "$2"); shift 2;; --disable-btf) config_args+=(--disable-btf); shift;; --jobs) jobs=$2; shift 2;; --cache-dir) cache_dir=$2; shift 2;; *) die "unknown argument: $1";;
    esac
done
source_dir=$(absolute_path "$source_dir"); build_dir=$(absolute_path "$build_dir"); cache_dir=$(absolute_path "$cache_dir")
"$HANDOFF_DIR/check_environment.sh"; "$HANDOFF_DIR/fetch_linux617_source.sh" --source-dir "$source_dir" --cache-dir "$cache_dir"; "$HANDOFF_DIR/apply_linux_l02_patches.sh" --source-dir "$source_dir"
if ((${#config_args[@]})); then "$HANDOFF_DIR/configure_linux_l02.sh" --source-dir "$source_dir" --build-dir "$build_dir" "${config_args[@]}"; else "$HANDOFF_DIR/configure_linux_l02.sh" --source-dir "$source_dir" --build-dir "$build_dir"; fi
if [[ -n "$jobs" ]]; then "$HANDOFF_DIR/build_linux_l02.sh" --source-dir "$source_dir" --build-dir "$build_dir" --jobs "$jobs"; else "$HANDOFF_DIR/build_linux_l02.sh" --source-dir "$source_dir" --build-dir "$build_dir"; fi
"$HANDOFF_DIR/verify_linux_l02_build.sh" --source-dir "$source_dir" --build-dir "$build_dir"
echo 'Reproduction complete. No installation was performed.'
