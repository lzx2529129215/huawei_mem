#!/usr/bin/env bash
set -euo pipefail

source_root="${1:-$HOME/automation-wps}"
target_root="${2:-$HOME/PycharmProjects/automation-wps}"
report="${3:-/tmp/pycharm-project-created.txt}"

mkdir -p "$target_root"
cp -a "$source_root/automation" "$target_root/"
cp -a "$source_root/configs" "$target_root/"
chmod +x "$target_root"/automation/*.sh

{
    printf 'PROJECT=%s\n' "$target_root"
    printf 'PYTHON=%s\n' "$(command -v python3)"
    find "$target_root" -maxdepth 3 -type f | sort
} > "$report"
