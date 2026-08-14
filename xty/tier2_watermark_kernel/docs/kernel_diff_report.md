# Original Kernel vs Improved Kernel — Diff Report

**Original**: `mglru-kernel-transfer-kit.tar.zst` (kernel 6.17.0 + MGLRU)
**Improved**: 6.17.13 #8 (per-cgroup tier2 watermark)

---

## 1. Files Changed

| File | Status | Lines Changed |
|------|--------|---------------|
| `include/linux/tier2_watermark.h` | **NEW** | +170 lines |
| `mm/tier2_watermark.c` | **NEW** | +1800 lines |
| `include/linux/memcontrol.h` | Modified | +5 lines |
| `mm/memcontrol.c` | Modified | +40 lines |

Total: **4 files, ~2015 lines added**

---

## 2. memcontrol.h Diff

```diff
--- a/include/linux/memcontrol.h
+++ b/include/linux/memcontrol.h
@@ -24,6 +24,7 @@
 #include <linux/writeback.h>
 #include <linux/page-flags.h>
 #include <linux/shrinker.h>
+#include <linux/tier2_watermark.h>

 struct mem_cgroup;
 struct obj_cgroup;
@@ -320,6 +321,10 @@ struct mem_cgroup {
        struct list_head event_list;
        spinlock_t event_list_lock;
 #endif /* CONFIG_MEMCG_V1 */
+
+#ifdef CONFIG_TIER2_WATERMARK
+       struct tier2_wmark_memcg *tier2_wmark;
+#endif

        struct mem_cgroup_per_node *nodeinfo[];
 };
```

## 3. memcontrol.c Diff

### 3.1 Include
```diff
+#include <linux/tier2_watermark.h>
```

### 3.2 mem_cgroup_css_alloc() — Init hook
```diff
+ #ifdef CONFIG_TIER2_WATERMARK
+       if (tier2_wmark_memcg_alloc(memcg))
+               pr_warn("memcg: tier2_wmark alloc failed (non-fatal)\n");
+ #endif
        return &memcg->css;
```

### 3.3 mem_cgroup_css_free() — Cleanup hook
```diff
 static void mem_cgroup_css_free(struct cgroup_subsys_state *css)
 {
        struct mem_cgroup *memcg = mem_cgroup_from_css(css);
+ #ifdef CONFIG_TIER2_WATERMARK
+       tier2_wmark_memcg_free(memcg);
+ #endif
        int __maybe_unused i;
```

### 3.4 try_charge_memcg() → done_restock — Reclaim hook
```diff
+ #ifdef CONFIG_TIER2_WATERMARK
+               tier2_wmark_memcg_check_and_reclaim(memcg);
+ #endif
```

### 3.5 memory_files[] — Cgroup v2 registration
```diff
+ #ifdef CONFIG_TIER2_WATERMARK
+       { .name = "tier2_enabled",      .flags = CFTYPE_NOT_ON_ROOT,
+         .seq_show = tier2_memcg_enabled_show,
+         .write = tier2_memcg_enabled_write },
+       { .name = "tier2_alloc_scale",  .flags = CFTYPE_NOT_ON_ROOT,
+         .seq_show = tier2_memcg_alloc_scale_show,
+         .write = tier2_memcg_alloc_scale_write },
+       ... (8 files total)
+ #endif
        { }     /* terminate */
```

---

## 4. tier2_watermark.h (NEW)

Complete new header providing:

- `struct tier2_wmark_memcg` — per-memcg state (enabled, scales, watermarks, 6 atomic64 counters, work_struct)
- `struct tier2_wmark_stats` / `struct tier2_wmark_ewma` / `struct tier2_wmark_node` — node-level state (unchanged from original)
- Node-level API (9 functions)
- Per-memcg API (7 functions + 10 cgroup file handlers)
- Global vmstat counters (4 atomic64_t)
- Full stubs for `!CONFIG_TIER2_WATERMARK`

---

## 5. tier2_watermark.c (NEW)

Complete implementation (~1800 lines):

| Section | Lines | Content |
|---------|-------|---------|
| Node-level core | ~500 | Watermark calc, EWMA, debugfs state/stats (unchanged from original) |
| Per-memcg helpers | ~100 | limit_bytes, usage_bytes, alloc/demote_wmark_bytes, headroom_bytes |
| Per-memcg lifecycle | ~80 | alloc/free/update |
| Per-memcg check+reclaim | ~120 | tier2_wmark_memcg_check(), check_and_reclaim() |
| Workqueue reclaim | ~70 | tier2_wmark_reclaim_work_fn() |
| Cgroup v1 handlers | ~500 | 8 files × (show + write) |
| Cgroup v1 registration | ~50 | tier2_memcg_files[] + tier2_memcg_register_files() |
| Global counters | ~10 | 4 tier2_global_* definitions |

---

## 6. Conceptual Architecture Change

```
BEFORE (original):              AFTER (improved):
                                
/proc/sys/vm/tier2_*           /proc/sys/vm/tier2_*  (global, unchanged)
  ↓ global only                  ↓
node free_pages                 node free_pages
  ↓                               ↓
tier2_alloc/demote_wmark        tier2_alloc/demote_wmark
  ↓                               ↓
debugfs state/stats             debugfs state/stats (unchanged)
                                
                                /sys/fs/cgroup/<cg>/memory.tier2_*  (per-cgroup, NEW)
                                  ↓
                                memcg limit - usage = headroom
                                  ↓
                                per-memcg alloc/demote_wmark
                                  ↓
                                below_alloc / below_demote stats
                                  ↓
                                async reclaim (workqueue)
                                  ↓
                                reclaim_actual / reclaim_pages / pressure_count
                                  ↓
                                tier2_global_* counters
```
