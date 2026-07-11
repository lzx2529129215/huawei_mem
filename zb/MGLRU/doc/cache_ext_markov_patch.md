# merged_cache_ext.patch 说明

本文档解释 `zb/MGLRU/merged_cache_ext.patch` 的设计目标、补丁内容、使用顺序和验证方法。

## 1. 补丁定位

`merged_cache_ext.patch` 是基于 Linux 6.17 的完整 unified diff。

它必须直接应用到原始 Linux 内核源码树，而不是应用到已经打过旧增量补丁的源码树。

应用顺序：

```text
Linux 6.17 原始源码
    -> merged_cache_ext.patch
```

该补丁已经合并：

```text
MGLRU page control debugfs 接口
cache_ext page-cache profile 匹配
reclaim-cycle 级别 eBPF Markov 预测
debugfs 配置和统计字段
```

## 2. 总体目标

`cache_ext` 是一个应用预测驱动的 page-cache 保护框架。

用户态负责：

```text
读取 Markov 转移表
维护最近 4 个操作历史
加载 eBPF policy
同步 page profile 到内核 debugfs
```

内核负责：

```text
在每轮 MGLRU reclaim cycle 开始时调用一次 eBPF Markov 预测
保存 current_predicted_next_op
在 aging/isolation folio 路径中匹配 file-backed page cache profile
命中时 promote 或跳过 reclaim isolation
```

当前 eBPF 不是 per-folio Markov 判断。

## 3. 补丁包含的文件

`merged_cache_ext.patch` 包含以下内核修改：

```text
mm/vmscan.c                    MGLRU page control + cache_ext hook
include/linux/cache_ext.h      cache_ext 对外声明和 BPF 上下文结构
mm/cache_ext.c                 debugfs、profile 匹配、BPF cycle 预测和统计
mm/Kconfig                     CONFIG_CACHE_EXT / CONFIG_CACHE_EXT_BPF
mm/Makefile                    编译 cache_ext.o
```

eBPF 用户态和 BPF 程序不在内核补丁内，位于：

```text
zb/MGLRU/ebpf/cache_ext_policy.bpf.c
zb/MGLRU/ebpf/cache_ext_bpf_common.h
zb/MGLRU/ebpf/cache_ext_loader.py
zb/MGLRU/ebpf/cache_ext_libbpf_loader.c
```

## 4. 核心数据结构

内核 profile 表表示一段 file-backed page cache 范围：

```c
struct cache_ext_page_profile {
	u16 app_id;
	u16 op_id;
	u32 dev_major;
	u32 dev_minor;
	unsigned long ino;
	unsigned long index_start;
	unsigned long index_end;
	u16 priority;
	bool valid;
};
```

profile 含义：

```text
app_id + op_id + dev_major + dev_minor + ino + index_start/index_end
```

folio 匹配不使用 pathname，而使用：

```text
folio -> mapping -> inode
inode superblock dev
inode number
folio index range
```

这样 reclaim 热路径不需要路径解析和字符串匹配。

## 5. debugfs 接口

新增接口：

```text
/sys/kernel/debug/cache_ext
```

常用命令：

```bash
echo "enable 1" | sudo tee /sys/kernel/debug/cache_ext
echo "enable 0" | sudo tee /sys/kernel/debug/cache_ext

echo "policy builtin" | sudo tee /sys/kernel/debug/cache_ext
echo "policy bpf" | sudo tee /sys/kernel/debug/cache_ext
echo "bpf enable 1" | sudo tee /sys/kernel/debug/cache_ext
echo "bpf enable 0" | sudo tee /sys/kernel/debug/cache_ext

echo "app 4" | sudo tee /sys/kernel/debug/cache_ext
echo "predicted_op 4 22" | sudo tee /sys/kernel/debug/cache_ext

echo "profile add 4 22 8 3 1234567 0 128 1" | sudo tee /sys/kernel/debug/cache_ext
echo "profile clear" | sudo tee /sys/kernel/debug/cache_ext

echo "clear" | sudo tee /sys/kernel/debug/cache_ext
```

命令含义：

```text
enable <0|1>
    开启或关闭 cache_ext。

policy builtin
    使用 debugfs 手动 predicted_op 模式。

policy bpf
    使用 eBPF reclaim-cycle Markov 预测模式。

bpf enable <0|1>
    开启或关闭 BPF 预测调用。

app <app_id>
    设置当前 app_id。

predicted_op <app_id> <op_id>
    手动设置当前预测操作。

profile add <app_id> <op_id> <dev_major> <dev_minor> <ino> <index_start> <index_end> <priority>
    添加一条操作到 page cache 范围的映射。

profile clear
    清空 profile 表。

clear
    清空状态和统计。
```

读取接口：

```bash
sudo cat /sys/kernel/debug/cache_ext
```

关键字段：

```text
cache_ext enabled
app_id
policy_mode
bpf_supported
bpf_enabled
cycle_seq
current_predicted_next_op
profiles

predicted_updates
cycle_refreshes
active_hint_updates
profile_hits
protected_folios
skipped_reclaim
aging_calls
aging_hits
aging_promoted
bpf_predict_calls
bpf_predict_hits
bpf_predict_miss
bpf_predict_errors
```

## 6. MGLRU hook 行为

### 6.1 reclaim-cycle 预测入口

在 `isolate_folios()` 开始处：

```c
#ifdef CONFIG_CACHE_EXT
	cache_ext_begin_reclaim_cycle(sc);
#endif
```

该入口每轮 reclaim scan 调用一次。

在 BPF 模式下：

```text
cache_ext_begin_reclaim_cycle()
    -> cache_ext_bpf_predict(cycle_ctx)
    -> 更新 predicted_next_op
```

### 6.2 aging promote 路径

在 MGLRU aging/look-around 路径中：

```c
if (cache_ext_aging_should_promote(folio)) {
	gen = mglru_promote_folio_locked(lruvec, folio);
	...
}
```

命中 profile 后，folio 被提升到较新的 generation。

### 6.3 reclaim isolation 路径

在 `isolate_folio()` 中：

```c
if (!cache_ext_can_isolate(folio))
	return false;
```

命中 profile 后，folio 不进入 isolate/reclaim。

## 7. 匹配规则

`cache_ext_aging_should_promote()` 和 `cache_ext_can_isolate()` 只保护 file-backed folio。

以下情况不保护：

```text
cache_ext 未启用
predicted_next_op 为 0
folio 是 swap-backed
folio_mapping(folio) 为空
mapping->host 为空
inode->i_sb 为空
没有匹配 profile
```

命中条件：

```text
profile.valid == true
profile.app_id == 当前 app_id
profile.op_id == current_predicted_next_op
profile.dev_major/dev_minor == inode superblock dev
profile.ino == inode->i_ino
folio index range 与 profile index range 有交集
```

folio 范围：

```text
folio_start = folio->index
folio_end   = folio->index + folio_nr_pages(folio) - 1
```

交集：

```text
folio_start <= profile.index_end &&
folio_end >= profile.index_start
```

## 8. 统计语义

aging 阶段命中：

```text
aging_calls        +1
profile_hits       +1
protected_folios   +1
aging_hits         +1
aging_promoted     +1（实际完成提升后）
```

reclaim 阶段命中：

```text
profile_hits       +1
protected_folios   +1
skipped_reclaim    +1
```

BPF reclaim-cycle 预测成功：

```text
cycle_refreshes       +1
bpf_predict_calls     +1
bpf_predict_hits      +1
predicted_updates     +1
active_hint_updates   +1
```

debugfs 手动设置 predicted_op：

```text
predicted_updates     +1
active_hint_updates   +1
```

## 9. 应用补丁

```bash
cd ~/myOsTest

SRC=$PWD/linux-hwe-6.17-6.17.0
MGLRU=$PWD/huawei_mem-master/zb/MGLRU
PATCH=$MGLRU/merged_cache_ext.patch

patch -d "$SRC" -p1 --dry-run < "$PATCH"
echo $?
patch -d "$SRC" -p1 < "$PATCH"
```

成功标准：

```text
0
```

确认 `cache_ext_begin_reclaim_cycle(sc)` 位置：

```bash
grep -n "static int isolate_folios" "$SRC/mm/vmscan.c"
grep -n "cache_ext_begin_reclaim_cycle(sc)" "$SRC/mm/vmscan.c"
```

## 10. 内核配置

```bash
cd ~/myOsTest

SRC=$PWD/linux-hwe-6.17-6.17.0
BUILD=$PWD/linux-hwe-6.17-cacheext-v2-build

cp ~/myOsTest/huawei_mem-master/zb/MGLRU/config-6.17.13-mglru "$BUILD/.config"

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

检查：

```bash
grep CONFIG_CACHE_EXT "$BUILD/.config"
grep CONFIG_CACHE_EXT_BPF "$BUILD/.config"
grep -E "CONFIG_BPF=|CONFIG_BPF_SYSCALL=|CONFIG_DEBUG_INFO=|CONFIG_DEBUG_INFO_BTF=" "$BUILD/.config"
grep -E "SYSTEM_TRUSTED_KEYS|SYSTEM_REVOCATION_KEYS" "$BUILD/.config"
grep -E "CONFIG_DEBUG_INFO_BTF_MODULES" "$BUILD/.config"
```

期望：

```text
CONFIG_CACHE_EXT=y
CONFIG_CACHE_EXT_BPF=y
CONFIG_BPF=y
CONFIG_BPF_SYSCALL=y
CONFIG_DEBUG_INFO=y
CONFIG_DEBUG_INFO_BTF=y
# CONFIG_DEBUG_INFO_BTF_MODULES is not set
CONFIG_SYSTEM_TRUSTED_KEYS=""
CONFIG_SYSTEM_REVOCATION_KEYS=""
```

## 11. 编译与安装

如果链接阶段出现：

```text
LD .tmp_vmlinux1
Killed
Error 137
```

说明是 OOM，可启用额外 swap：

```bash
swapon --show
free -h
sudo chmod 600 /swapfile2
sudo swapon /swapfile2
swapon --show
free -h
```

完整增量编译：

```bash
make -C "$SRC" O="$BUILD" OBJCOPY=/usr/bin/objcopy -j1 2>&1 | tee -a ~/myOsTest/build-cacheext-v2.log
```

只重编内核镜像：

```bash
make -C "$SRC" O="$BUILD" OBJCOPY=/usr/bin/objcopy -j1 bzImage 2>&1 | tee -a ~/myOsTest/build-cacheext-v2.log
```

安装：

```bash
sudo make -C "$SRC" O="$BUILD" modules_install
sudo make -C "$SRC" O="$BUILD" install
sudo update-grub
sudo reboot
```

重启后：

```bash
uname -r
```

期望：

```text
6.17.0-cacheext-v2
```

## 12. 启动后验证

```bash
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true

sudo ls -l /sys/kernel/debug/cache_ext
sudo ls -l /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/cache_ext

sudo grep cache_ext /proc/kallsyms | head -n 40
sudo grep cache_ext_bpf_predict /proc/kallsyms

cat /sys/kernel/mm/lru_gen/enabled
cat /sys/kernel/mm/lru_gen/min_ttl_ms
```

关键符号：

```text
cache_ext_bpf_predict
cache_ext_begin_reclaim_cycle
cache_ext_can_isolate
cache_ext_aging_should_promote
```

## 13. reclaim 保护路径验证

```bash
CE=/sys/kernel/debug/cache_ext
TEST=/home/gaia/myOsTest/linux-hwe-6.17-cacheext-v2-build/vmlinux

read MAJ MIN INO PAGES < <(python3 - <<'PY'
import os
p=os.path.expanduser("~/myOsTest/linux-hwe-6.17-cacheext-v2-build/vmlinux")
st=os.stat(p)
pages=st.st_size // os.sysconf("SC_PAGE_SIZE") - 1
print(os.major(st.st_dev), os.minor(st.st_dev), st.st_ino, pages)
PY
)

echo "clear" | sudo tee "$CE"
echo "enable 1" | sudo tee "$CE"
echo "app 4" | sudo tee "$CE"
echo "policy builtin" | sudo tee "$CE"
echo "bpf enable 0" | sudo tee "$CE"
echo "profile clear" | sudo tee "$CE"
echo "profile add 4 22 $MAJ $MIN $INO 0 $PAGES 1" | sudo tee "$CE"
echo "predicted_op 4 22" | sudo tee "$CE"

sudo cat "$CE"
```

使用 cgroup 触发 reclaim：

```bash
CE=/sys/kernel/debug/cache_ext
CG=/sys/fs/cgroup/cacheext_test

sudo mkdir -p "$CG"
echo 900M | sudo tee "$CG/memory.max"
echo 0 | sudo tee "$CG/memory.swap.max" 2>/dev/null || true

sync
echo 3 | sudo tee /proc/sys/vm/drop_caches

sudo bash -c '
echo $$ > /sys/fs/cgroup/cacheext_test/cgroup.procs

dd if=/home/gaia/myOsTest/linux-hwe-6.17-cacheext-v2-build/vmlinux of=/dev/null bs=4M status=progress

python3 - <<PY
import time
chunks = []
try:
    for i in range(700):
        chunks.append(bytearray(1024 * 1024))
        if i % 100 == 0:
            print("allocated", i, "MB")
        time.sleep(0.003)
except MemoryError:
    print("MemoryError")
time.sleep(2)
PY
'

sudo cat "$CE"
```

成功证据：

```text
profile_hits: 17711
protected_folios: 17711
skipped_reclaim: 17711
```

## 14. eBPF / Markov 自动预测验证

详细流程见：

```text
zb/MGLRU/ebpf/README.md
```

关键成功状态：

```text
policy_mode: bpf
bpf_enabled: 1
current_predicted_next_op: 22
bpf_predict_calls: 305
bpf_predict_hits: 305
bpf_predict_miss: 0
bpf_predict_errors: 0
```

## 15. 当前边界

当前版本不实现：

```text
内核侧 Markov 训练
内核侧 CSV 解析
pathname 匹配
匿名页、heap、stack、swap-backed page 保护
per-folio BPF Markov 决策
```

当前版本只保护能够取得 `mapping` 和 `inode` 的 file-backed page cache folio。
