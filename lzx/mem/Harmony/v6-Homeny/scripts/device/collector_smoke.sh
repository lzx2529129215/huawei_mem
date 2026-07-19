#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/setup_hdc_env_windows.sh"

stamp="$(date +%Y%m%d_%H%M%S)"
target="$(hdc list targets | tr -d '\r' | awk 'NF && $1 !~ /^\[/ {print $1; exit}')"
pid="$(hdc -t "${target}" shell 'pidof cn.wps.office.hap' | tr -d '\r' | awk '{print $1}')"
[[ -n ${target} && -n ${pid} ]]

local_dir="${ROOT}/hdc_out/collector_smoke_${stamp}"
remote_dir="/data/local/tmp/mem_analyze_v6/collector_smoke_${stamp}"
remote_bin="/data/local/tmp/mem_analyze_v6/mem_analyze-v6"
remote_md="${remote_dir}/collector_pid_${pid}.md"
remote_jsonl="${remote_dir}/collector_pid_${pid}.jsonl"
mkdir -p "${local_dir}"

hdc -t "${target}" shell "mkdir -p '${remote_dir}'"
hdc -t "${target}" file send "${ROOT}/mem_analyze-v6-ohos" "${remote_bin}"
hdc -t "${target}" shell "chmod 755 '${remote_bin}'"
hdc -t "${target}" shell "'${remote_bin}' --clear-refs '${pid}'"
sleep 1
collector_output="$(hdc -t "${target}" shell "'${remote_bin}' '${pid}' -o '${remote_md}' --jsonl-output '${remote_jsonl}' --with-vma")"
printf '%s\n' "${collector_output}"
device_md_sha="$(hdc -t "${target}" shell "sha256sum '${remote_md}' | cut -d ' ' -f 1" | tr -d '\r')"
device_jsonl_sha="$(hdc -t "${target}" shell "sha256sum '${remote_jsonl}' | cut -d ' ' -f 1" | tr -d '\r')"
hdc -t "${target}" file recv "${remote_md}" "${local_dir}/collector.md"
hdc -t "${target}" file recv "${remote_jsonl}" "${local_dir}/collector.jsonl"
local_md_sha="$(sha256sum "${local_dir}/collector.md" | cut -d ' ' -f 1)"
local_jsonl_sha="$(sha256sum "${local_dir}/collector.jsonl" | cut -d ' ' -f 1)"

python3 - "${local_dir}/collector.md" "${local_dir}/collector.jsonl" <<'PY'
import json
import re
import sys
from pathlib import Path

markdown = Path(sys.argv[1]).read_text(encoding="utf-8")
lines = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
records = [json.loads(line) for line in lines]
match = re.search(r"\| VMA 数 \| `(\d+)` \|", markdown)
assert match, "Markdown VMA count missing"
assert int(match.group(1)) == len(records), (match.group(1), len(records))
assert records and all(item["schema_version"] == "homeny.vma.v1" for item in records)
assert any(item["referenced_kib"] == 0 for item in records)
print(f"jsonl_records={len(records)} all_vmas_match=true referenced_zero_present=true")
PY

echo "target=${target} pid=${pid}"
echo "local_dir=${local_dir}"
echo "markdown_nonempty=$(test -s "${local_dir}/collector.md" && echo true || echo false)"
echo "jsonl_nonempty=$(test -s "${local_dir}/collector.jsonl" && echo true || echo false)"
echo "markdown_sha_match=$([[ ${device_md_sha} == "${local_md_sha}" ]] && echo true || echo false)"
echo "jsonl_sha_match=$([[ ${device_jsonl_sha} == "${local_jsonl_sha}" ]] && echo true || echo false)"
[[ ${device_md_sha} == "${local_md_sha}" && ${device_jsonl_sha} == "${local_jsonl_sha}" ]]
