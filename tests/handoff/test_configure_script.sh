#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
"$ROOT/scripts/handoff/configure_linux_l02.sh" --help >/dev/null
"$ROOT/scripts/handoff/install_linux_l02.sh" --help >/dev/null
echo 'configure/install CLI: PASS'
