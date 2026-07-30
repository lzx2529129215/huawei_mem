#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
CLI="${CLI:-$ROOT/用户态模拟器/v1/output/task18-green/bin/lruvec_observer_cli}"
FIXTURE="$ROOT/tools/myself_kswapd/tests/fixtures/lruvec_snapshot.log"

[[ -x "$CLI" ]]
grep -q '"status":"PARSED"' <("$CLI" --input "$FIXTURE" --mode parse-only)
grep -q 'PROVISIONAL_GAP\|ACCEPTED' <("$CLI" --input "$FIXTURE" --mode bootstrap)
if "$CLI" --input "$FIXTURE" --mode strict >/dev/null; then
    exit 1
fi
