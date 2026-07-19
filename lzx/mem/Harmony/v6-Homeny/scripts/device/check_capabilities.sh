#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/setup_hdc_env_windows.sh"

echo "---TARGETS---"
hdc list targets
echo "---ID---"
hdc shell id
echo "---UNAME---"
hdc shell uname -a
echo "---PROC_ACCESS---"
if hdc shell 'test -r /proc/self/smaps -a -w /proc/self/clear_refs'; then
    echo "proc_access=PASS"
else
    echo "proc_access=FAIL"
fi
echo "---WPS_PIDOF---"
hdc shell 'pidof cn.wps.office.hap' || true
echo "---WPS_PS---"
hdc shell 'ps -ef | grep -i wps | grep -v grep' || true
echo "---COLLECTOR_PROCESSES---"
hdc shell 'ps -ef | grep mem_analyze-v6 | grep -v grep' || true
