# HarmonyOS WPS Baseline/VMA Mapping Design

## Scope and baseline

The user-designated baseline is `lzx/mem/Harmony/v6-Homeny`; no zip archive was provided. Before any source edit, the directory was copied to `lzx/mem/Harmony/v6-Homeny.backup_20260716_163441`. The source and backup manifest SHA256 are both `cf6a08045d493a7afc719298e3747b77cbe2992f4870eac0f6b1e9d2f2c8e424`.

This extension collects and analyzes userspace evidence only. It does not change HarmonyOS/Linux kernels, MGLRU, reclamation, WPS itself, page protection, or prefetch behavior.

## Module boundaries

- `mem_analyze-v6.c` reads `/proc/<pid>/smaps`, preserves the current Markdown and `SegmentKind` summary, and emits all VMAs as `homeny.vma.v1` JSONL with an independent `mapping_type`.
- `process_role_resolver.py` parses process metadata and classifies WPS/CEF roles. It has no HDC orchestration responsibility.
- `operation_vma_mapping.py` is a pure analysis module. It parses JSONL, pairs processes and VMAs, estimates background activity, classifies activity, generates file/anonymous keys, and emits quality states.
- `wps_v6_session.py` orchestrates the nine UI stages, the three sample kinds, real timing, collector execution, transfers, hashes, and per-stage mapping invocation.
- `analyze_operation_vma_mapping.py` aggregates valid samples across trials and writes support and quality analysis.
- `analyze_wps_workload.py` remains the consumer of operation Markdown for the existing 56-dimensional vectors.

## Sample data flow

For an ordinary measured stage:

1. Capture the pre-baseline process snapshot.
2. Clear Referenced bits for all matching WPS processes and record wall/monotonic start and end.
3. Start the baseline window at successful clear completion; sleep for the configured idle duration without UI action.
4. Capture the baseline process snapshot and begin the BASELINE collector. `baseline_window_s` is collector-start monotonic time minus clear-complete monotonic time.
5. Pull and hash every Markdown and JSONL report into `baseline_reports/<stage>/`.
6. Clear Referenced bits again and start the operation window at clear completion.
7. Run the existing UI action, settle, capture the operation process snapshot, and begin the OPERATION collector. `operation_window_s` uses the same monotonic definition.
8. Pull and hash reports into `operation_reports/<stage>/`.
9. Invoke the pure mapping module with both snapshots, both report sets, windows, stage context, and config.
10. Persist raw, paired, file, anonymous, and quality outputs under `vma_mapping/`, then append the summary to `operations.csv`.

The original `report` column always contains OPERATION Markdown paths. Baseline and JSONL paths use appended columns.

## Special stage timing

- `01_open_wps`: force-stop, launch, wait, clear_refs, wait, POST_LAUNCH sample. It records `baseline_status=NOT_APPLICABLE`, `baseline_unavailable_reason=NO_PREEXISTING_WPS_PROCESS`, and `sample_semantics=POST_LAUNCH_ACTIVITY`. It remains eligible for the legacy 56d pipeline but is invalid for baseline-subtracted VMA support.
- `06_background`: baseline observes WPS idle in the foreground. Operation clear_refs is followed by Home and background settling.
- `07_foreground`: baseline observes WPS idle in the background. Operation clear_refs is followed by bringing WPS to the foreground and settling.
- `08_reopen_saved_document`: launch WPS and wait; collect an idle baseline before opening the saved document; clear_refs again; open the document; settle; collect OPERATION.

## Process identity and pairing

Each process snapshot contains PID, PPID, UID, VSZ/RSS, args, comm, exe, `/proc/<pid>/stat` starttime, availability, role, and role rule. The stat parser locates the final `)` enclosing comm and reads field 22 from the remaining fields, so spaces and parentheses in comm are safe.

Pairing priority is `(pid, process_starttime)`. Equal PID with different available starttimes is `PID_REUSED` and is never paired. If either starttime is unavailable, equal PID may be paired as `PID_ONLY_MATCH`, but its quality is degraded. Operation-only processes are `NEW_PROCESS_NO_BASELINE`; baseline-only processes are `PROCESS_EXITED`. Their raw records remain available, but they are not valid baseline-subtracted support executions.

## File VMA pairing and split/merge allocation

A file VMA has a usable device/inode identity and a mapped interval `[file_offset_bytes, file_offset_bytes + address_size_bytes)`. Within a paired process, candidates must match device major/minor, inode, permissions, and have positive file-offset overlap. Virtual addresses are not used.

All matching baseline/operation edges are built first. For each baseline VMA, its Referenced pages are distributed across its overlapping operation edges in proportion to edge overlap length divided by the sum of its edge overlap lengths. This conservation rule prevents a baseline VMA from being deducted in full more than once. One-to-many or many-to-one components are marked `VMA_SPLIT_MERGE_APPROXIMATION`; simple one-to-one edges are `FILE_OFFSET_OVERLAP_MATCH`.

The exact key contains process role, device major/minor, inode, permissions, and the actual VMA file interval. The semantic key uses role, mapping type, normalized library identity or document role, permissions, and actual relative VMA interval. The granularity is always `FILE_VMA_OFFSET_INTERVAL`; no 256 KiB buckets are fabricated.

## Anonymous VMA pairing

Anonymous candidates are restricted to a paired process lifetime. They must match path/name, permissions, segment, and mapping type and have positive virtual-address overlap. Addresses are retained only in audit fields. Split/merge allocation uses the same conservative overlap weighting as file VMAs.

The long-term auxiliary key contains app id, process role, anonymous type/name, permissions, and a configured size bucket. It excludes PID, PFN, address, and ordinal. Every anonymous feature declares auxiliary-only usage and disables long-term page mapping, protection, and prefetch.

## Background estimate and activity

Raw baseline and operation Referenced/RSS/Size data are preserved. For a valid paired contribution:

```
baseline_rate_pages_per_s = allocated_baseline_pages / baseline_window_s
estimated_background_pages = baseline_rate_pages_per_s * operation_window_s
estimated_excess_referenced_pages = max(0, operation_referenced_pages - estimated_background_pages)
estimated_excess_rss_ratio = estimated_excess_kib / max(operation_rss_kib, page_size_kib)
```

The method name is `TIME_NORMALIZED_REFERENCED_HEURISTIC`. It is a noise estimate, not a set difference or access count.

Thresholds come only from `vma_mapping_config.json`: at least 64 excess pages is STRONG; at least 8 pages and 0.05 RSS ratio is STRONG; at least 4 pages and 0.02 is WEAK; otherwise INACTIVE.

## Quality propagation

Every sample records `collection_quality`, `process_match_quality`, `vma_match_quality`, `baseline_quality`, `window_quality`, `activity_quality`, and `identity_confidence`. Raw evidence is never discarded.

Missing/invalid JSONL or reports degrades collection quality. Baseline-not-applicable, absent baseline, PID reuse, new/exited processes, PID-only matches, overlap approximations, short windows, and window mismatches remain distinct. Activity quality is OK only when collection, process identity, baseline, and window quality permit the heuristic. Identity confidence reflects whether exact device/inode identity or only semantic/anonymous identity is available.

Cross-trial support uses only executions whose collection, baseline, process match, and activity quality are valid. Invalid or missing baseline samples are excluded from the denominator rather than counted inactive.

## Output contracts

Collector JSONL is one `homeny.vma.v1` object per VMA and includes numeric/hex addresses, page size, file interval, device numbers, inode, raw/normalized/deleted path, independent segment/mapping type, memory metrics, ratios or null, and sample wall/monotonic timestamps.

Per trial, the system writes `baseline_reports/`, `operation_reports/`, `post_launch_reports/`, and `vma_mapping/{raw_vma_samples.jsonl,paired_vma_samples.jsonl,operation_file_vma_samples.jsonl,operation_anon_vma_samples.jsonl,operation_vma_quality.json,operation_vma_summary.md}`. Across trials it writes file and anonymous mapping/support outputs plus `operation_vma_analysis.json/.md`.

The readiness report must keep `ready_for_operation_recognition=false` and `ready_for_apply=false`.

## Verification

Tests cover JSON escaping/full VMA emission, role/starttime parsing, PID lifecycle cases, file and anonymous overlap, split/merge conservation, timing normalization, activity boundaries, keys, support denominator rules, CSV compatibility, and 56d regression. Verification then proceeds through host C warnings, OpenHarmony cross compilation with binary backup/hash, HDC capability checks, collector smoke, role smoke, stage smoke, special stages, one full workflow, and three trials when device state permits.
