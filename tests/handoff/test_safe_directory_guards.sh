#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
target="$ROOT/work/handoff-test-nonempty"; mkdir -p "$target"; printf x > "$target/sentinel"
trap 'rm -rf -- "$target"' EXIT
if "$ROOT/scripts/handoff/fetch_linux617_source.sh" --source-dir "$target" --cache-dir "$ROOT/work/handoff-test-cache" >/dev/null 2>&1; then
    echo 'non-empty directory was accepted' >&2; exit 1
fi
if "$ROOT/scripts/handoff/fetch_linux617_source.sh" --source-dir "$ROOT" --cache-dir "$ROOT/work/handoff-test-cache" >/dev/null 2>&1; then
    echo 'unsafe source directory was accepted' >&2; exit 1
fi
echo 'safe directory guards: PASS'
