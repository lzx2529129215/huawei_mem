#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SOURCE_DIR=${SOURCE_DIR:-$ROOT/work/linux-6.17-l03a-final-v2}
OUTPUT_ROOT=${OUTPUT_ROOT:-$ROOT/../outputs/linux-l03a-20260802/builds/config-matrix}
JOBS=${JOBS:-2}

[[ -f "$SOURCE_DIR/Makefile" ]] || {
    echo "missing Linux source: $SOURCE_DIR" >&2
    exit 1
}
mkdir -p "$OUTPUT_ROOT"

build_variant() {
    local name=$1
    shift
    local output="$OUTPUT_ROOT/$name"

    mkdir -p "$output"
    make -C "$SOURCE_DIR" O="$output" defconfig
    "$SOURCE_DIR/scripts/config" --file "$output/.config" \
        --enable KUNIT \
        --enable MYSELF_KSWAPD \
        --enable MYSELF_KSWAPD_PAGE_LIFECYCLE \
        --enable MYSELF_KSWAPD_KUNIT_TEST \
        "$@"
    make -C "$SOURCE_DIR" O="$output" olddefconfig prepare
    grep -q '^CONFIG_MYSELF_KSWAPD_PAGE_LIFECYCLE=y$' "$output/.config"
    make -C "$SOURCE_DIR" O="$output" -j"$JOBS" \
        mm/swap.o mm/vmscan.o mm/migrate.o \
        mm/myself_kswapd/adapter/page_lifecycle.o \
        mm/myself_kswapd/adapter/observer_config.o \
        mm/myself_kswapd/heartbeat.o \
        mm/myself_kswapd/debugfs/lruvec_debugfs.o \
        mm/myself_kswapd/trace/trace.o \
        mm/myself_kswapd/tests/page_lifecycle_test.o
    for rel in \
        mm/swap.o mm/vmscan.o mm/migrate.o \
        mm/myself_kswapd/adapter/page_lifecycle.o \
        mm/myself_kswapd/adapter/observer_config.o \
        mm/myself_kswapd/heartbeat.o \
        mm/myself_kswapd/debugfs/lruvec_debugfs.o \
        mm/myself_kswapd/trace/trace.o \
        mm/myself_kswapd/tests/page_lifecycle_test.o; do
        test -s "$output/$rel"
    done
    echo "L0.3A object matrix $name: PASS"
}

build_variant memcg-y-lrugen-n-debugfs-y \
    --enable MEMCG --disable LRU_GEN --enable DEBUG_FS
build_variant memcg-n-lrugen-n-debugfs-y \
    --disable MEMCG --disable LRU_GEN --enable DEBUG_FS
build_variant memcg-y-lrugen-y-debugfs-y \
    --enable MEMCG --enable LRU_GEN --enable DEBUG_FS
build_variant memcg-y-lrugen-n-debugfs-n \
    --enable MEMCG --disable LRU_GEN --disable DEBUG_FS

echo "Linux L0.3A four-way object matrix: PASS"
