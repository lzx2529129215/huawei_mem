# HarmonyOS WPS VMA Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing HarmonyOS WPS collector with baseline-subtracted VMA mapping while preserving the nine-stage automation and 56-dimensional workload pipeline.

**Architecture:** The C collector emits immutable raw Markdown/JSONL evidence. Focused Python modules resolve process roles and perform pure VMA analysis; the session runner only orchestrates collection and persists summaries. Cross-trial support is a separate offline analysis pass.

**Tech Stack:** C11, Python 3 standard library, pytest, Bash/PowerShell, OpenHarmony clang, HDC.

## Global Constraints

- Use `lzx/mem/Harmony/v6-Homeny` as the user-designated baseline; zip path and SHA256 are `NOT_PROVIDED`.
- Preserve every existing `hdc_out` file and every existing `operations.csv` field in its original order.
- Keep `report` pointing only to OPERATION Markdown.
- Keep SegmentKind and the `Referenced 段汇总` columns/semantics unchanged.
- Do not modify any kernel, WPS application, reclamation, protection, prefetch, or MGLRU behavior.
- Never represent VMA evidence as fabricated 256 KiB page-offset buckets.
- Keep `ready_for_operation_recognition=false` and `ready_for_apply=false`.

---

### Task 1: Configuration and process roles

**Files:**
- Create: `lzx/mem/Harmony/v6-Homeny/vma_mapping_config.json`
- Create: `lzx/mem/Harmony/v6-Homeny/process_role_resolver.py`
- Test: `lzx/mem/Harmony/v6-Homeny/tests/test_process_role_resolver.py`

**Interfaces:**
- Produces: `parse_proc_stat_starttime(text) -> int | None`, `resolve_process_role(row, rows) -> dict`, `enrich_process_rows(rows) -> list[dict]`.

- [ ] Write tests for comm parentheses/spaces, unavailable starttime, and all WPS/CEF roles; run them and confirm missing-module failure.
- [ ] Implement deterministic role precedence: renderer, GPU, zygote, network utility, libadapter, cloud/service, main, other.
- [ ] Run the focused tests and full test suite.

### Task 2: Collector JSONL contract

**Files:**
- Modify: `lzx/mem/Harmony/v6-Homeny/mem_analyze-v6.c`
- Test: `lzx/mem/Harmony/v6-Homeny/tests/test_vma_jsonl_parser.py`

**Interfaces:**
- Produces: CLI `--jsonl-output PATH`; status lines `REPORT_MD=...`, `REPORT_JSONL=...`; schema `homeny.vma.v1`.

- [ ] Add a test harness that compiles the C file with a test macro and verifies escaping, UTF-8, deleted paths, empty paths, device parsing, inode zero, zero RSS ratios, and full VMA emission; confirm failure first.
- [ ] Add independent `MappingType`, safe JSON escaping, normalized/deleted paths, device parsing, timestamps, all-VMA JSONL output, and generalized PID output paths.
- [ ] Append the five required VMA Markdown columns without changing the segment table.
- [ ] Run focused tests and `cc -std=c11 -Wall -Wextra -Werror -fsyntax-only mem_analyze-v6.c`.

### Task 3: Pure VMA parser, pairing, estimation, and keys

**Files:**
- Create: `lzx/mem/Harmony/v6-Homeny/operation_vma_mapping.py`
- Test: `tests/test_vma_pairing.py`, `tests/test_activity_classifier.py`, `tests/test_file_identity.py`, `tests/test_anon_features.py`

**Interfaces:**
- Produces: `load_vma_jsonl(paths)`, `pair_processes(baseline, operation)`, `pair_vmas(...)`, `classify_activity(...)`, `map_operation_stage(...)`, file/anonymous key helpers.

- [ ] Write failing tests for PID reuse/new/exit/PID-only, file/anonymous overlaps, ASLR, split/merge conservation, time scaling, mismatch states, activity boundaries, and address-free long-term keys.
- [ ] Implement dataclass-free dictionary transformations with explicit schema validation and deterministic ordering.
- [ ] Persist raw evidence and per-record quality fields even for invalid/degraded cases.
- [ ] Run focused and full tests.

### Task 4: Sample kinds and report transfer

**Files:**
- Modify: `lzx/mem/Harmony/v6-Homeny/wps_v6_session.py`
- Test: `tests/test_session_compatibility.py`

**Interfaces:**
- Consumes: role enrichment and `map_operation_stage`.
- Produces: `sample(index, stage, sample_kind, process_snapshot_before_collection) -> dict`.

- [ ] Write failing tests for stable status-line parsing, per-kind directories, hash CSV appended columns, and legacy `report` compatibility.
- [ ] Refactor sampling to transfer Markdown and JSONL, hash them independently, and key report records by kind/stage/PID/format.
- [ ] Extend process snapshots with one batched device shell command for stat/cmdline/comm/exe where practical.
- [ ] Run focused and full tests.

### Task 5: Baseline stage orchestration

**Files:**
- Modify: `wps_v6_session.py`
- Test: `tests/test_session_baseline.py`

**Interfaces:**
- Produces: monotonic timing fields, BASELINE/OPERATION/POST_LAUNCH records, mapping summaries.

- [ ] Write failing fake-device tests for ordinary stages, 01, 06, 07, and 08 timing/semantics.
- [ ] Implement ordinary idle baseline, POST_LAUNCH open, foreground/background state baselines, and startup-idle reopen baseline.
- [ ] Append all new `operations.csv` fields while leaving old order and meanings intact.
- [ ] Run focused and full tests.

### Task 6: Cross-trial support

**Files:**
- Create: `lzx/mem/Harmony/v6-Homeny/analyze_operation_vma_mapping.py`
- Modify: `lzx/mem/Harmony/v6-Homeny/run_wps_workload.py`
- Test: `tests/test_operation_vma_support.py`

**Interfaces:**
- Produces: `analyze(session_root, expected_repeats) -> dict` and required JSON/CSV/Markdown artifacts.

- [ ] Write failing tests for valid denominator exclusion, percentiles, role distribution, and CORE/COMMON/OCCASIONAL/NOISE boundaries.
- [ ] Implement deterministic file and anonymous support aggregation and quality/readiness reporting.
- [ ] Invoke the new analyzer after the legacy analyzer without masking either return code.
- [ ] Run focused and full tests.

### Task 7: CLI, shell, docs, and 56d regression

**Files:**
- Modify: `wps_v6_session.py`, `run_wps_workload.py`, `run_wps_v6.sh`, `run_wps_workload.sh`, `README.md`
- Test: `tests/test_legacy_56d.py`, `tests/test_cli_compatibility.py`

- [ ] Write failing tests for CLI pass-through, old Markdown parsing, 56 fields, old CSV fields, and operation Markdown report paths.
- [ ] Add baseline/config/disable flags and transparent shell pass-through while preserving old commands.
- [ ] Update documentation with JSONL, sample directories, semantics, limitations, and commands.
- [ ] Run all Python tests and py_compile for all seven Python files.

### Task 8: Builds and device evidence

**Files:**
- Preserve: old `mem_analyze-v6-ohos` as a timestamped backup.
- Generate: new `mem_analyze-v6-ohos`, HDC logs, and trial outputs.

- [ ] Record old binary SHA256, cross-compile with `-Wall -Wextra`, record new SHA256, and retain the backup.
- [ ] Source `scripts/device/setup_env.sh` before HDC commands where the environment supports it; otherwise use its resolved paths without changing device state beyond scope.
- [ ] Run HDC capability, collector, role, single-stage, and special-stage smoke tests in order.
- [ ] If smoke passes, run one full nine-stage workflow and verify legacy/new artifacts.
- [ ] If the full workflow passes, run three trials and the two analysis pipelines.
- [ ] Preserve raw outputs and failure logs; mark unavailable stages BLOCKED/NOT_RUN instead of PASS.

### Task 9: Final verification

- [ ] Run fresh full pytest, py_compile, host C warning check, cross build/hash check, and artifact/schema audit.
- [ ] Inspect `git status --short` and `git diff --stat`, separating pre-existing unrelated Linux changes.
- [ ] Report every requested status with command-backed evidence and fixed false values for operation recognition/apply.
