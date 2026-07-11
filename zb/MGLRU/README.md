# MGLRU Page Control + cache_ext Kernel Patch Kit

本目录保存基于 Linux 6.17 的 MGLRU 页控制、cache_ext page-cache 保护、
eBPF Markov 预测和验证材料。

当前最终内核补丁是：

```text
zb/MGLRU/merged_cache_ext.patch
```

该补丁是一次性应用到原始 Linux 内核源码树的完整 unified diff，包含：

```text
mm/vmscan.c
mm/cache_ext.c
include/linux/cache_ext.h
mm/Kconfig
mm/Makefile
```

核心逻辑：

```text
MGLRU reclaim scan cycle begins
  -> cache_ext_begin_reclaim_cycle(sc)
  -> cache_ext_bpf_predict(cycle_ctx)
  -> eBPF Markov predicts next_op once for this cycle
  -> kernel stores current_predicted_next_op

MGLRU aging/isolation folio paths
  -> cache_ext_aging_should_promote(folio) / cache_ext_can_isolate(folio)
  -> kernel matches app_id + predicted_op + dev + ino + index range
  -> hit promotes folio or skips reclaim isolation
```

eBPF 不在每个 folio 上执行 Markov。每个 folio 仍由原始 MGLRU 流程扫描，
cache_ext 只在 folio 热路径做内核侧 profile 匹配。

主要文档：

```text
zb/MGLRU/doc/cache_ext_markov_patch.md       完整补丁说明
zb/MGLRU/doc/cache_ext_markov_call_flow.md   调用流程分析
zb/MGLRU/ebpf/README.md                      eBPF 构建与验证流程
```

快速应用：

```bash
cd ~/myOsTest

SRC=$PWD/linux-hwe-6.17-6.17.0
MGLRU=$PWD/huawei_mem-master/zb/MGLRU
PATCH=$MGLRU/merged_cache_ext.patch

patch -d "$SRC" -p1 --dry-run < "$PATCH"
patch -d "$SRC" -p1 < "$PATCH"
```

推荐配置：

```bash
BUILD=$PWD/linux-hwe-6.17-cacheext-v2-build

"$SRC/scripts/config" --file "$BUILD/.config" --set-str LOCALVERSION "-cacheext-v2"
"$SRC/scripts/config" --file "$BUILD/.config" -e CACHE_EXT
"$SRC/scripts/config" --file "$BUILD/.config" -e CACHE_EXT_BPF
"$SRC/scripts/config" --file "$BUILD/.config" -e BPF
"$SRC/scripts/config" --file "$BUILD/.config" -e BPF_SYSCALL
"$SRC/scripts/config" --file "$BUILD/.config" -e DEBUG_INFO
"$SRC/scripts/config" --file "$BUILD/.config" -e DEBUG_INFO_BTF
"$SRC/scripts/config" --file "$BUILD/.config" -d DEBUG_INFO_BTF_MODULES
"$SRC/scripts/config" --file "$BUILD/.config" --set-str SYSTEM_TRUSTED_KEYS ""
"$SRC/scripts/config" --file "$BUILD/.config" --set-str SYSTEM_REVOCATION_KEYS ""

make -C "$SRC" O="$BUILD" olddefconfig
```

编译安装：

```bash
make -C "$SRC" O="$BUILD" OBJCOPY=/usr/bin/objcopy -j1
sudo make -C "$SRC" O="$BUILD" modules_install
sudo make -C "$SRC" O="$BUILD" install
sudo update-grub
sudo reboot
```

重启后基础检查：

```bash
uname -r
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
sudo cat /sys/kernel/debug/cache_ext
sudo ls -l /sys/kernel/debug/lru_gen_pages
```

期望版本：

```text
6.17.0-cacheext-v2
```
