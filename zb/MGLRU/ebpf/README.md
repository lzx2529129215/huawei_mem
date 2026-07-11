# cache_ext eBPF policy mode

This directory contains the userspace and eBPF pieces for the optional
`CONFIG_CACHE_EXT_BPF` policy mode used by:

```text
zb/MGLRU/merged_cache_ext.patch
```

The kernel patch provides `cache_ext_bpf_predict()` as a reclaim-cycle BPF
attach point. The active eBPF program predicts one `next_op` per MGLRU reclaim
cycle. Folio hot paths use kernel-side profile hints and do not call BPF.

## Runtime Path

```text
MGLRU reclaim scan cycle begins
  -> cache_ext_begin_reclaim_cycle(sc)
  -> cache_ext_bpf_predict(cycle_ctx)
  -> eBPF reads history_map + markov_map
  -> returns predicted next_op, or 0 for no prediction
  -> kernel stores current_predicted_next_op

MGLRU aging/isolation folio paths
  -> cache_ext_aging_should_promote(folio) / cache_ext_can_isolate(folio)
  -> kernel matches app_id + current_predicted_next_op + dev + ino + index range
  -> hit promotes folio or skips reclaim isolation
```

The active eBPF program receives only `struct cache_ext_bpf_cycle_ctx`. It never
reads `struct folio` directly and never compares file page ranges.

`cache_ext_bpf_decide` exists only as a compatibility stub:

```text
fmod_ret/cache_ext_bpf_decide -> return 0
```

## Maps

`history_map`

```text
key:   app_id
value: last 4 operation ids
```

The loader updates this map when operation events arrive or when `--set-history`
is used for deterministic testing.

`markov_map`

```text
key:   app_id + ctx[4]
value: top-1 next_op + count
```

The loader parses:

```text
zb/MGLRU/generated/cache_ext_markov_transition.csv
```

For duplicate `app_id + ctx0 + ctx1 + ctx2 + ctx3` rows, the loader keeps the
row with the largest `count`. The `prob` column is ignored at runtime.

`profile_map`

```text
key:   app_id + op_id + dev_major + dev_minor + ino
value: index_start + index_end + priority
```

This map is retained for compatibility and inspection. The active folio keep
decision uses the kernel debugfs profile table. The loader synchronizes
`generated/cache_ext_page_profile.csv` into `/sys/kernel/debug/cache_ext` with
`profile add ...` commands.

## Builtin Policy

The builtin path remains available without eBPF:

```bash
CE=/sys/kernel/debug/cache_ext

echo "clear" | sudo tee "$CE"
echo "enable 1" | sudo tee "$CE"
echo "app 4" | sudo tee "$CE"
echo "policy builtin" | sudo tee "$CE"
echo "bpf enable 0" | sudo tee "$CE"
echo "predicted_op 4 22" | sudo tee "$CE"
echo "profile add 4 22 8 3 1234567 0 128 1" | sudo tee "$CE"
```

After `predicted_op`, expected counters include:

```text
predicted_updates: 1
active_hint_updates: 1
```

## Build And Test

This is the current end-to-end process for the cycle-level Markov
implementation.

### 1. Apply Kernel Patch

Use the final merged patch so the kernel tree is patched in one step:

```bash
cd ~/myOsTest

SRC=$PWD/linux-hwe-6.17-6.17.0
MGLRU=$PWD/huawei_mem-master/zb/MGLRU
PATCH=$MGLRU/merged_cache_ext.patch

patch -d "$SRC" -p1 --dry-run < "$PATCH"
echo $?
patch -d "$SRC" -p1 < "$PATCH"
```

Expected dry-run result:

```text
0
```

Confirm the cycle hook is in `isolate_folios()`:

```bash
grep -n "static int isolate_folios" "$SRC/mm/vmscan.c"
grep -n "cache_ext_begin_reclaim_cycle(sc)" "$SRC/mm/vmscan.c"
```

### 2. Configure Kernel

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

Quick config check:

```bash
grep CONFIG_CACHE_EXT "$BUILD/.config"
grep CONFIG_CACHE_EXT_BPF "$BUILD/.config"
grep -E "CONFIG_BPF=|CONFIG_BPF_SYSCALL=|CONFIG_DEBUG_INFO=|CONFIG_DEBUG_INFO_BTF=" "$BUILD/.config"
grep -E "SYSTEM_TRUSTED_KEYS|SYSTEM_REVOCATION_KEYS" "$BUILD/.config"
grep -E "CONFIG_DEBUG_INFO_BTF_MODULES" "$BUILD/.config"
```

Expected:

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

### 3. Build And Install Kernel

If final linking is killed with `Error 137`, enable more swap first:

```bash
swapon --show
free -h
sudo chmod 600 /swapfile2
sudo swapon /swapfile2
swapon --show
free -h
```

Full incremental build:

```bash
make -C "$SRC" O="$BUILD" OBJCOPY=/usr/bin/objcopy -j1 2>&1 | tee -a ~/myOsTest/build-cacheext-v2.log
```

When only built-in kernel files such as `mm/cache_ext.c` changed, rebuilding
`bzImage` is enough:

```bash
make -C "$SRC" O="$BUILD" OBJCOPY=/usr/bin/objcopy -j1 bzImage 2>&1 | tee -a ~/myOsTest/build-cacheext-v2.log
```

Success marker:

```text
Kernel: arch/x86/boot/bzImage is ready
```

Install:

```bash
sudo make -C "$SRC" O="$BUILD" modules_install
sudo make -C "$SRC" O="$BUILD" install
sudo update-grub
sudo reboot
```

After reboot:

```bash
uname -r
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
sudo cat /sys/kernel/debug/cache_ext
```

Expected release:

```text
6.17.0-cacheext-v2
```

### 4. Basic Runtime Checks

```bash
sudo ls -l /sys/kernel/debug/cache_ext
sudo ls -l /sys/kernel/debug/lru_gen_pages
sudo grep cache_ext /proc/kallsyms | head -n 40
sudo grep cache_ext_bpf_predict /proc/kallsyms
cat /sys/kernel/mm/lru_gen/enabled
cat /sys/kernel/mm/lru_gen/min_ttl_ms
```

Key symbols:

```text
cache_ext_bpf_predict
cache_ext_begin_reclaim_cycle
cache_ext_can_isolate
cache_ext_aging_should_promote
```

### 5. Build libbpf

Build kernel libbpf once if `tools/lib/bpf/libbpf.a` is missing:

```bash
cd ~/myOsTest
SRC=$PWD/linux-hwe-6.17-6.17.0

make -C "$SRC/tools/lib/bpf" -j$(nproc)
ls -lh "$SRC/tools/lib/bpf/libbpf.a"
```

### 6. Build bpftool And Generate vmlinux.h

Build the bpftool from the same kernel source tree. A distro wrapper may create
a zero-byte `vmlinux.h`.

```bash
cd ~/myOsTest/huawei_mem-master/zb/MGLRU

SRC=~/myOsTest/linux-hwe-6.17-6.17.0
rm -f ebpf/vmlinux.h

make -C "$SRC/tools/bpf/bpftool" -j1 2>&1 | tee ~/myOsTest/build-bpftool.log

find "$SRC/tools/bpf/bpftool" -maxdepth 2 -type f -name bpftool -executable -ls
```

Generate `ebpf/vmlinux.h`:

```bash
BPFT=~/myOsTest/linux-hwe-6.17-6.17.0/tools/bpf/bpftool/bpftool

rm -f ebpf/vmlinux.h
"$BPFT" btf dump file /sys/kernel/btf/vmlinux format c > ebpf/vmlinux.h

ls -lh ebpf/vmlinux.h
head -n 5 ebpf/vmlinux.h
```

Expected:

```text
ebpf/vmlinux.h 3.3M
#ifndef __VMLINUX_H__
#define __VMLINUX_H__
```

`cache_ext_bpf_common.h` already guards BTF-provided context structs:

```c
#if !defined(CACHE_EXT_SKIP_CTX) && !defined(__VMLINUX_H__)
struct cache_ext_bpf_ctx {
	...
};
#endif

#ifndef __VMLINUX_H__
struct cache_ext_bpf_cycle_ctx {
	...
};
#endif
```

### 7. Dry-Run CSV Parsing

```bash
cd ~/myOsTest/huawei_mem-master/zb/MGLRU

python3 ebpf/cache_ext_loader.py \
  --dry-run \
  --app-id 4 \
  --markov-csv generated/cache_ext_markov_transition.csv \
  --profile-csv generated/cache_ext_page_profile.csv
```

Expected:

```text
markov top-1 entries: ...
profile entries: ...
profile CSV will be synced to kernel debugfs hints by the libbpf loader
```

Markov sample:

```text
app_id,order,ctx0,ctx1,ctx2,ctx3,next_op,count,prob
4,4,2,3,4,5,22,191,0.221065
```

This means history `2 3 4 5` predicts `next_op=22`.

### 8. Load BPF And Sync Kernel Hints

Run with a fixed 4-op history for deterministic testing:

```bash
cd ~/myOsTest/huawei_mem-master/zb/MGLRU

read CTX0 CTX1 CTX2 CTX3 NEXTOP < <(awk -F, 'NR==2 {print $3, $4, $5, $6, $7}' generated/cache_ext_markov_transition.csv)
echo "CTX=$CTX0 $CTX1 $CTX2 $CTX3 NEXTOP=$NEXTOP"

sudo pkill -f "cache_ext_loader.py" 2>/dev/null || true

LOG=~/myOsTest/cache_ext_bpf_loader.log
: > "$LOG"

sudo -E python3 ebpf/cache_ext_loader.py \
  --markov-csv generated/cache_ext_markov_transition.csv \
  --profile-csv generated/cache_ext_page_profile.csv \
  --kernel-src ~/myOsTest/linux-hwe-6.17-6.17.0 \
  --kernel-build ~/myOsTest/linux-hwe-6.17-cacheext-v2-build \
  --app-id 4 \
  --limit 1000 \
  --set-history "$CTX0" "$CTX1" "$CTX2" "$CTX3" \
  > "$LOG" 2>&1 &

echo $! > ~/myOsTest/cache_ext_bpf_loader.pid
```

The loader performs:

```text
1. compile cache_ext_policy.bpf.c -> cache_ext_policy.bpf.o
2. compile cache_ext_libbpf_loader.c
3. attach cache_ext_predict_policy to fmod_ret/cache_ext_bpf_predict
4. load history_map and markov_map
5. enable debugfs policy bpf mode
6. write profile clear
7. merge profile CSV and write profile add ... into /sys/kernel/debug/cache_ext
8. keep the BPF link alive
```

Expected state:

```bash
sudo cat /sys/kernel/debug/cache_ext
```

```text
policy_mode: bpf
bpf_enabled: 1
current_predicted_next_op: 22
```

### 9. Trigger Reclaim And Verify BPF Prediction

Use a cgroup memory limit instead of global memory pressure.

```bash
CE=/sys/kernel/debug/cache_ext
CG=/sys/fs/cgroup/cacheext_bpf_test

sudo mkdir -p "$CG"
echo 900M | sudo tee "$CG/memory.max"
echo 0 | sudo tee "$CG/memory.swap.max" 2>/dev/null || true

sync
echo 3 | sudo tee /proc/sys/vm/drop_caches

sudo bash -c '
echo $$ > /sys/fs/cgroup/cacheext_bpf_test/cgroup.procs

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

Expected successful result:

```text
policy_mode: bpf
bpf_enabled: 1
cycle_seq: 305
current_predicted_next_op: 22
predicted_updates: 307
cycle_refreshes: 305
active_hint_updates: 307
bpf_predict_calls: 305
bpf_predict_hits: 305
bpf_predict_miss: 0
bpf_predict_errors: 0
```

Pass criteria:

```text
bpf_predict_calls grows with reclaim/scan cycles.
bpf_predict_hits grows when history_map + markov_map match.
bpf_predict_miss remains 0 for deterministic history 2 3 4 5.
bpf_predict_errors remains 0.
bpf_predict_calls does not track folio count.
aging_calls may grow much faster because it counts folio-level checks.
profile_hits/protected_folios/skipped_reclaim grow only when kernel-side profile hints match file-backed folios.
```

### 10. Save Logs And Cleanup

```bash
mkdir -p ~/myOsTest/cache_ext_verify_logs

sudo cat /sys/kernel/debug/cache_ext | tee ~/myOsTest/cache_ext_verify_logs/bpf_markov_success.txt
uname -r | tee -a ~/myOsTest/cache_ext_verify_logs/bpf_markov_success.txt
date | tee -a ~/myOsTest/cache_ext_verify_logs/bpf_markov_success.txt

sudo pkill -f "cache_ext_loader.py"
sudo rmdir /sys/fs/cgroup/cacheext_bpf_test 2>/dev/null || true
```

## Code-Level Sanity Checks

Run inside the patched kernel tree:

```bash
grep -R "cache_ext_bpf_should_keep" -n mm include || true
grep -R "cache_ext_bpf_predict" -n mm/cache_ext.c mm/vmscan.c
grep -R "cache_ext_bpf_decide" -n mm/cache_ext.c
grep -n -A8 "bool cache_ext_can_isolate" mm/cache_ext.c
grep -n -A8 "predicted_op %hu %hu" mm/cache_ext.c
```

Expected:

```text
cache_ext_bpf_should_keep is absent.
cache_ext_bpf_predict is called from cache_ext_begin_reclaim_cycle only.
cache_ext_bpf_decide exists only as a compatibility stub.
cache_ext_can_isolate uses cache_ext_match_folio(folio, true).
predicted_op increments active_hint_updates after predicted_updates.
```
