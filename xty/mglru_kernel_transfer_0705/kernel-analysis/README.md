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
├── tier2_watermark.patch              # Unified patch for all modified source files (~10KB)
├── mglru_kernel_transfer_0705.zip     # Complete source bundle (553MB):
│   ├── linux-hwe-6.17.0-mglru-source.tar.zst  # Original unpatched kernel source
│   ├── linux-hwe-6.17-6.17.0/                  # Full extracted source tree
│   └── ...                                      # (other original kit files)
├── new_files/
│   ├── tier2_watermark.h              # NEW — Tier2 watermark header (175 lines)
│   └── tier2_watermark.c              # NEW — Tier2 watermark implementation (1239 lines)
└── improved/                          # Reference: expected post-patch state of modified files
    ├── mm_Kconfig
    ├── mm_Makefile
    ├── include_linux_memcontrol.h
    ├── mm_vmscan.c
    ├── mm_page_alloc.c
    └── mm_memcontrol.c
```

---

## Quick Reproduction (for AI / Automated Build)

### Prerequisites

- `mglru_kernel_transfer_0705.zip` (unzipped in this directory, or already extracted)
- Linux build environment with: gcc, make, flex, bison, libssl-dev, libelf-dev, zstd

### Step 1: Extract original kernel source

```bash
unzip mglru_kernel_transfer_0705.zip
cd mglru_kernel_transfer_0705
tar --use-compress-program=zstd -xf linux-hwe-6.17.0-mglru-source.tar.zst
cd linux-hwe-6.17-6.17.0
```

### Step 2: Copy new tier2 files

```bash
cp ../../new_files/tier2_watermark.h include/linux/
cp ../../new_files/tier2_watermark.c mm/
```

### Step 3: Apply the patch (with path fix)

> **⚠️ IMPORTANT:** The patch was originally generated on a virtual machine and
> contains absolute paths (`/tmp/orig_extract/...` and `/home/xty/...`).
> These MUST be fixed before applying, otherwise `patch -p1` will fail.

```bash
# Fix patch paths from VM absolute paths → standard a/b/ prefixes
sed -i 's|/tmp/orig_extract/linux-hwe-6.17-6.17.0/|a/|g' ../../tier2_watermark.patch
sed -i 's|/home/xty/HUAWEI_PC/MGLRU_TEST/mglru_kernel_transfer_0705/linux-hwe-6.17-6.17.0/|b/|g' ../../tier2_watermark.patch

# Verify the fix worked (should show "a/mm/Kconfig" not "/tmp/orig_extract/...")
head -7 ../../tier2_watermark.patch

# Apply the patch
patch -p1 --dry-run < ../../tier2_watermark.patch   # dry-run first to verify
patch -p1 < ../../tier2_watermark.patch               # actual apply
```

### Step 4: Build

```bash
# We are in: kernel-analysis/mglru_kernel_transfer_0705/linux-hwe-6.17-6.17.0/
# Config is in: ../../config-6.17.13-mglru
mkdir -p ../build
cp ../../config-6.17.13-mglru ../build/.config
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

### Known Patch Issues

1. **Duplicate `#include` in `memcontrol.c`**: The patch adds `#include <linux/tier2_watermark.h>` twice at lines 67-68. This is **harmless** (the include guard `_LINUX_TIER2_WATERMARK_H` prevents double inclusion) but not ideal. To clean up, delete one of the duplicate lines after patching.

2. **Absolute VM paths in patch headers**: See the sed fix in **Step 3**. Without this fix, `patch -p1` will fail with "can't find file to patch".

---

## Troubleshooting

### "can't find file to patch" when applying tier2_watermark.patch

**Cause:** The patch was generated on a VM with absolute paths like `/tmp/orig_extract/linux-hwe-6.17-6.17.0/mm/Kconfig` instead of the standard `a/mm/Kconfig`.

**Fix:** Run the `sed` commands from **Step 3** to replace the absolute paths:

```bash
sed -i 's|/tmp/orig_extract/linux-hwe-6.17-6.17.0/|a/|g' tier2_watermark.patch
sed -i 's|/home/xty/HUAWEI_PC/MGLRU_TEST/mglru_kernel_transfer_0705/linux-hwe-6.17-6.17.0/|b/|g' tier2_watermark.patch
```

After fixing, verify with `head -7 tier2_watermark.patch` — the first diff header should show `--- a/mm/Kconfig`, NOT an absolute path.

### "This does not look like a tar archive" on extracted .tar.zst

**Cause:** The `.tar.zst` file was decompressed incorrectly (e.g., using `tar -xf` without `--use-compress-program=zstd`, or piping through a broken pipeline).

**Fix:**

```bash
# Correct way — let tar invoke zstd internally:
tar --use-compress-program=zstd -xf linux-hwe-6.17.0-mglru-source.tar.zst

# Or decompress first, then extract:
zstd -d linux-hwe-6.17.0-mglru-source.tar.zst -o source.tar
tar -xf source.tar
```

### Build fails with "CONFIG_TIER2_WATERMARK" not found

**Cause:** The patch was not applied before building.

**Fix:** Ensure **Step 3** completed successfully (the dry-run should list "checking file ..." for all 6 files). If it was skipped, the Kconfig won't have the `TIER2_WATERMARK` option and the build config will fail `olddefconfig`.

### Want to verify the patch produced correct output

Compare your patched files against the reference copies in `improved/`:

```bash
diff mm/Kconfig ../../improved/mm_Kconfig
diff mm/Makefile ../../improved/mm_Makefile
diff mm/vmscan.c ../../improved/mm_vmscan.c
diff mm/page_alloc.c ../../improved/mm_page_alloc.c
diff mm/memcontrol.c ../../improved/mm_memcontrol.c
diff include/linux/memcontrol.h ../../improved/include_linux_memcontrol.h
```

No output = files match the expected post-patch state (what built the working kernel).

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
