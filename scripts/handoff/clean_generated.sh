#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
yes=0; work="$ROOT/work"; build="$ROOT/builds"
while (($#)); do case "$1" in --help) usage_header; echo "Usage: $0 --yes"; exit 0;; --yes) yes=1; shift;; *) die "unknown argument: $1";; esac; done
[[ "$work" == "$ROOT/work" && "$build" == "$ROOT/builds" ]] || die 'unsafe cleanup target'; (( yes )) || die 'refusing cleanup without explicit --yes'
[[ -d "$work" ]] && find "$work" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; [[ -d "$build" ]] && find "$build" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
echo 'Generated handoff directories cleaned; tracked files were not touched.'
