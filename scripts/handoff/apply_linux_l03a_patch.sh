#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

source_dir="$ROOT/work/linux-6.17-l03a-final"
while (($#)); do
    case "$1" in
        --help)
            usage_header
            echo "Usage: $0 [--source-dir DIR]"
            exit 0
            ;;
        --source-dir)
            [[ $# -ge 2 ]] || die '--source-dir needs a value'
            source_dir=$2
            shift 2
            ;;
        *) die "unknown argument: $1" ;;
    esac
done
source_dir=$(absolute_path "$source_dir")
[[ -d "$source_dir" ]] || die "source directory not found: $source_dir"

patch_file="$ROOT/patches/0004-linux617-myself-kswapd-l03a-page-lifecycle.patch"
expected=$(awk '$2 == "patches/0004-linux617-myself-kswapd-l03a-page-lifecycle.patch" {print $1}' \
    "$ROOT/docs/handoff/checksums/patches.sha256")
[[ -n "$expected" ]] || die 'missing 0004 checksum'
verify_sha256 "$patch_file" "$expected"

normalized=$(mktemp)
trap 'rm -f -- "$normalized"' EXIT
sed -e 's#^diff --git a/Linux6\.17/#diff --git a/#' \
    -e 's# b/Linux6\.17/# b/#' \
    -e 's#^--- a/Linux6\.17/#--- a/#' \
    -e 's#^+++ b/Linux6\.17/#+++ b/#' \
    "$patch_file" > "$normalized"
git_ceiling=$(dirname "$source_dir")
source_apply() {
    GIT_CEILING_DIRECTORIES="$git_ceiling" git -C "$source_dir" apply "$@"
}

if source_apply --reverse --check -p1 "$normalized" >/dev/null 2>&1; then
    log '0004: ALREADY_APPLIED'
else
    "$ROOT/scripts/handoff/apply_linux_l02_patches.sh" --source-dir "$source_dir"
    if source_apply --check -p1 "$normalized" >/dev/null 2>&1; then
        log 'applying 0004'
        source_apply -p1 "$normalized"
    else
        die '0004: PARTIAL/UNKNOWN; exact forward and reverse checks failed'
    fi
fi

for rel in \
    mm/myself_kswapd/adapter/page_lifecycle.c \
    mm/myself_kswapd/include/page_lifecycle.h \
    mm/myself_kswapd/tests/page_lifecycle_test.c; do
    [[ -f "$source_dir/$rel" ]] || die "0004 missing post-patch file: $rel"
done
rg -q '^config MYSELF_KSWAPD_PAGE_LIFECYCLE$' \
    "$source_dir/mm/myself_kswapd/Kconfig" || die '0004 Kconfig symbol missing'
python3 "$ROOT/tools/myself_kswapd/tests/test_trace_event_arg_limits.py" \
    "$source_dir/include/trace/events/myself_kswapd.h"
python3 "$ROOT/tools/myself_kswapd/tests/test_page_lifecycle_trace_contract.py" \
    "$source_dir/include/trace/events/myself_kswapd.h"
echo 'Linux L0.3A patch chain: PASS'
