#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s --base <L0.1 tree> --current <L0.2 tree> --output <patch> [--allow-empty]\n' \
        "${0##*/}" >&2
}

BASE=''
CURRENT=''
OUTPUT=''
ALLOW_EMPTY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            BASE=$2
            shift 2
            ;;
        --current)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            CURRENT=$2
            shift 2
            ;;
        --output)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            OUTPUT=$2
            shift 2
            ;;
        --allow-empty)
            ALLOW_EMPTY=1
            shift
            ;;
        -h|--help)
            usage >&2
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

[[ -n "$BASE" && -n "$CURRENT" && -n "$OUTPUT" ]] || { usage; exit 2; }
[[ -d "$BASE" && -d "$CURRENT" ]] || {
    printf 'base and current must be directories\n' >&2
    exit 1
}
case "$OUTPUT" in
    ../*|*/../*|*/..|..)
        printf 'output path traversal is not allowed: %s\n' "$OUTPUT" >&2
        exit 1
        ;;
esac

base_abs=$(cd -- "$BASE" && pwd -P)
current_abs=$(cd -- "$CURRENT" && pwd -P)
base_label=${base_abs#/}
current_label=${current_abs#/}
TMP_DIR=$(mktemp -d)
trap 'rm -rf -- "$TMP_DIR"' EXIT
PATHS_FILE="$TMP_DIR/paths"
TMP_OUTPUT="$TMP_DIR/output"
: > "$PATHS_FILE"

is_allowed() {
    local rel=$1
    case "$rel" in
        include/trace/events/myself_kswapd.h)
            ;;
        mm/vmscan.c|mm/myself_kswapd/Kconfig|mm/myself_kswapd/Makefile|\
        mm/myself_kswapd/include/*|mm/myself_kswapd/adapter/*|\
        mm/myself_kswapd/debugfs/*|mm/myself_kswapd/trace/*|\
        mm/myself_kswapd/tests/*)
            [[ "$rel" != *..* ]]
            ;;
        *)
            return 1
            ;;
    esac
}

collect_paths() {
    local root=$1
    [[ -d "$root" ]] || return 0
    while IFS= read -r -d '' path; do
        local rel=${path#"$root"/}
        if is_allowed "$rel"; then
            printf '%s\n' "$rel" >> "$PATHS_FILE"
        fi
    done < <(find "$root" -type f -print0)
}

collect_paths "$base_abs"
collect_paths "$current_abs"

normalize_patch() {
    local rel=$1
    sed \
        -e "s|a/${base_label}/${rel}|a/Linux6.17/${rel}|g" \
        -e "s|b/${current_label}/${rel}|b/Linux6.17/${rel}|g" \
        -e "s|a/${current_label}/${rel}|a/Linux6.17/${rel}|g" \
        -e "s|b/${base_label}/${rel}|b/Linux6.17/${rel}|g"
}

while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    base_path="$base_abs/$rel"
    current_path="$current_abs/$rel"
    left=/dev/null
    right=/dev/null
    [[ -f "$base_path" ]] && left=$base_path
    [[ -f "$current_path" ]] && right=$current_path
    [[ "$left" != /dev/null || "$right" != /dev/null ]] || continue

    set +e
    patch_text=$(git diff --no-index --binary -- "$left" "$right")
    diff_status=$?
    set -e
    if [[ $diff_status -gt 1 ]]; then
        printf 'git diff failed for %s\n' "$rel" >&2
        exit "$diff_status"
    fi
    if [[ -n "$patch_text" ]]; then
        printf '%s\n' "$patch_text" | normalize_patch "$rel" >> "$TMP_OUTPUT"
    fi
done < <(sort -u "$PATHS_FILE")

output_parent=${OUTPUT%/*}
if [[ "$output_parent" == "$OUTPUT" ]]; then
    output_parent=.
fi

if [[ -s "$TMP_OUTPUT" ]]; then
    mkdir -p -- "$output_parent"
    mv -- "$TMP_OUTPUT" "$OUTPUT"
    printf 'refreshed %s\n' "$OUTPUT"
elif [[ $ALLOW_EMPTY -eq 1 ]]; then
    mkdir -p -- "$output_parent"
    : > "$OUTPUT"
    printf 'created empty %s\n' "$OUTPUT"
else
    printf 'no allowlisted Linux6.17 differences\n'
fi
