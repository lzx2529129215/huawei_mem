#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: ${0##*/} --base L0.2_TREE --current L0.3A_TREE --output PATCH" >&2
}

BASE=''
CURRENT=''
OUTPUT=''
while (($#)); do
    case "$1" in
        --base) BASE=$2; shift 2 ;;
        --current) CURRENT=$2; shift 2 ;;
        --output) OUTPUT=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done
[[ -n "$BASE" && -n "$CURRENT" && -n "$OUTPUT" ]] || { usage; exit 2; }
[[ -d "$BASE" && -d "$CURRENT" ]] || {
    echo "base and current must be directories" >&2
    exit 1
}

readonly ALLOWED_PATHS=(
    include/trace/events/myself_kswapd.h
    mm/migrate.c
    mm/swap.c
    mm/vmscan.c
    mm/myself_kswapd/Kconfig
    mm/myself_kswapd/Makefile
    mm/myself_kswapd/adapter/kswapd_observer.c
    mm/myself_kswapd/adapter/lruvec_observer.c
    mm/myself_kswapd/adapter/page_lifecycle.c
    mm/myself_kswapd/debugfs/lruvec_debugfs.c
    mm/myself_kswapd/include/lruvec_observer.h
    mm/myself_kswapd/include/page_lifecycle.h
    mm/myself_kswapd/tests/Makefile
    mm/myself_kswapd/tests/page_lifecycle_test.c
)

base_abs=$(cd -- "$BASE" && pwd -P)
current_abs=$(cd -- "$CURRENT" && pwd -P)
base_label=${base_abs#/}
current_label=${current_abs#/}
tmp_dir=$(mktemp -d)
trap 'rm -rf -- "$tmp_dir"' EXIT
tmp_patch="$tmp_dir/0004.patch"
changed_paths="$tmp_dir/changed-paths"
: > "$tmp_patch"
: > "$changed_paths"

normalize_patch() {
    local rel=$1
    sed \
        -e "s|a/${base_label}/${rel}|a/Linux6.17/${rel}|g" \
        -e "s|b/${current_label}/${rel}|b/Linux6.17/${rel}|g" \
        -e "s|a/${current_label}/${rel}|a/Linux6.17/${rel}|g" \
        -e "s|b/${base_label}/${rel}|b/Linux6.17/${rel}|g"
}

for rel in "${ALLOWED_PATHS[@]}"; do
    left=/dev/null
    right=/dev/null
    [[ -f "$base_abs/$rel" ]] && left="$base_abs/$rel"
    [[ -f "$current_abs/$rel" ]] && right="$current_abs/$rel"
    [[ "$left" != /dev/null || "$right" != /dev/null ]] || {
        echo "allowlisted path absent from both trees: $rel" >&2
        exit 1
    }
    set +e
    patch_text=$(git diff --no-index --binary -- "$left" "$right")
    rc=$?
    set -e
    ((rc <= 1)) || exit "$rc"
    if [[ -n "$patch_text" ]]; then
        printf '%s\n' "$rel" >> "$changed_paths"
        printf '%s\n' "$patch_text" | normalize_patch "$rel" >> "$tmp_patch"
    fi
done

expected="$tmp_dir/expected"
printf '%s\n' "${ALLOWED_PATHS[@]}" | sort > "$expected"
sort -o "$changed_paths" "$changed_paths"
if ! cmp -s "$expected" "$changed_paths"; then
    echo "L0.3A allowlist mismatch; expected every frozen path to differ" >&2
    diff -u "$expected" "$changed_paths" >&2 || true
    exit 1
fi
[[ -s "$tmp_patch" ]] || { echo "empty L0.3A patch" >&2; exit 1; }

output_parent=${OUTPUT%/*}
[[ "$output_parent" != "$OUTPUT" ]] || output_parent=.
mkdir -p -- "$output_parent"
mv -- "$tmp_patch" "$OUTPUT"
echo "refreshed $OUTPUT"
