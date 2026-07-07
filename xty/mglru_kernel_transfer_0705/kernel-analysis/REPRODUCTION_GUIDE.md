# MGLRU Kernel Improvement: Tier2 Watermark Reproduction Guide

## Overview

This document describes how to reproduce the improved `6.17.13-mglru` kernel from the original MGLRU Page Control kernel source. The improvement adds a **Tier2 Watermark** system for proactive memory demotion and memory tiering.

### Original Kernel (v1 - MGLRU Page Control)
- Base: Ubuntu HWE 6.17 kernel
- Feature: `/sys/kernel/debug/lru_gen_pages` interface for per-page MGLRU policy control (protect, skip, only, promote)
- All changes confined to `mm/vmscan.c`

### Improved Kernel (v2 - Tier2 Watermark)
- Adds a complete Tier2 Watermark infrastructure for memory tiering
- Node-level watermarks (alloc/demote) with sysctl configuration
- Per-memcg (cgroup) tier2 watermarks with async reclaim via workqueue
- Integration with existing memory tiers, kswapd, and demotion paths
- Sysfs, debugfs, and cgroup v1 interfaces

---

## File Inventory

### New Files (must be created)
| # | File | Description |
|---|------|-------------|
| 1 | `include/linux/tier2_watermark.h` | Tier2 watermark header (175 lines) |
| 2 | `mm/tier2_watermark.c` | Tier2 watermark implementation (1349 lines) |

### Modified Files (patches to apply)
| # | File | Changes |
|---|------|---------|
| 3 | `mm/vmscan.c` | 3 insertions: include header, demotion recording, kswapd reclaim extension |
| 4 | `mm/page_alloc.c` | 3 insertions: include header, watermark recording, 3 sysctl entries |
| 5 | `mm/memcontrol.c` | 5 insertions: include header, proactive reclaim in charge path, CSS lifecycle hooks, 8 cgroup v1 files (×3 arrays) |
| 6 | `include/linux/memcontrol.h` | 2 insertions: include header, `tier2_wmark` pointer in `struct mem_cgroup` |
| 7 | `mm/Makefile` | 1 line: `obj-$(CONFIG_TIER2_WATERMARK) += tier2_watermark.o` |
| 8 | `mm/Kconfig` | 1 block: `CONFIG_TIER2_WATERMARK` config option |

### Configuration
| # | File | Description |
|---|------|-------------|
| 9 | `config-6.17.13-mglru` | Kernel .config with `CONFIG_TIER2_WATERMARK=y` |

---

## Step-by-Step Reproduction

### Prerequisites
- Original kernel source archive: `mglru-kernel-transfer-kit.tar.zst`
- The two new files: `tier2_watermark.h` and `tier2_watermark.c` (provided alongside this guide)
- A build machine with: gcc, make, flex, bison, openssl, libelf, zstd

### Step 1: Extract the original kernel source

```bash
tar --use-compress-program=zstd -xf mglru-kernel-transfer-kit.tar.zst
cd mglru_kernel_transfer
tar --use-compress-program=zstd -xf linux-hwe-6.17.0-mglru-source.tar.zst
```

### Step 2: Create the two new tier2 files

Copy `tier2_watermark.h` to `linux-hwe-6.17-6.17.0/include/linux/tier2_watermark.h`
Copy `tier2_watermark.c` to `linux-hwe-6.17-6.17.0/mm/tier2_watermark.c`

### Step 3: Apply patches to existing files

Apply each of the following patches in order, or use `patch -p1 < patchfile`.

---

#### Patch 3a: `mm/vmscan.c` — Add tier2 header include

```
--- a/mm/vmscan.c
+++ b/mm/vmscan.c
@@ -66,6 +66,7 @@
 #include <linux/swapops.h>
 #include <linux/balloon_compaction.h>
 #include <linux/sched/sysctl.h>
+#include <linux/tier2_watermark.h>

 #include "internal.h"
 #include "swap.h"
```

#### Patch 3b: `mm/vmscan.c` — Record demotion attempts and results

Find `demote_folios_list()` (around line 1068). After the `if (target_nid == NUMA_NO_NODE) return 0;` block, add:

```
 	/* Tier2 watermark: record demotion attempt */
 	if (tier2_wmark_enabled())
 		tier2_wmark_record_demote_attempt(pgdat, 1);

```

After `migrate_pages()` call (around line 1074), add:

```
 	/* Tier2 watermark: record demotion result */
 	if (tier2_wmark_enabled() && nr_succeeded > 0) {
 		unsigned int remaining = 0;
 		struct folio *__f;
 		list_for_each_entry(__f, demote_folios, lru)
 			remaining++;
 		tier2_wmark_record_demote_result(pgdat, nr_succeeded, remaining);
 	}

```

#### Patch 3c: `mm/vmscan.c` — Extend kswapd reclaim target

Find `kswapd_shrink_node()` (around line 7480). After `sc->nr_to_reclaim += max(high_wmark_pages(zone), SWAP_CLUSTER_MAX);`:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	/* Tier2 watermark: extend reclaim target to demotion watermark */
+	if (tier2_wmark_enabled() && tier2_wmark_below_demote(pgdat)) {
+		unsigned long tier2_target =
+			tier2_wmark_demote_pages_pgdat(pgdat);
+		sc->nr_to_reclaim += max(tier2_target, (unsigned long)SWAP_CLUSTER_MAX);
+		tier2_wmark_record_reclaim_wakeup(pgdat);
+	}
+#endif
```

---

#### Patch 4a: `mm/page_alloc.c` — Add tier2 header include

```
--- a/mm/page_alloc.c
+++ b/mm/page_alloc.c
@@ -55,6 +55,7 @@
 #include <linux/delayacct.h>
 #include <linux/cacheinfo.h>
 #include <linux/pgalloc_tag.h>
+#include <linux/tier2_watermark.h>
 #include <asm/div64.h>
 #include "internal.h"
 #include "shuffle.h"
```

#### Patch 4b: `mm/page_alloc.c` — Record below-watermark events

Find `get_page_from_freelist()` (around line 4400). After the `wakeup_kswapd()` loop:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	/* Tier2 watermark: record below-watermark events */
+	if (tier2_wmark_enabled()) {
+		struct zone *__tz;
+		struct zoneref *__zr;
+		for_each_zone_zonelist_nodemask(__tz, __zr, ac->zonelist,
+						highest_zoneidx, ac->nodemask) {
+			if (managed_zone(__tz))
+				tier2_wmark_record_below(__tz->zone_pgdat);
+		}
+	}
+#endif
```

#### Patch 4c: `mm/page_alloc.c` — Add sysctl entries

Find the `vm_table[]` sysctl array (around line 6645). Add three entries before the closing:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	{
+		.procname	= "tier2_wmark_enabled",
+		.data		= &sysctl_tier2_wmark_enabled,
+		.maxlen		= sizeof(sysctl_tier2_wmark_enabled),
+		.mode		= 0644,
+		.proc_handler	= proc_dointvec_minmax,
+		.extra1		= SYSCTL_ZERO,
+		.extra2		= SYSCTL_ONE,
+	},
+	{
+		.procname	= "tier2_alloc_scale_factor",
+		.data		= &sysctl_tier2_alloc_scale_factor,
+		.maxlen		= sizeof(sysctl_tier2_alloc_scale_factor),
+		.mode		= 0644,
+		.proc_handler	= proc_dointvec_minmax,
+		.extra1		= SYSCTL_ZERO,
+		.extra2		= SYSCTL_ONE_THOUSAND,
+	},
+	{
+		.procname	= "tier2_demote_scale_factor",
+		.data		= &sysctl_tier2_demote_scale_factor,
+		.maxlen		= sizeof(sysctl_tier2_demote_scale_factor),
+		.mode		= 0644,
+		.proc_handler	= proc_dointvec_minmax,
+		.extra1		= SYSCTL_ZERO,
+		.extra2		= SYSCTL_ONE_THOUSAND,
+	},
+#endif
```

---

#### Patch 5a: `mm/memcontrol.c` — Add tier2 header include

```
--- a/mm/memcontrol.c
+++ b/mm/memcontrol.c
@@ -64,6 +64,7 @@
 #include <linux/sched/isolation.h>
 #include <linux/kmemleak.h>
 #include "internal.h"
+#include <linux/tier2_watermark.h>
 #include <net/sock.h>
 #include <net/ip.h>
 #include "slab.h"
```

#### Patch 5b: `mm/memcontrol.c` — Proactive tier2 reclaim in charge path

Find `try_charge_memcg()` (around line 2461). Inside the `do { } while` loop, after the `continue;`:

```
+#ifdef CONFIG_TIER2_WATERMARK
+		/*
+		 * Proactive tier2 reclaim: if headroom is below
+		 * demote watermark, trigger reclaim to free pages
+		 * before hitting the hard limit.
+		 */
+		tier2_wmark_memcg_check_and_reclaim(memcg);
+#endif
+
```

#### Patch 5c: `mm/memcontrol.c` — CSS lifecycle hooks

In `mem_cgroup_css_alloc()` (around line 3831), before `return &memcg->css;`:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	if (tier2_wmark_memcg_alloc(memcg))
+		pr_warn("memcg: tier2_wmark alloc failed (non-fatal)\n");
+#endif
```

In `mem_cgroup_css_free()` (around line 3910), at the beginning:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	tier2_wmark_memcg_free(memcg);
+#endif
```

#### Patch 5d: `mm/memcontrol.c` — Cgroup v1 tier2 files

Add the following 8 cgroup files to EACH of these three struct arrays:
- `mem_cgroup_legacy_files[]` (around line 4651)
- `memory_files[]` (around line 5381)
- `zswap_files[]` (around line 5568)

Before the `{ }  /* terminate */` entry in each array, add:

```
+#ifdef CONFIG_TIER2_WATERMARK
+	{
+		.name = "tier2_enabled",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_enabled_show,
+		.write = tier2_memcg_enabled_write,
+	},
+	{
+		.name = "tier2_alloc_scale",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_alloc_scale_show,
+		.write = tier2_memcg_alloc_scale_write,
+	},
+	{
+		.name = "tier2_demote_scale",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_demote_scale_show,
+		.write = tier2_memcg_demote_scale_write,
+	},
+	{
+		.name = "tier2_alloc_wmark",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_alloc_wmark_show,
+	},
+	{
+		.name = "tier2_demote_wmark",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_demote_wmark_show,
+	},
+	{
+		.name = "tier2_headroom",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_headroom_show,
+	},
+	{
+		.name = "tier2_below",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_below_show,
+	},
+	{
+		.name = "tier2_stats",
+		.flags = CFTYPE_NOT_ON_ROOT,
+		.seq_show = tier2_memcg_stats_show,
+	},
+#endif
```

---

#### Patch 6: `include/linux/memcontrol.h`

Add after the existing includes (around line 23):

```
+#include <linux/tier2_watermark.h>
```

In `struct mem_cgroup`, add a new field (around line 320, before `struct mem_cgroup_per_node`):

```
+#ifdef CONFIG_TIER2_WATERMARK
+	struct tier2_wmark_memcg *tier2_wmark;
+#endif
```

---

#### Patch 7: `mm/Makefile`

Add at the end of the file:

```
+obj-$(CONFIG_TIER2_WATERMARK) += tier2_watermark.o
```

---

#### Patch 8: `mm/Kconfig`

Add after the LRU_GEN config block (around line 1327):

```
+#
+# Tier-2 Watermark for memory tiering demotion/promotion decisions
+#
+config TIER2_WATERMARK
+	bool "Tier-2 Watermark for proactive demotion and memory tiering"
+	depends on NUMA
+	default n
+	help
+	  Add a secondary watermark system for top-tier memory nodes,
+	  enabling proactive demotion and headroom-based allocation
+	  decisions. Exposes state/stats via debugfs and sysctl.
```

---

### Step 4: Build the kernel

```bash
cd linux-hwe-6.17-6.17.0
mkdir -p ../linux-hwe-6.17-mglru-build
cp ../config-6.17.13-mglru ../linux-hwe-6.17-mglru-build/.config
make O="$PWD/../linux-hwe-6.17-mglru-build" LOCALVERSION=-mglru olddefconfig
make O="$PWD/../linux-hwe-6.17-mglru-build" LOCALVERSION=-mglru -j$(nproc)
```

### Step 5: Install and reboot

```bash
sudo make O="$PWD/../linux-hwe-6.17-mglru-build" LOCALVERSION=-mglru modules_install
sudo make O="$PWD/../linux-hwe-6.17-mglru-build" LOCALVERSION=-mglru install
sudo update-grub
sudo reboot
```

### Step 6: Verify

```bash
uname -r
# Expected: 6.17.13-mglru

# Check MGLRU page control (original feature)
ls /sys/kernel/debug/lru_gen_pages

# Check Tier2 watermark (new feature)
cat /sys/kernel/mm/tier2_watermark/state
cat /sys/kernel/debug/tier2_watermark/state
cat /sys/kernel/debug/tier2_watermark/stats

# Check tier2 sysctl
sysctl vm.tier2_wmark_enabled
sysctl vm.tier2_alloc_scale_factor
sysctl vm.tier2_demote_scale_factor

# Check per-cgroup tier2 interface
ls /sys/fs/cgroup/memory/memory.tier2_*

# Enable tier2 at runtime
echo 1 | sudo tee /proc/sys/vm/tier2_wmark_enabled
```

---

## Architecture Overview

### Tier2 Watermark Design

```
User-space tools
     │
     ├── /proc/sys/vm/tier2_wmark_enabled       (enable/disable)
     ├── /proc/sys/vm/tier2_alloc_scale_factor   (alloc watermark scale)
     ├── /proc/sys/vm/tier2_demote_scale_factor  (demote watermark scale)
     ├── /sys/kernel/mm/tier2_watermark/state    (detailed node/zone state)
     ├── /sys/kernel/debug/tier2_watermark/state  (same via debugfs)
     └── /sys/fs/cgroup/memory/<group>/memory.tier2_*  (per-memcg)
              │
              ▼
     mm/tier2_watermark.c
     ┌─────────────────────────────────────────┐
     │  Node-level watermarks                   │
     │  - alloc_wmark = max(high, managed*scale)│
     │  - demote_wmark = max(alloc, ...)        │
     │  - EWMA-based free page prediction       │
     │  - Statistics (attempt/success/fail)     │
     │                                          │
     │  Per-memcg watermarks (NEW)              │
     │  - headroom = limit - usage              │
     │  - alloc_wmark = max(PAGE, limit*scale)  │
     │  - demote_wmark = max(alloc, limit*scale) │
     │  - Async reclaim via workqueue           │
     │  - Rate limiting (1/16 trigger)          │
     └─────────────────────────────────────────┘
              │
    ┌─────────┼─────────┬──────────────────┐
    ▼         ▼         ▼                  ▼
 vmscan.c  page_alloc.c  memcontrol.c   memcontrol.h
 (kswapd,   (freelist    (charge path,   (struct
  demotion)  watermark)   CSS lifecycle)  mem_cgroup)
```

### Call Flow

1. **Allocation path** (`mm/page_alloc.c`):
   `get_page_from_freelist()` → `tier2_wmark_record_below()` → records if free_pages < watermark

2. **Demotion path** (`mm/vmscan.c`):
   `demote_folios_list()` → `tier2_wmark_record_demote_attempt()` / `tier2_wmark_record_demote_result()`

3. **Reclaim path** (`mm/vmscan.c`):
   `kswapd_shrink_node()` → `tier2_wmark_below_demote()` → extends reclaim target

4. **Charge path** (`mm/memcontrol.c`):
   `try_charge_memcg()` → `tier2_wmark_memcg_check_and_reclaim()` → async workqueue reclaim

5. **CSS lifecycle** (`mm/memcontrol.c`):
   `mem_cgroup_css_alloc()` → `tier2_wmark_memcg_alloc()`
   `mem_cgroup_css_free()` → `tier2_wmark_memcg_free()`

### Key Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `vm.tier2_wmark_enabled` | 0 | Master enable (0=off, 1=on) |
| `vm.tier2_alloc_scale_factor` | 100 | Alloc watermark as 1/10000 of managed pages (100 = 1%) |
| `vm.tier2_demote_scale_factor` | 300 | Demote watermark as 1/10000 of managed pages (300 = 3%) |
| `memory.tier2_enabled` | 0 | Per-memcg enable (overrides global for that cgroup) |
| `memory.tier2_alloc_scale` | 100 | Per-memcg alloc scale |
| `memory.tier2_demote_scale` | 300 | Per-memcg demote scale |

---

## Automated Reproduction Script

For fully automated reproduction by another Claude/Codex agent, provide:
1. The original archive: `mglru-kernel-transfer-kit.tar.zst`
2. The two new files: `tier2_watermark.h` and `tier2_watermark.c`
3. This guide (or the unified patch file)

The agent should:
1. Extract the archive
2. Extract the kernel source from the inner archive
3. Copy the two new files to the correct locations
4. Apply all the patches described above (or apply a unified `.patch` file)
5. Verify `CONFIG_TIER2_WATERMARK=y` in the config
6. Build and install the kernel

---

## Summary of Improvements

| Category | Original (MGLRU only) | Improved (MGLRU + Tier2) |
|----------|----------------------|---------------------------|
| Page-level MGLRU control | `/sys/kernel/debug/lru_gen_pages` | Same + tier2 integration |
| Memory tiering watermarks | None (only zone min/low/high) | Alloc + Demote watermarks |
| Proactive demotion | Manual policy only | Automatic based on watermarks |
| Per-cgroup control | None | 8 new cgroup v1 files |
| Statistics/observability | Policy hits only | Comprehensive node+memcg stats |
| Prediction | None | EWMA-based free page prediction |
| Async reclaim | None | Workqueue-based per-memcg reclaim |
| Sysctl configuration | None | 3 /proc/sys/vm/ entries |
