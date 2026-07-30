#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s --source <L0.1 Linux6.17 tree> --dest <L0.2 Linux6.17 tree>\n' \
        "${0##*/}" >&2
}

SOURCE=''
DEST=''
while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            SOURCE=$2
            shift 2
            ;;
        --dest)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            DEST=$2
            shift 2
            ;;
        -h|--help)
            usage >&2
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

[[ -n "$SOURCE" && -n "$DEST" ]] || { usage; exit 2; }
[[ -d "$SOURCE" ]] || { printf 'source is not a directory: %s\n' "$SOURCE" >&2; exit 1; }

source_abs=$(cd -- "$SOURCE" && pwd -P)
dest_abs=$(realpath -m -- "$DEST")
[[ "$source_abs" != "$dest_abs" ]] || {
    printf 'source and destination must differ: %s\n' "$source_abs" >&2
    exit 1
}

if [[ -e "$DEST" && ! -d "$DEST" ]]; then
    printf 'destination is not a directory: %s\n' "$DEST" >&2
    exit 1
fi

if [[ -d "$DEST" ]] && find "$DEST" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    printf 'destination must be absent or empty: %s\n' "$DEST" >&2
    exit 1
fi

mkdir -p -- "$DEST"
cp -a --reflink=auto -- "$source_abs"/. "$DEST"/
{
    printf 'source=%s\n' "$source_abs"
    printf 'created_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$DEST/.myks_l02_base"

printf 'bootstrapped %s from %s\n' "$DEST" "$source_abs"
