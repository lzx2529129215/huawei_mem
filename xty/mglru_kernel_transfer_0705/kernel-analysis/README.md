# MGLRU Kernel with Tier2 Watermark — Reproduction Kit

## Overview

This kit contains everything needed to reproduce the improved `6.17.13-mglru` kernel with **Tier2 Watermark** support from the original MGLRU Page Control kernel source.

### Features

| Feature                   | Description                                                  |
| ------------------------- | ------------------------------------------------------------ |
| **MGLRU Page Control**    | `/sys/kernel/debug/lru_gen_pages` — per-page protect/skip/only/promote policies |
| **Tier2 Node Watermarks** | alloc_wmark + demote_wmark at node granularity via `/proc/sys/vm/tier2_*` |
| **Per-memcg Tier2**       | 8 `memory.tier2_*` cgroup files for per-container watermark control |
| **Async Reclaim**         | Workqueue-driven proactive reclaim on memory charge path     |
| **EWMA Prediction**       | Exponential Weighted Moving Average for free page prediction |
| **Demotion Statistics**   | Full attempt/success/failure tracking per NUMA node          |

### Known Limitations

1. **NUMA required** — `CONFIG_TIER2_WATERMARK` depends on NUMA. On single-node systems no demotion occurs.
2. **Memory tiers needed for demotion** — `next_demotion_node()` returns `NUMA_NO_NODE` without multi-tier memory (e.g., DRAM + CXL/PMEM).
3. **Cgroup v1 only for per-memcg** — The per-memcg tier2 files use cgroup v1 interface. For v2, the same files appear via `memory_files[]` (`.dfl_cftypes`).
4. **Promotion not implemented** — `promotion_hint/success` counters exist but are always 0; only demotion/watermark detection is implemented.
5. **Per-memcg reclaim is async** — Workqueue-based, not immediate. Subject to rate limiting (1/16 triggers).

---

## File Inventory

```
kernel-analysis/
├── README.md                          # This file
├── config-6.17.13-mglru               # Kernel .config with CONFIG_TIER2_WATERMARK=y
├── tier2_watermark.patch              # Unified patch for all modified source files (393 lines)
├── new_files/
│   ├── tier2_watermark.h              # NEW — Tier2 watermark header (175 lines)
│   └── tier2_watermark.c              # NEW — Tier2 watermark implementation (1239 lines)
├── original/                          # Original MGLRU kernel transfer kit
│   └── mglru-kernel-transfer-kit.tar.zst
└── diffs/                             # Per-file diffs for reference (optional)
```

---

## Quick Reproduction (for AI / Automated Build)

### Prerequisites

- Original kernel source archive: `original/mglru-kernel-transfer-kit.tar.zst`
- Linux build environment with: gcc, make, flex, bison, libssl-dev, libelf-dev, zstd

### Step 1: Extract original kernel source

```bash
tar --use-compress-program=zstd -xf original/mglru-kernel-transfer-kit.tar.zst
cd mglru_kernel_transfer
tar --use-compress-program=zstd -xf linux-hwe-6.17.0-mglru-source.tar.zst
cd linux-hwe-6.17-6.17.0
```

### Step 2: Copy new tier2 files

```bash
cp ../new_files/tier2_watermark.h include/linux/
cp ../new_files/tier2_watermark.c mm/
```

### Step 3: Apply the patch

```bash
patch -p1 < ../tier2_watermark.patch
```

### Step 4: Build

```bash
mkdir -p ../build
cp ../config-6.17.13-mglru ../build/.config
make O=../build LOCALVERSION=-mglru olddefconfig
make O=../build LOCALVERSION=-mglru -j$(nproc)
```

### Step 5: Install and reboot

```bash
sudo make O=../build LOCALVERSION=-mglru modules_install
sudo make O=../build LOCALVERSION=-mglru install
sudo update-grub
sudo reboot
```

### Step 6: Verify

```bash
uname -r                          # Expected: 6.17.13-mglru

# MGLRU page control (original)
ls /sys/kernel/debug/lru_gen_pages

# Tier2 watermark (new)
ls /sys/kernel/mm/tier2_watermark/
cat /sys/kernel/debug/tier2_watermark/state
cat /sys/kernel/debug/tier2_watermark/stats

# Tier2 sysctl
sysctl vm.tier2_wmark_enabled
sysctl vm.tier2_alloc_scale_factor
sysctl vm.tier2_demote_scale_factor

# Enable
echo 1 | sudo tee /proc/sys/vm/tier2_wmark_enabled

# Per-memcg (cgroup v1)
ls /sys/fs/cgroup/memory/memory.tier2_*
```

---

## What Changed from Original

### New Files (2)

| File                              | Lines | Description                                                  |
| --------------------------------- | ----- | ------------------------------------------------------------ |
| `include/linux/tier2_watermark.h` | 175   | Tier2 structs, function declarations, stubs                  |
| `mm/tier2_watermark.c`            | 1239  | Full implementation: watermarks, EWMA, per-memcg, sysfs, debugfs |

### Modified Files (6)

| File                         | Change Summary                                               |
| ---------------------------- | ------------------------------------------------------------ |
| `mm/Kconfig`                 | Added `CONFIG_TIER2_WATERMARK` (NUMA dependency)             |
| `mm/Makefile`                | Added `obj-$(CONFIG_TIER2_WATERMARK) += tier2_watermark.o`   |
| `include/linux/memcontrol.h` | Added `#include <linux/tier2_watermark.h>` and `struct tier2_wmark_memcg *tier2_wmark` to `struct mem_cgroup` |
| `mm/vmscan.c`                | Added tier2 include, demotion recording, kswapd reclaim extension |
| `mm/page_alloc.c`            | Added tier2 include, watermark recording in freelist path, 3 sysctl entries |
| `mm/memcontrol.c`            | Added tier2 include, proactive reclaim in charge path, CSS alloc/free hooks, cgroup file definitions in `memory_files[]`, `mem_cgroup_legacy_files[]`, and `zswap_files[]` |

### Fixed from VM Source (cleaned)

The VM's source had 4 issues that were cleaned:

1. Duplicate SPDX/import block in `tier2_watermark.c` — removed
2. Duplicate `#include <linux/tier2_watermark.h>` in `memcontrol.h` — removed
3. Duplicate `tier2_wmark_memcg_alloc()` call in `memcontrol.c` — removed
4. Redundant `tier2_memcg_register_files()` function — removed (files already registered via `memory_files[]`/`mem_cgroup_legacy_files[]` in memcontrol.c)

---

## Runtime Interfaces

### Sysctl (`/proc/sys/vm/`)

| Name                        | Default | Range  | Description                                                 |
| --------------------------- | ------- | ------ | ----------------------------------------------------------- |
| `tier2_wmark_enabled`       | 0       | 0-1    | Master enable switch                                        |
| `tier2_alloc_scale_factor`  | 100     | 0-1000 | Alloc watermark = managed_pages * scale / 10000 (100 = 1%)  |
| `tier2_demote_scale_factor` | 300     | 0-1000 | Demote watermark = managed_pages * scale / 10000 (300 = 3%) |

### DebugFS (`/sys/kernel/debug/tier2_watermark/`)

| File    | Permission | Description                                        |
| ------- | ---------- | -------------------------------------------------- |
| `state` | 0444       | Per-node/zone detailed state with EWMA predictions |
| `stats` | 0444       | Cumulative per-node statistics                     |

### Cgroup v1 (`/sys/fs/cgroup/memory/<group>/`)

| File                        | Permission | Description                               |
| --------------------------- | ---------- | ----------------------------------------- |
| `memory.tier2_enabled`      | 0644       | Per-cgroup tier2 enable                   |
| `memory.tier2_alloc_scale`  | 0644       | Per-cgroup alloc scale                    |
| `memory.tier2_demote_scale` | 0644       | Per-cgroup demote scale                   |
| `memory.tier2_alloc_wmark`  | 0444       | Current alloc watermark (bytes)           |
| `memory.tier2_demote_wmark` | 0444       | Current demote watermark (bytes)          |
| `memory.tier2_headroom`     | 0444       | limit - current_usage (bytes)             |
| `memory.tier2_below`        | 0444       | "alloc=X,demote=Y" below-watermark status |
| `memory.tier2_stats`        | 0444       | Full per-memcg statistics                 |
