#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT_DIR}/tools/myself_kswapd/bootstrap_linux617_l02_tree.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

SOURCE="${TMP_DIR}/source"
DEST="${TMP_DIR}/dest"
mkdir -p "${SOURCE}/mm/myself_kswapd/include"
printf 'source\n' > "${SOURCE}/Makefile"
printf 'observer\n' > "${SOURCE}/mm/vmscan.c"
printf 'header\n' > "${SOURCE}/mm/myself_kswapd/include/observer.h"

if bash "${SCRIPT}" --source "${SOURCE}" --dest "${DEST}"; then
    :
else
    echo "bootstrap script is expected to exist and pass the first invocation" >&2
    exit 1
fi

test "$(cat "${DEST}/Makefile")" = source
test "$(cat "${DEST}/mm/vmscan.c")" = observer
test "$(cat "${DEST}/mm/myself_kswapd/include/observer.h")" = header
test -s "${DEST}/.myks_l02_base"

mkdir -p "${TMP_DIR}/unknown"
printf 'keep\n' > "${TMP_DIR}/unknown/file"
if bash "${SCRIPT}" --source "${SOURCE}" --dest "${TMP_DIR}/unknown"; then
    echo "non-empty unknown destination must be rejected" >&2
    exit 1
fi

if bash "${SCRIPT}" --source "${SOURCE}" --dest "${SOURCE}"; then
    echo "identical source and destination must be rejected" >&2
    exit 1
fi

echo "bootstrap self-test passed"
