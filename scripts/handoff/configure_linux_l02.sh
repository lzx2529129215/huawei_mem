#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source_dir="$ROOT/work/linux-6.17"; build_dir="$ROOT/builds/linux-6.17-l02"; config=""; defconfig=0; lru_gen=retain; disable_btf=0
while (($#)); do
    case "$1" in
        --help) usage_header; echo "Usage: $0 [--source-dir DIR] [--build-dir DIR] [--config FILE|--defconfig] [--lru-gen y|n] [--disable-btf]"; exit 0;;
        --source-dir) source_dir=$2; shift 2;; --build-dir) build_dir=$2; shift 2;;
        --config) config=$2; shift 2;; --defconfig) defconfig=1; shift;;
        --lru-gen) lru_gen=$2; [[ "$lru_gen" == y || "$lru_gen" == n ]] || die '--lru-gen must be y or n'; shift 2;;
        --disable-btf) disable_btf=1; shift;; *) die "unknown argument: $1";;
    esac
done
source_dir=$(absolute_path "$source_dir")
build_dir=$(absolute_path "$build_dir")
[[ -d "$source_dir" ]] || die "source directory not found: $source_dir"
require_safe_generated_dir "$build_dir"; mkdir -p -- "$build_dir"
if (( defconfig )); then make -C "$source_dir" O="$build_dir" defconfig
else
    if [[ -z "$config" ]]; then config="/boot/config-$(uname -r)"; fi
    [[ -f "$config" ]] || die "config not found: $config (use --defconfig or --config FILE)"
    cp -- "$config" "$build_dir/.config"; make -C "$source_dir" O="$build_dir" olddefconfig
fi
scripts="$source_dir/scripts/config"; [[ -x "$scripts" ]] || die 'scripts/config is unavailable'
"$scripts" --file "$build_dir/.config" --set-str SYSTEM_TRUSTED_KEYS '' --set-str SYSTEM_REVOCATION_KEYS '' \
    --enable MYSELF_KSWAPD --enable MEMCG --enable TRACING --enable TRACEPOINTS --set-str LOCALVERSION '-myks-l02' --disable LOCALVERSION_AUTO
case "$lru_gen" in y) "$scripts" --file "$build_dir/.config" --enable LRU_GEN;; n) "$scripts" --file "$build_dir/.config" --disable LRU_GEN;; esac
if (( disable_btf )); then "$scripts" --file "$build_dir/.config" --disable DEBUG_INFO_BTF; elif grep -q '^CONFIG_DEBUG_INFO_BTF=y' "$build_dir/.config" && ! command -v pahole >/dev/null 2>&1; then die 'CONFIG_DEBUG_INFO_BTF=y but pahole is missing; rerun with --disable-btf explicitly'; fi
make -C "$source_dir" O="$build_dir" olddefconfig; grep -q '^CONFIG_MYSELF_KSWAPD=y' "$build_dir/.config" || die 'CONFIG_MYSELF_KSWAPD is not enabled'
make -C "$source_dir" O="$build_dir" prepare modules_prepare
cp -- "$build_dir/.config" "$build_dir/CONFIG-LINUX-L02"; sha256sum "$build_dir/.config" > "$build_dir/CONFIG-LINUX-L02.sha256"
log "configured build directory: $build_dir"
