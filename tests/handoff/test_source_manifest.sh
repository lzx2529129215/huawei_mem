#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/scripts/handoff/common.sh"
tmp=$(mktemp -d); trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/source"; printf 'one\n' > "$tmp/source/file"
manifest="$tmp/manifest"; write_source_manifest "$tmp/source" "$manifest"; verify_source_manifest "$tmp/source" "$manifest"
printf 'two\n' > "$tmp/source/file"
if (verify_source_manifest "$tmp/source" "$manifest") >/dev/null 2>&1; then
    echo 'manifest mismatch was accepted' >&2; exit 1
fi
echo 'source manifest mismatch rejection: PASS'
