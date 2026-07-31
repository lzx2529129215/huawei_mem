#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cache_dir="$ROOT/../linux-l02-source-cache"
source_dir="$ROOT/work/linux-6.17"
while (($#)); do
    case "$1" in
        --help) usage_header; echo "Usage: $0 [--cache-dir DIR] [--source-dir DIR]"; exit 0;;
        --cache-dir) [[ $# -ge 2 ]] || die '--cache-dir needs a value'; cache_dir=$2; shift 2;;
        --source-dir) [[ $# -ge 2 ]] || die '--source-dir needs a value'; source_dir=$2; shift 2;;
        *) die "unknown argument: $1";;
    esac
done
cache_dir=$(absolute_path "$cache_dir")
source_dir=$(absolute_path "$source_dir")
require_safe_generated_dir "$source_dir"
require_empty_or_absent "$source_dir"
need_cmd curl; need_cmd tar; need_cmd xz; need_cmd sha256sum
mkdir -p -- "$cache_dir" "$(dirname "$source_dir")"
archive="$cache_dir/$LINUX_ARCHIVE"
if [[ -f "$archive" ]]; then
    log "using cached archive: $archive"
else
    log "downloading fixed public source: $LINUX_URL"
    curl -fL --retry 3 --retry-delay 2 -o "$archive" "$LINUX_URL"
fi
verify_sha256 "$archive" "$LINUX_ARCHIVE_SHA256"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
tar -xJf "$archive" -C "$tmp"
extracted="$tmp/linux-$LINUX_VERSION"
[[ -d "$extracted" ]] || die "archive did not contain linux-$LINUX_VERSION"
mv -- "$extracted" "$source_dir"
verify_source_manifest "$source_dir" "$(manifest_path)"
log "pristine source verified: $source_dir"
