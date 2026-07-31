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
    patch_input=$p
    if [[ "$n" == 0003 ]]; then
        patch_input=$(mktemp)
        trap 'rm -f -- "$patch_input"' RETURN
        sed -e 's#^diff --git a/Linux6\.17/#diff --git a/#' \
            -e 's# b/Linux6\.17/# b/#' \
            -e 's#^--- a/Linux6\.17/#--- a/#' \
            -e 's#^+++ b/Linux6\.17/#+++ b/#' "$p" > "$patch_input"
    fi
    if source_apply --check -p1 "$patch_input" >/dev/null 2>&1; then
        log "applying $n"
        source_apply -p1 "$patch_input"
    elif source_apply --reverse --check -p1 "$patch_input" >/dev/null 2>&1; then
        log "$n: ALREADY_APPLIED"
    else
        die "$n: PARTIAL/UNKNOWN; neither exact apply nor exact reverse apply succeeded"
    fi
    if [[ "$n" == 0003 ]]; then rm -f -- "$patch_input"; trap - RETURN; fi
done
for f in include/trace/events/myself_kswapd.h mm/myself_kswapd/heartbeat.c mm/myself_kswapd/adapter/observer_config.c; do
    [[ -f "$source_dir/$f" ]] || die "missing post-patch file: $f"
done
rg -q '#include <linux/mm.h>' "$source_dir/mm/myself_kswapd/adapter/observer_config.c" || die 'observer_config.c missing linux/mm.h include'
python3 "$ROOT/tools/myself_kswapd/tests/test_trace_event_arg_limits.py" "$source_dir/include/trace/events/myself_kswapd.h"
echo 'Linux L0.2 patch chain: PASS'
