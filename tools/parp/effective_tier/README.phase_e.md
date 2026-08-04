# Phase E: offline effective-tier experiment harness

This appendix defines the Phase-E stopping point:
`PARP_EFFECTIVE_TIER_LIVE_AUTH_REQUIRED`. It adds contracts and offline tools;
it does not install or boot a kernel, read live tracefs/debugfs, write a cgroup,
start memory pressure, or enable any PARP mode. No real SHADOW or APPLY result is
implied by these files.

## Data boundary

`raw_event.schema.json` covers two exported event types:

- `tier_gate_candidate`: every folio that reaches the native MGLRU tier gate,
  including native-reclaim, native-protect, and special-native-protect folios;
- `real_access`: a strictly later `PTE_YOUNG`, `MARK_ACCESSED`, or
  `FD_REFERENCE` observation for the same experiment, session, folio cookie,
  and lifetime epoch.

Native generation movement, native tier promotion, and PARP policy movement
are not real-access labels. The labels describe future access, not refault.
True refault analysis uses exported `workingset_refault_file` and
`workingset_refault_anon` counter deltas in `observability.schema.json`.

For each candidate, `collector.py` creates four posterior labels:
`reuse_within_100ms`, `reuse_within_500ms`, `reuse_within_1s`, and
`reuse_within_5s`. A negative label is emitted only when its entire future
window was observed. A truncated window is `null`; a positive real access that
arrives before truncation is still a valid positive.

`session_metadata.schema.json` supplies the independently exported session
boundary, candidate counter, and trace-loss before/after measurement. Complete
tier-gate coverage is claimed only when:

1. the measured gate-counter delta equals the number of candidate records;
2. trace loss was measured from a named source; and
3. measured trace loss is zero.

Otherwise the rows remain available for diagnostics, but the collection and
training gate is marked incomplete.

## Offline flow

All input paths must point to previously exported ordinary files. `/sys`,
`/proc`, `/dev`, and `/run` paths are rejected.

`collector.py` also accepts `--trace-text` for an already-exported text dump of
the four `parp_effective_tier_{decision,access,outcome,batch}` tracepoints. It
normalizes the numeric kernel enums, joins outcome records, ignores explicitly
non-real access/movement events, infers an access session only when the folio
cookie/lifetime has one unambiguous owner, and imports measured batch model
time. It does not open a live trace source. Session metadata remains mandatory
because a per-record trace flag cannot prove trace-buffer loss.

```sh
python3 tools/parp/effective_tier/collector.py \
  --events exported-events.jsonl \
  --sessions exported-sessions.json \
  --output-dir offline-dataset

# Equivalent input adapter for a previously exported kernel trace text file:
python3 tools/parp/effective_tier/collector.py \
  --trace-text exported-effective-tier-trace.txt \
  --sessions exported-sessions.json \
  --output-dir offline-dataset

python3 tools/parp/effective_tier/analyze.py \
  --samples offline-dataset/labeled_candidates.jsonl \
  --telemetry offline-dataset/observability.jsonl \
  --output-dir offline-analysis

python3 tools/parp/effective_tier/experiment_plan.py \
  --manifest tools/parp/effective_tier/experiment_manifest.template.json \
  --output-dir offline-plan
```

The plan renderer has no execute option and emits no shell command. Every live
matrix cell is marked `NOT_EXECUTED_PLAN_ONLY`.

## Required decisions and metrics

Special native protection is forced into the effective protected state and is
reported separately. The remaining native/effective combinations are:

| Native | Effective | Quadrant |
|---|---|---|
| reclaim | reclaim | `KEEP_RECLAIM` |
| reclaim | protect | `PREDICTIVE_UPGRADE` |
| protect | protect | `KEEP_PROTECT` |
| protect | reclaim | `PREDICTIVE_DOWNGRADE` |

Counts and rates are weighted by `folio_nr_pages`, not by folio records.
Upgrade hit/waste and downgrade mistake/cold precision are reported for all
four label windows. The offline bidirectional direction gate requires both:

- reuse among `PREDICTIVE_UPGRADE` is above `KEEP_RECLAIM`; and
- reuse among `PREDICTIVE_DOWNGRADE` is below `KEEP_PROTECT`.

The observability contract covers score/effective-tier/quadrant/batch timing,
`lru_lock` hold/wait/IRQ-disabled timing, direct and memcg reclaim, kswapd,
isolation and shrink timing, reclaim efficiency, VM/PSI/memory event deltas,
and App operation latency and failures. Analysis emits P50/P95/P99/P99.9/max
where raw latency samples exist.

## GLOBAL model training and ablations

Splits are assigned to whole sessions. An explicit session split is preserved;
otherwise the experiment and session IDs are deterministically hashed into
70% train, 15% validation, and 15% test. Page-row random splitting is rejected.

The trainer uses offline smoothed log-odds to fit and immediately quantize
integer additive lookup tables. Floating point is confined to offline analysis;
the emitted runtime candidate has only integer bias, bins, weights, and
thresholds. Training rows must come from complete SHADOW sessions. It performs exactly three
offline ablations:

1. the six real-history features without native tier;
2. those features plus `native_tier`;
3. those features plus `native_tier` and `native_tier_idx`.

Every ablation remains one `GLOBAL_REUSE_MODEL`; App, workload, and session are
reporting dimensions, never model features. The seven- and eight-feature
variants are marked offline-only because the version-1 kernel scorer has six
feature slots. They are used to decide whether native inputs merit a later,
explicitly reviewed kernel schema change, not loaded into the current kernel.
The analyzer also replays maximum upgrades of +1, +2, and +3 tiers while
retaining the -1 boundary-only downgrade rule.

## Outputs

The collector writes `labeled_candidates.jsonl`, `observability.jsonl`,
`collection_summary.json`, and `session_splits.json`. The analyzer writes:

- `tier_reclassification.json`;
- `upgrade_analysis.json` and `downgrade_analysis.json`;
- `dataset_stability.json` and `model_quality.json`;
- `global_model.json`, explicitly marked as an unselected offline candidate;
- `latency.json`, `lock_latency.json`, `reclaim_efficiency.json`,
  `app_latency.json`, and `vm_counter_deltas.json`;
- `summary.json`, which explicitly records that this tool ran no live SHADOW,
  APPLY, cgroup, or pressure action.

Run the Phase-E tests from the kernel tree root:

```sh
python3 -m unittest -v tools.parp.effective_tier.tests.test_phase_e
python3 -m compileall -q tools/parp/effective_tier
```
