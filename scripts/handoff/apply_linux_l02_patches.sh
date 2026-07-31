#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source_dir="$ROOT/work/linux-6.17"
while (($#)); do
    case "$1" in
        --help) usage_header; echo "Usage: $0 [--source-dir DIR]"; exit 0;;
        --source-dir) [[ $# -ge 2 ]] || die '--source-dir needs a value'; source_dir=$2; shift 2;;
        *) die "unknown argument: $1";;
    esac
done
source_dir=$(absolute_path "$source_dir")
[[ -d "$source_dir" ]] || die "source directory not found: $source_dir"
git_ceiling=$(dirname "$source_dir")
source_apply() { GIT_CEILING_DIRECTORIES="$git_ceiling" git -C "$source_dir" apply "$@"; }
if (verify_source_manifest "$source_dir" "$(manifest_path)") >/dev/null 2>&1; then
    log 'source state: NOT_APPLIED (pristine manifest verified)'
else
    log 'source state is non-pristine; determining exact patch state'
fi
for n in 0002 0003; do
    p=$(patch_path "$n")
    expected=$(awk -v name="patches/$(basename "$p")" '$2 == name {print $1}' "$ROOT/docs/handoff/checksums/patches.sha256")
    [[ -n "$expected" ]] || die "missing checksum for $(basename "$p")"
    verify_sha256 "$p" "$expected"
done
patch2=$(patch_path 0002)
patch3=$(mktemp)
trap 'rm -f -- "$patch3"' EXIT
sed -e 's#^diff --git a/Linux6\.17/#diff --git a/#' \
    -e 's# b/Linux6\.17/# b/#' \
    -e 's#^--- a/Linux6\.17/#--- a/#' \
    -e 's#^+++ b/Linux6\.17/#+++ b/#' "$(patch_path 0003)" > "$patch3"

if source_apply --check -p1 "$patch2" >/dev/null 2>&1; then
    source_apply --check -p1 "$patch3" >/dev/null 2>&1 || die '0003 cannot follow a pristine 0002 state'
    log 'applying 0002'; source_apply -p1 "$patch2"
    log 'applying 0003'; source_apply -p1 "$patch3"
elif source_apply --check -p1 "$patch3" >/dev/null 2>&1; then
    source_apply --reverse --check -p1 "$patch2" >/dev/null 2>&1 || die '0002: PARTIAL/UNKNOWN before pending 0003'
    log '0002: ALREADY_APPLIED'
    log 'applying 0003'; source_apply -p1 "$patch3"
elif source_apply --reverse --check -p1 "$patch3" >/dev/null 2>&1; then
    log '0002: ALREADY_APPLIED (validated through final 0003 state)'
    log '0003: ALREADY_APPLIED'
else
    die 'patch chain: PARTIAL/UNKNOWN; exact forward and reverse checks failed'
fi
for f in include/trace/events/myself_kswapd.h mm/myself_kswapd/heartbeat.c mm/myself_kswapd/adapter/observer_config.c; do
    [[ -f "$source_dir/$f" ]] || die "missing post-patch file: $f"
done
rg -q '^source "mm/myself_kswapd/Kconfig"$' "$source_dir/mm/Kconfig" || die '0002 Kconfig hook missing'
rg -q '^obj-\$\(CONFIG_MYSELF_KSWAPD\) \+= myself_kswapd/$' "$source_dir/mm/Makefile" || die '0002 Makefile hook missing'
rg -q 'myself_kswapd/include/kswapd_observer.h' "$source_dir/mm/vmscan.c" || die '0002 vmscan observer hook missing'
rg -q '#include <linux/mm.h>' "$source_dir/mm/myself_kswapd/adapter/observer_config.c" || die 'observer_config.c missing linux/mm.h include'
python3 "$ROOT/tools/myself_kswapd/tests/test_trace_event_arg_limits.py" "$source_dir/include/trace/events/myself_kswapd.h"
echo 'Linux L0.2 patch chain: PASS'
