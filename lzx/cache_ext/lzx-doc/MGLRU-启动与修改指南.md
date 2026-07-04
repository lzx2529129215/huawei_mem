# cache_ext MGLRU 启动与修改指南

## 目录

1. [环境准备](#1-环境准备)
2. [构建 cache_ext 内核](#2-构建-cache_ext-内核)
3. [构建用户态工具与 eBPF 策略](#3-构建用户态工具与-ebpf-策略)
4. [启动 MGLRU 策略](#4-启动-mglru-策略)
5. [运行验证：YCSB Benchmark 示例](#5-运行验证ycsb-benchmark-示例)
6. [修改 MGLRU 逻辑指南](#6-修改-mglru-逻辑指南)
7. [修改后的构建与验证流程](#7-修改后的构建与验证流程)
8. [调试技巧](#8-调试技巧)

---

## 1. 环境准备

### 1.1 硬件要求

- Cloudlab c6525-25g 实例或同等配置（至少 32 核、128GB 内存）
- 约 **500GB** 可用磁盘空间
- 运行 Ubuntu 22.04

### 1.2 安装构建依赖

```sh
sudo apt-get update
sudo apt-get install -y build-essential bc bison flex rsync libelf-dev \
    libssl-dev libncurses-dev dwarves clang lld llvm python3 python3-pip

# Kernel build.py 脚本依赖
pip3 install yanniszark_common
```

### 1.3 验证 clang-14 可用

```sh
clang-14 --version
# 如果找不到，安装 clang-14
sudo apt-get install -y clang-14
```

---

## 2. 构建 cache_ext 内核

MGLRU 策略运行在修改过的 Linux v6.6.8 内核上，该内核包含了 cache_ext 框架（`BPF_PROG_TYPE_STRUCT_OPS` 支持、自定义链表 kfunc 等）。

### 2.1 内核构建与安装

```sh
cd /home/lzx/Desktop/huawei/cache_ext
./install_kernel.sh
```

这个脚本自动完成：
1. 安装构建依赖
2. 配置内核（`CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y`）
3. 编译并安装 Linux 6.6.8-cache-ext+ 内核
4. 编译并安装 **libbpf**（安装到 `/usr/local/lib64/`）
5. 编译并安装 **bpftool**（安装到 `/usr/local/sbin/bpftool`）

### 2.2 重启进入 cache_ext 内核

```sh
sudo grub-reboot "Advanced options for Ubuntu>Ubuntu, with Linux 6.6.8-cache-ext+"
sudo reboot now
```

重启后验证内核版本：

```sh
uname -r
# 输出应包含: 6.6.8-cache-ext+
```

### 2.3 确认内核 MGLRU 功能

```sh
# 查看 MGLRU 是否支持
cat /sys/kernel/mm/lru_gen/enabled
# 输出 0x0007 表示已完全启用
```

---

## 3. 构建用户态工具与 eBPF 策略

### 3.1 构建 eBPF 策略

```sh
cd /home/lzx/Desktop/huawei/cache_ext
./build_policies.sh
```

这会在 `policies/` 目录下生成以下文件：

```
policies/
├── vmlinux.h                       # 从运行中内核生成的 BTF 头文件
├── cache_ext_mglru.bpf.o           # MGLRU BPF 字节码（eBPF 验证器输入）
├── cache_ext_mglru.skel.h          # BPF skeleton（用户态加载器使用）
└── cache_ext_mglru.out             # MGLRU 用户态可执行加载器 ✅
```

### 3.2 手动构建（仅构建 MGLRU 策略）

如果只需要重新构建 MGLRU：

```sh
cd /home/lzx/Desktop/huawei/cache_ext/policies

# Step 1: 生成 vmlinux.h（仅首次需要，或内核更新后需要）
bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h

# Step 2: 编译 BPF 字节码
clang-14 -O2 -target bpf -D__TARGET_ARCH_x86 -c -g -Wall \
    cache_ext_mglru.bpf.c -o cache_ext_mglru.bpf.o

# Step 3: 生成 skeleton 头文件
bpftool gen skeleton cache_ext_mglru.bpf.o > cache_ext_mglru.skel.h

# Step 4: 编译用户态加载器
clang-14 -O2 -fsanitize=address -g -Wall \
    cache_ext_mglru.c -o cache_ext_mglru.out -L/usr/local/lib64 -lbpf
```

### 3.3 构建其他组件（运行 Benchmark 需要）

```sh
./install_leveldb.sh        # LevelDB (修改版)
./install_ycsb.sh           # My-YCSB benchmark
./install_filesearch.sh     # ripgrep + 文件搜索数据集
./install_misc.sh           # fio 等杂项工具
./setup_isolation.sh        # cgroup 隔离环境
```

---

## 4. 启动 MGLRU 策略

### 4.1 创建 cgroup

MGLRU 策略是 **per-cgroup** 的，需要先创建 cgroup：

```sh
# 创建用于 cache_ext 的 cgroup
sudo mkdir -p /sys/fs/cgroup/cache_ext_test

# (可选) 设置内存限制
echo "16G" | sudo tee /sys/fs/cgroup/cache_ext_test/memory.max
```

### 4.2 确保被监控目录存在

策略需要一个**监控目录**（watch_dir）。只有该目录下的文件才会被 MGLRU 策略管理：

```sh
# 例如：使用 LevelDB 数据库目录
mkdir -p /tmp/leveldb_test
```

### 4.3 启动 MGLRU 策略

```sh
cd /home/lzx/Desktop/huawei/cache_ext/policies

sudo ./cache_ext_mglru.out \
    --watch_dir /path/to/monitored/directory \
    --cgroup_path /sys/fs/cgroup/cache_ext_test
```

启动后终端会显示 `"Press any key to exit..."`，策略在后台运行：
- **目录监听器**：自动将 watch_dir 下文件的 `inode` 加入 `inode_watchlist`
- **Folio 钩子**：拦截所有进入 watch_dir 文件的 folio 操作
- **逐出控制**：在内存压力下按 MGLRU 逻辑执行逐出

### 4.4 停止策略

在运行策略的终端按 `Ctrl+C` 即可退出。

### 4.5 策略运行状态检查

```sh
# 查看 BPF 程序的 trace 日志
sudo cat /sys/kernel/debug/tracing/trace_pipe

# 查看 cgroup 内存统计
cat /sys/fs/cgroup/cache_ext_test/memory.current
cat /sys/fs/cgroup/cache_ext_test/memory.stat
```

---

## 5. 运行验证：YCSB Benchmark 示例

以下是一个完整的端到端验证示例：

### 5.1 准备 LevelDB 数据库

```sh
cd /home/lzx/Desktop/huawei/cache_ext

# 下载数据库数据集（约 75GB 压缩包）
./download_dbs.sh
```

### 5.2 启动 MGLRU 策略

```sh
# 终端 1：启动 MGLRU 策略
cd /home/lzx/Desktop/huawei/cache_ext/policies
sudo ./cache_ext_mglru.out \
    --watch_dir /mydata/leveldb \
    --cgroup_path /sys/fs/cgroup/cache_ext_test
```

### 5.3 运行 Benchmark

```sh
# 终端 2：运行 YCSB benchmark
cd /home/lzx/Desktop/huawei/cache_ext

# 将 benchmark 进程放入 cgroup
echo $$ | sudo tee /sys/fs/cgroup/cache_ext_test/cgroup.procs

python3 bench/bench_leveldb.py \
    --cpu 8 \
    --policy-loader policies/cache_ext_mglru.out \
    --results-file results/ycsb_mglru_test.json \
    --leveldb-db /mydata/leveldb \
    --fadvise-hints "" \
    --iterations 1 \
    --bench-binary-dir My-YCSB/build \
    --benchmark ycsb_a
```

### 5.4 查看结果

```sh
cat results/ycsb_mglru_test.json | python3 -m json.tool | head -50
```

---

## 6. 修改 MGLRU 逻辑指南

### 6.1 代码修改入口一览

```
policies/cache_ext_mglru.bpf.c   ← 【核心文件】所有 MGLRU 逻辑都在这里
```

下面按功能模块说明各逻辑的修改位置：

### 6.2 Generation 分配逻辑 ⭐

**文件位置**：`policies/cache_ext_mglru.bpf.c` 第 452-521 行

**函数**：`lru_gen_add_folio(struct folio *folio)`

**当前逻辑**：

```c
// 四种情况的代分配策略（行 475-483）：
if (folio_test_active(folio))
    seq = max_seq;              // 活跃页面 → 最新代（最年轻）
else if ((folio_test_reclaim(folio) &&
          (folio_test_dirty(folio) || folio_test_writeback(folio))))
    seq = max_seq - 1;          // 等待回写的脏页 → 次新代
else if (min_seq + MIN_NR_GENS >= max_seq)
    seq = min_seq;              // 代数不足 → 最旧代（尽快逐出）
else
    seq = min_seq + 1;          // 一般冷页 → 次旧代
```

**可以修改的方向**：

| 修改目标 | 修改位置 | 示例改动 |
|---------|---------|---------|
| 调整活跃页判定阈值 | `folio_test_active()` (行 406-408) | 将 `refs >= 2` 改为 `refs >= 3` |
| 改变各类型页面的代分配策略 | `lru_gen_add_folio()` 行 475-483 | 例如让脏页直接放到最旧代 |
| 添加新的分配条件 | `lru_gen_add_folio()` 行 475 之前 | 例如基于文件类型或 inode 做特殊分配 |
| 修改代的数量 | `MAX_NR_GENS` (行 109) | 从 4 改为 5（需要同步修改 `mglru_lists[]`） |

### 6.3 逐出扫描逻辑

**文件位置**：`policies/cache_ext_mglru.bpf.c` 第 713-778 行

**函数**：`mglru_iter_fn(int idx, struct cache_ext_list_node *a)`

**当前逻辑**：

```c
// 逐出扫描时的三种处理（行 756-777）：
if (tier > tier_threshold) {
    // 页面太热 → 保护，promote 到下一代
    ...
    return CACHE_EXT_CONTINUE_ITER;
}
if (folio_test_locked(a->folio) || folio_test_writeback(a->folio) ||
    folio_test_dirty(a->folio)) {
    // 页面正在写回 → promote 到下一代
    ...
    return CACHE_EXT_CONTINUE_ITER;
}
// 否则 → 逐出！
return CACHE_EXT_EVICT_NODE;
```

**可以修改的方向**：

| 修改目标 | 位置 | 说明 |
|---------|------|------|
| 调整保护阈值 | `mglru_iter_fn()` 行 756 | 修改 tier 比较逻辑 |
| 添加逐出前的额外检查 | `mglru_iter_fn()` 行 778 之前 | 例如检查页面是否被其他进程使用 |
| 改变 promote 目标代 | 行 762-763 | 选择不同的 `next_gen` |

### 6.4 Aging（老化）逻辑

**文件位置**：`policies/cache_ext_mglru.bpf.c`

| 函数 | 行号 | 作用 |
|------|------|------|
| `should_run_aging()` | 523-575 | 判断是否需要创建新一代（基于冷热比例） |
| `try_to_inc_max_seq()` | 589-635 | 执行 aging：递增 `max_seq` |
| `try_to_inc_min_seq()` | 577-587 | 收缩最旧代：递增 `min_seq` |

**修改示例**：调整 aging 的触发条件

```c
// 在 should_run_aging() 中（行 569-572）：
// 原逻辑：young * MIN_NR_GENS > total → 执行 aging
// 修改为：young * 3 > total（更宽松的触发条件）
if (young * MIN_NR_GENS > total)  // 改为 young * 3 > total
    return true;
```

### 6.5 PID 控制器

**文件位置**：`policies/cache_ext_mglru.bpf.c` 第 254-371 行

| 函数 | 行号 | 作用 |
|------|------|------|
| `read_ctrl_pos()` | 284-294 | 读取控制位置（refault/(evicted+protected)） |
| `positive_ctrl_err()` | 331-340 | 判断 PV 是否超过 SP |
| `get_tier_idx()` | 346-364 | 确定逐出阈值 |
| `reset_ctrl_pos()` | 297-329 | 代变更时重置/衰减统计 |

**修改示例**：调整 PID gain 参数

```c
// 在 get_tier_idx() 中（行 356-357）：
read_ctrl_pos(lrugen, 0, 1, &sp);  // tier 0 gain = 1
for (tier = 1; tier < MAX_NR_TIERS; tier++) {
    read_ctrl_pos(lrugen, tier, 2, &pv);  // 其他 tier gain = 2
    ...
}
```

### 6.6 全局常量

**文件位置**：`policies/cache_ext_mglru.bpf.c` 第 107-112 行

```c
#define MAX_NR_TIERS   4    // 最大层级数
#define MIN_NR_GENS    2    // 最小代数
#define MAX_NR_GENS    4    // 最大代数
#define NR_HIST_GENS   1    // 保留历史统计的代数量
#define MIN_LRU_BATCH  64   // LRU 批量操作最小值
```

---

## 7. 修改后的构建与验证流程

标准的"修改 → 构建 → 验证"迭代流程：

### 7.1 快速迭代流程

```
┌──────────────────────────────────────────────────────────┐
│  Step 1: 修改 BPF 策略代码                                 │
│  vim policies/cache_ext_mglru.bpf.c                       │
├──────────────────────────────────────────────────────────┤
│  Step 2: 重新编译（仅 eBPF 策略，不需要重新编译内核）          │
│  cd policies && make clean && make                        │
├──────────────────────────────────────────────────────────┤
│  Step 3: 停止旧策略                                        │
│  在运行策略的终端按 Ctrl+C                                   │
│  或 sudo pkill cache_ext_mglru                            │
├──────────────────────────────────────────────────────────┤
│  Step 4: 启动新策略                                        │
│  sudo ./cache_ext_mglru.out \                             │
│      --watch_dir /path/to/data \                          │
│      --cgroup_path /sys/fs/cgroup/cache_ext_test           │
├──────────────────────────────────────────────────────────┤
│  Step 5: 运行测试验证                                       │
│  python3 bench/bench_leveldb.py ...                       │
│  或自定义测试脚本                                           │
├──────────────────────────────────────────────────────────┤
│  Step 6: 对比结果                                          │
│  diff results/before.json results/after.json              │
│  或在 bench/bench_plot.ipynb 中对比图表                     │
└──────────────────────────────────────────────────────────┘
```

### 7.2 仅重新编译 MGLRU 策略

```sh
cd /home/lzx/Desktop/huawei/cache_ext/policies

# 清理旧的编译产物
rm -f cache_ext_mglru.bpf.o cache_ext_mglru.skel.h cache_ext_mglru.out

# 重新编译
make cache_ext_mglru.out

# 验证编译成功
ls -lh cache_ext_mglru.out
```

### 7.3 eBPF Verifier 注意事项

修改 BPF 代码后，clang 编译成功并不代表内核 eBPF verifier 会接受。如果 loader 加载失败：

```sh
# 查看 verifier 日志
sudo cat /sys/kernel/debug/tracing/trace_pipe

# 或在 dmesg 中查看
sudo dmesg | tail -50
```

常见的 verifier 报错：
- **无限循环**：verifier 拒绝无法确定迭代次数的循环 → 使用 `#pragma unroll` 或 `__builtin_constant_p` 包裹
- **越界访问**：数组索引必须在编译时确定范围 → 使用 assert 宏或 `if` 边界检查
- **spinlock 内 bpf_printk**：不能在持有自旋锁时调用 → 用标志位延迟打印

### 7.4 添加调试日志

```c
// 在 cache_ext_mglru.bpf.c 顶部启用 DEBUG：
#define DEBUG
// 编译后日志会输出到:
// sudo cat /sys/kernel/debug/tracing/trace_pipe
```

---

## 8. 调试技巧

### 8.1 查看 BPF Map 内容

```sh
# 列出所有 BPF map
sudo bpftool map list

# 查看 mglru_global_metadata_map 内容（通常 map id 较小）
sudo bpftool map dump id <map_id>

# 查看 folio_metadata_map 的条目数
sudo bpftool map dump id <map_id> | wc -l
```

### 8.2 监控策略统计

```sh
# 持续监控 BPF trace 输出
sudo cat /sys/kernel/debug/tracing/trace_pipe | grep cache_ext

# 查看 eviction 统计
sudo bpftool map dump name mglru_global_metadata_map
```

### 8.3 确认策略正确加载

```sh
# 查看已加载的 struct_ops
sudo bpftool struct_ops list

# 查看已附加的 BPF 程序
sudo bpftool prog list | grep mglru
```

### 8.4 对比测试脚本

```sh
#!/bin/bash
# compare_policies.sh - 对比修改前后的性能

POLICY_OLD="./cache_ext_mglru_old.out"
POLICY_NEW="./cache_ext_mglru.out"
CGROUP="/sys/fs/cgroup/cache_ext_test"

echo "=== Running baseline (old) ==="
sudo $POLICY_OLD --watch_dir /mydata/leveldb --cgroup_path $CGROUP &
POLICY_PID=$!
sleep 5
python3 bench/bench_leveldb.py --cpu 8 --policy-loader $POLICY_OLD \
    --results-file results/old.json --iterations 1 --benchmark ycsb_a
sudo kill $POLICY_PID

echo "=== Running new version ==="
sudo $POLICY_NEW --watch_dir /mydata/leveldb --cgroup_path $CGROUP &
POLICY_PID=$!
sleep 5
python3 bench/bench_leveldb.py --cpu 8 --policy-loader $POLICY_NEW \
    --results-file results/new.json --iterations 1 --benchmark ycsb_a
sudo kill $POLICY_PID

echo "=== Diff ==="
diff <(python3 -m json.tool results/old.json) \
     <(python3 -m json.tool results/new.json)
```

---

## 附录 A：关键文件速查表

| 文件 | 内容 | 修改影响范围 |
|------|------|------------|
| `policies/cache_ext_mglru.bpf.c:109` | `MAX_NR_GENS` / `MAX_NR_TIERS` | 代/层级数量 |
| `policies/cache_ext_mglru.bpf.c:406-408` | `folio_test_active()` | 活跃页面判定 |
| `policies/cache_ext_mglru.bpf.c:424-430` | `lru_tier_from_refs()` | 访问次数 → tier 映射 |
| `policies/cache_ext_mglru.bpf.c:452-521` | `lru_gen_add_folio()` | **新页面代分配** ⭐ |
| `policies/cache_ext_mglru.bpf.c:523-575` | `should_run_aging()` | aging 触发条件 |
| `policies/cache_ext_mglru.bpf.c:577-587` | `try_to_inc_min_seq()` | 代收缩逻辑 |
| `policies/cache_ext_mglru.bpf.c:589-635` | `try_to_inc_max_seq()` | 代扩展/aging 执行 |
| `policies/cache_ext_mglru.bpf.c:713-778` | `mglru_iter_fn()` | 逐出扫描决策 |
| `policies/cache_ext_mglru.bpf.c:780-869` | `mglru_evict_folios()` | 逐出主流程 |
| `policies/cache_ext_mglru.bpf.c:331-340` | `positive_ctrl_err()` | PID 误差判断 |
| `policies/cache_ext_mglru.bpf.c:346-364` | `get_tier_idx()` | Tier 阈值选择 |
| `policies/cache_ext_mglru.bpf.c:297-329` | `reset_ctrl_pos()` | 统计重置策略 |
| `policies/cache_ext_mglru.c:41-138` | `main()` | 用户态加载器 |
| `policies/Makefile` | 构建规则 | 编译选项、链接库 |

## 附录 B：完整启动命令示例

```sh
#!/bin/bash
# start_mglru_demo.sh - MGLRU 策略演示启动脚本

set -eu

BASE_DIR="/home/lzx/Desktop/huawei/cache_ext"
POLICY="$BASE_DIR/policies/cache_ext_mglru.out"
WATCH_DIR="/mydata/leveldb"
CGROUP_NAME="cache_ext_test"
CGROUP_PATH="/sys/fs/cgroup/$CGROUP_NAME"

# 1. 创建 cgroup
if [ ! -d "$CGROUP_PATH" ]; then
    echo "Creating cgroup: $CGROUP_PATH"
    sudo mkdir -p "$CGROUP_PATH"
fi

# 2. 设置 cgroup 内存限制为 16GB
echo "Setting cgroup memory limit to 16G"
echo "16G" | sudo tee "$CGROUP_PATH/memory.max" > /dev/null

# 3. 确保被监控目录存在
if [ ! -d "$WATCH_DIR" ]; then
    echo "Watch directory does not exist: $WATCH_DIR"
    echo "Creating it..."
    mkdir -p "$WATCH_DIR"
fi

# 4. 检查内核版本
if ! uname -r | grep -q "cache-ext"; then
    echo "ERROR: Not running cache_ext kernel!"
    echo "Current kernel: $(uname -r)"
    exit 1
fi

# 5. 启动 MGLRU 策略
echo "Starting MGLRU cache_ext policy..."
echo "  Watch dir: $WATCH_DIR"
echo "  Cgroup:    $CGROUP_PATH"
echo ""
sudo "$POLICY" \
    --watch_dir "$WATCH_DIR" \
    --cgroup_path "$CGROUP_PATH" &
POLICY_PID=$!

echo "MGLRU policy started (PID: $POLICY_PID)"
echo "Press Ctrl+C to stop"

# 等待
trap "sudo kill $POLICY_PID 2>/dev/null; exit 0" INT TERM
wait $POLICY_PID
```

---

*文档生成时间: 2026-06-30*
