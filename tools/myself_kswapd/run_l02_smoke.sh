#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
REPORT="$ROOT/docs/reports/linux-l02-validation.md"
ALLOW_DISABLE_MGLRU=0
if [[ "${1:-}" == "--allow-disable-mglru" ]]; then
    ALLOW_DISABLE_MGLRU=1
fi

reasons=()
TRACEFS="${TRACEFS:-}"
if [[ -z "$TRACEFS" ]]; then
    if [[ -d /sys/kernel/tracing ]]; then TRACEFS=/sys/kernel/tracing
    elif [[ -d /sys/kernel/debug/tracing ]]; then TRACEFS=/sys/kernel/debug/tracing
    fi
fi
[[ -d "$TRACEFS" ]] || reasons+=("tracefs not mounted")
[[ -r /proc/sys/kernel/osrelease ]] || reasons+=("kernel identity unavailable")
[[ -d "$TRACEFS/events/myself_kswapd" ]] || reasons+=("myself_kswapd trace events unavailable")
[[ -r /sys/kernel/mm/lru_gen/enabled ]] &&
    LRU_GEN_STATE=$(cat /sys/kernel/mm/lru_gen/enabled) ||
    LRU_GEN_STATE="unavailable"
if [[ "$LRU_GEN_STATE" != "unavailable" && "$ALLOW_DISABLE_MGLRU" -eq 0 ]]; then
    reasons+=("MGLRU state requires explicit --allow-disable-mglru for any change")
fi

{
    echo
    echo "## Runtime smoke"
    echo
    echo "- kernel: $(cat /proc/sys/kernel/osrelease 2>/dev/null || echo unavailable)"
    echo "- tracefs: ${TRACEFS:-unavailable}"
    echo "- MGLRU state: $LRU_GEN_STATE"
    if ((${#reasons[@]})); then
        echo
        echo "NOT RUN / ENVIRONMENT BLOCKED"
        printf '%s\n' "${reasons[@]}" | sed 's/^/- /'
    else
        echo
        echo "NOT RUN / ENVIRONMENT BLOCKED"
        echo "- preflight passed, but no disposable runtime target was authorized"
    fi
} >> "$REPORT"
printf 'NOT RUN / ENVIRONMENT BLOCKED\n'
if ((${#reasons[@]})); then
    printf '%s\n' "${reasons[@]}"
else
    printf '%s\n' "runtime smoke not authorized in this run"
fi
