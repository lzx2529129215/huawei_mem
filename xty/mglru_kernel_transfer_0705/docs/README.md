# MGLRU Kernel — Per-Cgroup Tier2 Watermark Improvement Kit

**Version**: 6.17.13 #8 (2026-07-06)

## What This Is

Based on the original `mglru-kernel-transfer-kit.tar.zst` (kernel 6.17.0 + MGLRU patches),
this kit upgrades the tier2 watermark from node-level to **per-cgroup** (per-memcg).

## Quick Apply

```bash
# 1. Extract original kernel
tar --use-compress-program=zstd -xf mglru-kernel-transfer-kit.tar.zst
cd linux-hwe-6.17-6.17.0

# 2. Apply patches
cp ../ADD/patches/tier2_watermark.h include/linux/
cp ../ADD/patches/tier2_watermark.c mm/
patch -p1 < ../ADD/patches/memcontrol.h.patch
patch -p1 < ../ADD/patches/memcontrol.c.patch

# 3. Build
echo "CONFIG_TIER2_WATERMARK=y" >> ../linux-hwe-6.17-mglru-build/.config
cd ../linux-hwe-6.17-mglru-build
make olddefconfig
make -j4
sudo make modules_install install
sudo reboot
```

## Quick Test

```bash
sudo mkdir /sys/fs/cgroup/memory/test
echo 128M | sudo tee /sys/fs/cgroup/memory/test/memory.limit_in_bytes
echo 1 | sudo tee /sys/fs/cgroup/memory/test/memory.tier2_enabled
sudo cat /sys/fs/cgroup/memory/test/memory.tier2_stats
```

## Per-Cgroup Files

| File | Type | Description |
|------|------|-------------|
| memory.tier2_enabled | RW | Enable per-memcg tier2 |
| memory.tier2_alloc_scale | RW | Alloc coefficient (1/10000) |
| memory.tier2_demote_scale | RW | Demote coefficient (1/10000) |
| memory.tier2_alloc_wmark | RO | Alloc watermark (bytes) |
| memory.tier2_demote_wmark | RO | Demote watermark (bytes) |
| memory.tier2_headroom | RO | limit - usage (bytes) |
| memory.tier2_below | RO | alloc=X,demote=Y status |
| memory.tier2_stats | RO | Full statistics |
