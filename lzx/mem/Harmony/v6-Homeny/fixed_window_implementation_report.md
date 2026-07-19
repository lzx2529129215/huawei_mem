# Fixed-window implementation report

## Scope and compatibility

- Working directory: `D:/lzx/school/lzx_code/lzx华为/lzx/mem/Harmony/v6-Homeny`.
- Existing formal data `hdc_out/wps_workload_formal20_3trial_20260717` was not overwritten.
- The original nine operation names, legacy `operations.csv` columns, Markdown reports, `homeny.vma.v1`, operation-level VMA analysis, and 56-dimensional workload code remain present.
- Fixed-window detail is additive and is stored below `vma_mapping/`; windows are not expanded into extra business rows in `operations.csv`.
- No kernel, MGLRU, page-reclaim policy, WPS application, protection, or prefetch behavior was changed.

## Worktree audit

At task start the repository was already dirty. The recorded status contained 13 modified `cache_ext/linux` files unrelated to this task, modified v6 collector/session/runner files from the approved previous baseline/VMA work, the collector binary and backup, and numerous untracked prior evidence directories and test/modules. Those changes were treated as user-owned and preserved. No `git reset --hard`, `git clean`, `git add .`, commit, or checkout rollback was used.

At final audit, tracked `git diff --stat` reports 23 files, 1,908 insertions and 1,012 deletions; this includes the untouched pre-existing kernel diff. New fixed-window Python modules, reports, tests, config, and HDC evidence remain untracked in the existing dirty worktree. The final `git status --short` is intentionally not cleaned.

## Fixed design

1. An ordinary operation execution uses two independently cleared baseline windows followed by one or more independently cleared operation windows. Collection begins after the observation window; collector runtime is excluded from `actual_window_s`.
2. `01_open_wps` remains `POST_LAUNCH` with `BASELINE_NOT_APPLICABLE`; post-launch windows are not presented as ordinary baseline subtraction.
3. `06_background` uses `FOREGROUND_IDLE`; `07_foreground` uses `BACKGROUND_IDLE`.
4. `08_reopen_saved_document` keeps `POST_LAUNCH_PRE_DOCUMENT_IDLE`: WPS is running while the target document is still closed.
5. Processes pair by PID plus `/proc/<pid>/stat` starttime. Missing starttime is `PID_ONLY_MATCH`; a changed starttime is `PID_REUSED` and is not treated as a valid pair.
6. File VMAs pair by device, inode, permissions, and file-offset overlap.
7. Anonymous VMAs pair by virtual-address overlap only inside the same paired process lifetime. Their semantic key excludes runtime addresses and remains auxiliary only.
8. Split/merge matches allocate baseline Referenced pages in proportion to overlap. The output says `VMA_SPLIT_MERGE_APPROXIMATION` and retains interval evidence.
9. A new PID is `NEW_PROCESS_NO_BASELINE`; its raw reports remain, but it is not silently classified inactive.
10. Exited PIDs are `PROCESS_EXITED`; reused PIDs are separated from valid pairs.
11. The primary fixed-window estimate is `max(0, operation - median_baseline)`. The compatibility time-normalized estimate is retained under explicit `TIME_NORMALIZED_REFERENCED_HEURISTIC` fields.
12. Quality remains multi-axis: collection, process/VMA match, activity/window, and identity. Degraded states retain raw data and do not masquerade as normal support samples.

## Window quality

- `OK`: absolute duration error at most 0.5 s; support eligible.
- `MINOR_MISMATCH`: error over 0.5 s and at most 1.0 s; support eligible with the downgrade retained.
- `PARTIAL_WINDOW`: shorter than target minus 1.0 s; excluded by default.
- `OVERRUN_WINDOW`: longer than target plus 1.0 s but not beyond the configured severe boundary; excluded by default.
- `SEVERE_OVERRUN`: beyond `target + max(minor_tolerance, max_action_overrun)`; excluded by default.
- A failed action, collection, hash, baseline, PID-lifetime, or mapping check overrides time eligibility with an explicit exclusion reason.

## Baseline median and execution aggregation

- Two eligible baselines are grouped by file identity/offset interval or anonymous runtime interval and reduced per VMA with a median.
- One valid baseline produces `SINGLE_BASELINE_WINDOW`; zero produces `NO_VALID_BASELINE_WINDOWS` and excludes the execution.
- Execution summaries expose sum, maximum, active-window count, and window count per semantic key.
- The exact aggregation label is `SUM_OF_VMA_WINDOW_SAMPLES_NOT_UNIQUE_PAGE_SET`; no unique page-set claim is made.

## Implementation files

New modules:

- `fixed_window_mapping.py`: quality, baseline median, window VMA mapping, fixed estimate, execution aggregation, similarity primitives.
- `analyze_fixed_windows.py`: streaming segment/operation support and FILE/ANON/combined similarity.
- `run_fixed_window_experiment.py`: ordered timing, block pilot, chunk pilot, stage04, and dataset device experiments.
- `rebuild_fixed_window_mapping.py`: deterministic rebuild from preserved window reports after a local derived-output failure.
- `tests/test_fixed_windows.py`: fixed-window regression coverage.

Modified integration:

- `wps_v6_session.py`: unified `run_fixed_window`, window JSONL, median mapping orchestration, safe text/block chunk actions, fixed stage04, compatibility CSV columns.
- `run_wps_workload.py`, `run_wps_v6.sh`, `run_wps_workload.sh`: fixed-window CLI passthrough and removal of the stale hard-coded target fallback.
- `vma_mapping_config.json`: the approved `fixed_windows` defaults.

## Output contract

Per trial:

- `operation_window_samples.jsonl`
- `operation_window_process_pairs.jsonl`
- `operation_window_vma_pairs.jsonl`
- `operation_window_file_vma_samples.jsonl`
- `operation_window_anon_vma_samples.jsonl`
- `operation_window_sequences.json`
- `fixed_window_quality.json`
- `fixed_window_summary.md`

Cross trial:

- `fixed_window_operation_file_support.csv`
- `fixed_window_operation_anon_support.csv`
- `fixed_window_similarity.csv`
- `fixed_window_stability.json`
- `fixed_window_analysis.md`

The per-VMA derived files use flattened interval evidence rather than copying complete raw baseline/operation VMA dictionaries. The collector JSONL remains the full raw source.

## Current limitation

The unified executor and analysis are implemented and proven for timing, edit, metadata-sample, and scroll windows. A full fixed-window nine-stage run was not performed: launch/new/save/reopen microaction boundaries have not yet received the same real-device pilot and content gates. The existing legacy nine-stage runner remains available and compatible; this limitation is not hidden as a pass.
