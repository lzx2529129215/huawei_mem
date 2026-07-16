#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v hdc >/dev/null 2>&1; then
    for candidate in \
        "$HOME/Library/OpenHarmony/Sdk/23/toolchains" \
        "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains"; do
        if [[ -x "$candidate/hdc" ]]; then
            export PATH="$candidate:$PATH"
            break
        fi
    done
fi

exec python3 "$SCRIPT_DIR/wps_v6_session.py" "$@"
