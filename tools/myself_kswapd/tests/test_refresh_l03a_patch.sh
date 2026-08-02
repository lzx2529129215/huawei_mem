#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
SCRIPT="$ROOT/tools/myself_kswapd/refresh_linux617_l03a_patch.sh"
tmp_dir=$(mktemp -d)
trap 'rm -rf -- "$tmp_dir"' EXIT
base="$tmp_dir/base"
current="$tmp_dir/current"
output="$tmp_dir/0004.patch"

paths=(
    include/trace/events/myself_kswapd.h
    mm/migrate.c mm/swap.c mm/vmscan.c
    mm/myself_kswapd/Kconfig mm/myself_kswapd/Makefile
    mm/myself_kswapd/adapter/kswapd_observer.c
    mm/myself_kswapd/adapter/lruvec_observer.c
    mm/myself_kswapd/adapter/page_lifecycle.c
    mm/myself_kswapd/debugfs/lruvec_debugfs.c
    mm/myself_kswapd/include/lruvec_observer.h
    mm/myself_kswapd/include/page_lifecycle.h
    mm/myself_kswapd/tests/Makefile
    mm/myself_kswapd/tests/page_lifecycle_test.c
)
for rel in "${paths[@]}"; do
    mkdir -p "$base/${rel%/*}" "$current/${rel%/*}"
    printf 'L0.2 %s\n' "$rel" > "$base/$rel"
    printf 'L0.3A %s\n' "$rel" > "$current/$rel"
done

bash "$SCRIPT" --base "$base" --current "$current" --output "$output"
for rel in "${paths[@]}"; do
    grep -Fq "diff --git a/Linux6.17/$rel b/Linux6.17/$rel" "$output"
done
test "$(grep -c '^diff --git ' "$output")" -eq "${#paths[@]}"
! grep -q '/tmp/' "$output"
echo "L0.3A patch refresh allowlist: PASS"
