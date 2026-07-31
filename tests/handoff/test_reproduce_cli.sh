#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
for script in "$ROOT/scripts/handoff"/*.sh; do
    "$script" --help >/dev/null
done
echo 'handoff CLI help: PASS'
