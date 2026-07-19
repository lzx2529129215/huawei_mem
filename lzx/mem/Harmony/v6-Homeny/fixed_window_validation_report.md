# Fixed-window validation report

## Offline verification

- `python -m pytest -q`: **95 passed**.
- All project Python files passed `py_compile`.
- `mem_analyze-v6.c` passed OpenHarmony clang with `-std=c11 -Wall -Wextra -Werror -target aarch64-linux-ohos --sysroot=... -fsyntax-only`.
- Legacy 56-dimensional regression tests still assert exactly 56 dimensions and passed in the full suite.

## Device environment

- Explicit target: `3QC0124C11000839`; it was the only online target during validation.
- Device identity: `uid=0(root)`.
- Kernel: `HongMeng Kernel 1.12.0`, aarch64.
- `/proc/1/maps`, `/proc/1/smaps`, `/proc/1/pagemap` readable; `/proc/self/clear_refs` writable.
- Local and device collector SHA256: `97c0929312e5469c9164d8ba27e641723616aaf36f114a0493f58080275f37cc`.

## Timing Smoke

The first attempt retained five accurately timed windows but failed collection because a repeated long window ID exceeded a Windows path limit. It is preserved as `fixed_window_timing_20260717_220500` and marked `COLLECTION_FAILED`.

After shortening path tokens, `fixed_window_timing_retry_20260717_184000` passed:

- Actual seconds: `5.001014, 5.010753, 5.011562, 5.003493, 5.014408`.
- Quality: 5/5 `OK`; eligible: 5/5.
- Hashes: 20/20 matched.

## Edit pilot and selected microaction

Complete logical blocks did not fit five seconds:

| Blocks | Actual seconds | Quality |
|---:|---:|---|
| 5 | 81.443 | SEVERE_OVERRUN |
| 4 | 65.659 | SEVERE_OVERRUN |
| 3 | 48.623 | SEVERE_OVERRUN |
| 2 | 31.771 | SEVERE_OVERRUN |
| 1 | 16.030 | SEVERE_OVERRUN |

Therefore there is no valid integer `blocks_per_window` for a five-second window. The selected implementation is explicitly `edit_window_mode=chunk`, `chunks_per_window=1`: four ordered safe chunks form one complete logical block.

Chunk pilot `fixed_window_chunk_pilot_20260717_190000`:

- Action seconds: `4.771, 4.759, 4.680, 2.287`.
- Actual windows: `5.000, 5.007, 5.016, 5.007`.
- 4/4 `OK`, 4/4 eligible, 32/32 hashes.
- Saved DOCX passed every metadata marker and the complete logical-block check.

The failed custom-serial pilot and overwrite-dialog evidence are retained. The corrected pilot document was independently extracted as 15/15 exact logical blocks.

## Stage04 three-trial Smoke

Each trial contains 2 baseline windows, 80 edit-chunk windows (20 complete blocks), and 2 scroll windows.

| Trial | Eligible | Quality | Hashes | DOCX |
|---|---:|---|---:|---:|
| trial01 | 84/84 | 83 OK, 1 MINOR | 672/672 | 20/20 |
| trial02 | 84/84 | 84 OK | 672/672 | 20/20 |
| trial03 | 84/84 | 82 OK, 2 MINOR | 672/672 | 20/20 |

- Operation-window eligibility in every trial: 100%, exceeding the 90% gate.
- Final accepted stage04 counts: partial 0, overrun 0, severe overrun 0.
- A first local mapping attempt for trial01 was stopped because nested raw VMA dictionaries produced multi-gigabyte duplication. All 84 raw windows were preserved; flattened derived records were rebuilt deterministically and the trial passed.
- The normal WPS close gesture left processes on this device in trials 2/3; the pre-existing force-stop fallback was used and recorded. Final residue checks found no WPS or collector process.

## Three-class small dataset

- EDIT_TEXT: 240 eligible edit-chunk windows from three stage04 trials, equivalent to 60 complete four-chunk logical-block groups.
- WRITE_METADATA: 10/10 eligible operation windows plus 2/2 baselines.
- SCROLL_DOCUMENT: 20/20 eligible operation windows plus 2/2 baselines.
- Dataset quality including baselines: 26 OK, 8 MINOR, no partial/overrun/severe, 34/34 eligible.
- Dataset hashes: 272/272 matched.

Across stage04 plus dataset:

- Total windows: 286 (10 baseline, 276 operation).
- Eligible operation windows: 276/276.
- Accepted quality: 276 OK, 10 MINOR; partial 0, overrun 0, severe 0.
- Accepted hashes: 2,288/2,288.
- File support rows: 2,407; anonymous auxiliary support rows: 346.
- Similarity rows: 113,850 (37,950 window pairs × three feature modes).

## Gates

- `ready_for_fixed_window_collection = true`
- `ready_for_stable_operation_dataset = true` (EDIT uses 60 equivalent complete-block groups; WRITE has 10 and SCROLL has 20 independent valid sample executions)
- `ready_for_operation_recognition = false`
- `ready_for_apply = false`

## Full nine-stage fixed-window run

`NOT_RUN`. The mandatory stage04 and three-class gates passed, but fixed microaction pilots for launch, new-document creation, save trigger/settle, and exact reopen have not yet been validated. Running the legacy long-window nine-stage path would not constitute a valid fixed-window result, so it was not mislabeled as one.
