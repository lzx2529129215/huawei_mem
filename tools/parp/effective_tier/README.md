# PARP effective-tier integer reference

This package defines the pure-integer contract for the first PARP
effective-tier implementation. It has exactly one `GLOBAL_REUSE_MODEL`, no
App/workload routing, and no generation-frontier inputs. The bundled table is
a deterministic engineering fixture for implementation and parity testing; it
is not trained or calibrated and must not be described as production quality.

The six schema-v1 inputs, in fixed order, are:

1. time since the last real access, in milliseconds;
2. previous real-access interval, in milliseconds;
3. reuse-interval EMA, in milliseconds;
4. consecutive reclaim-candidate count;
5. time in the current generation, in milliseconds;
6. access EMA in Q8.

The score is `bias + sum(weights[feature][bin])`. An edge belongs to its lower
bin. `INT64_MIN` represents a missing feature and forces an invalid result.
Version, schema, feature-count, missing-state, or score-overflow failures also
force `delta_tier_q8 = 0`, making the ordinary effective decision exactly
Native.

The Q8 policy uses `PARP_TIER_SCALE = 256` and the following fixture values:

```text
score <= -48       -> -1 tier
-48 < score < 48   ->  0 tiers
48 <= score < 96   -> +1 tier
score >= 96        -> +2 tiers
```

The strong-upgrade cap accepts +1, +2, or +3 for offline ablation. Downgrade
is capped at one tier. The final value is clamped to `[0, 3 * 256]`, and the
comparison is strict:

```text
effective_tier_q8 = clamp(native_tier * 256 + delta_tier_q8, 0, 3 * 256)
effective_protect = effective_tier_q8 > tier_idx * 256
```

The native lazy/workingset special condition remains a separate,
non-overridable protection. Large folios are counted in base pages; scoring
does not multiply their influence by treating one folio as one page. Compressed
timestamps use modulo-2^32 subtraction via `u32_elapsed()`.

Run from the kernel tree root:

```sh
python3 -m unittest -v tools.parp.effective_tier.tests.test_reference
python3 -m compileall -q tools/parp/effective_tier
```

The test suite builds `cscore.c` with `-Wall -Wextra -Werror` and compares its
GLOBAL score, all three score-to-delta mappings, Q8 clamp/strict comparison,
large-folio accounting, and u32-wrap results against deterministic Python
vectors. The oracle is standalone userspace code and does not modify or boot a
kernel.
