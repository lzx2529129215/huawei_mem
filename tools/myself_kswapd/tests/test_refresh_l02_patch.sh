#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT_DIR}/tools/myself_kswapd/refresh_linux617_l02_patch.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

BASE="${TMP_DIR}/base"
CURRENT="${TMP_DIR}/current"
PATCH_FILE="${TMP_DIR}/0003.patch"
mkdir -p "${BASE}/mm/myself_kswapd/include" \
    "${BASE}/mm/myself_kswapd/adapter" \
    "${BASE}/mm/myself_kswapd/debugfs" \
    "${BASE}/mm/myself_kswapd/trace" \
    "${BASE}/mm/myself_kswapd/tests"
cp -a "${BASE}" "${CURRENT}"

printf 'base\n' > "${BASE}/mm/vmscan.c"
printf 'current\n' > "${CURRENT}/mm/vmscan.c"
printf 'config\n' > "${CURRENT}/mm/myself_kswapd/Kconfig"
printf 'unsafe\n' > "${CURRENT}/outside.txt"
printf 'unsafe\n' > "${CURRENT}/mm/myself_kswapd/../outside-mm.txt"

if bash "${SCRIPT}" --base "${BASE}" --current "${CURRENT}" --output "${PATCH_FILE}"; then
    :
else
    echo "patch refresh script is expected to exist and pass" >&2
    exit 1
fi

grep -q '^diff --git a/Linux6.17/mm/vmscan.c b/Linux6.17/mm/vmscan.c$' "${PATCH_FILE}"
grep -q '^diff --git a/Linux6.17/mm/myself_kswapd/Kconfig b/Linux6.17/mm/myself_kswapd/Kconfig$' "${PATCH_FILE}"
! grep -q 'outside' "${PATCH_FILE}"
! grep -q '^diff --git .*[^a-zA-Z0-9_./-]' "${PATCH_FILE}"

EMPTY_PATCH="${TMP_DIR}/empty.patch"
if bash "${SCRIPT}" --base "${BASE}" --current "${BASE}" --output "${EMPTY_PATCH}"; then
    :
else
    echo "no-diff refresh should succeed without creating an empty patch" >&2
    exit 1
fi
test ! -e "${EMPTY_PATCH}"

bash "${SCRIPT}" --base "${BASE}" --current "${BASE}" \
    --output "${EMPTY_PATCH}" --allow-empty
test -f "${EMPTY_PATCH}"
test ! -s "${EMPTY_PATCH}"

echo "patch refresh self-test passed"
