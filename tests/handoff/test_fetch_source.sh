#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
cache="$tmp/cache"; mkdir -p "$cache"; printf 'not a Linux archive\n' > "$cache/linux-6.17.tar.xz"
target="$ROOT/work/handoff-test-bad-sha"; mkdir -p "$target"
trap 'rm -rf -- "$target" "$tmp"' EXIT
if "$ROOT/scripts/handoff/fetch_linux617_source.sh" --cache-dir "$cache" --source-dir "$target" >/dev/null 2>&1; then
    echo 'bad SHA was accepted' >&2; exit 1
fi
echo 'fetch bad SHA rejection: PASS'
