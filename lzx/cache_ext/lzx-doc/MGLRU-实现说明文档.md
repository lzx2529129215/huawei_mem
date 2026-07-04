# cache_ext MGLRU 实现说明文档

## 1. 概述

MGLRU（**M**ulti-**G**eneration **LRU**，多代 LRU）是 cache_ext 项目中实现的一种页面缓存逐出（eviction）策略。它基于 Linux 内核的 MGLRU 框架思想，通过 eBPF `struct_ops` 机制注入到内核的页面回收路径中，实现可定制的页面缓存逐出策略。

与传统的 LRU/2Q 等逐出策略相比，MGLRU 的核心优势在于：

- **多代分代管理**：将页面按访问时间划分为多个代（generation），逐代老化（aging）和逐出
- **分层保护**：在每代内部基于访问频率划分层级（tier），保护热点页面
- **PID 控制器反馈**：基于 refault（回退）事件动态调整逐出决策，自动平衡逐出激进程度
- **Ghost 条目**：记录最近被逐出页面的元数据，用于检测和统计 refault 事件

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────┐
│                  Userspace                         │
│  cache_ext_mglru.c                                 │
│  - 加载 BPF 程序                                   │
│  - 附加到 cgroup                                   │
│  - 初始化 inode 监听                                │
└──────────────────┬───────────────────────────────┘
                   │ BPF struct_ops / cgroup
┌──────────────────▼───────────────────────────────┐
│              eBPF Policy (内核态)                   │
│  cache_ext_mglru.bpf.c                             │
│  ┌─────────────────────────────────────────────┐  │
│  │  struct_ops hooks:                           │  │
│  │  - mglru_init()      策略初始化               │  │
│  │  - mglru_folio_added()     页面加入时回调     │  │
│  │  - mglru_folio_accessed()  页面被访问时回调   │  │
│  │  - mglru_evict_folios()    逐出决策主逻辑     │  │
│  │  - mglru_folio_evicted()   页面被逐出时回调   │  │
│  └─────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────┐  │
│  │  Core Components:                            │  │
│  │  - PID Controller (逐出层级选择)              │  │
│  │  - Ghost Map (refault 检测)                  │  │
│  │  - Generation Lists (多代链表)                │  │
│  │  - Per-Folio Metadata Map                    │  │
│  └─────────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────────┘
                   │ BPF kfuncs
┌──────────────────▼───────────────────────────────┐
│           Kernel Infrastructure                    │
│  linux/mm/page_cache_ext.c / .h                    │
│  linux/include/linux/cache_ext.h                   │
│  - cache_ext list (链式数据结构)                    │
│  - DS registry (数据结构注册管理)                   │
│  - kfunc 导出到 BPF                               │
└──────────────────────────────────────────────────┘
```

---

## 3. 核心概念

### 3.1 多代（Multi-Generation）模型

页面按照访问时间被划分到最多 **4 个代**（`MAX_NR_GENS = 4`）中：

```
   越老 ←──────────────────────────→ 越新
  gen 0      gen 1      gen 2      gen 3
 [min_seq]                        [max_seq]
  最旧代                          最新代
 (逐出目标)                   (新访问页面加入)
```

- **`min_seq`**：指向最老一代（eviction 的目标）
- **`max_seq`**：指向最新一代（新加入页面所在代）
- 每代至少保留 2 代（`MIN_NR_GENS = 2`）
- 代之间的迁移由 aging 和 eviction 过程驱动

### 3.2 层级（Tier）系统

在每个代内部，页面根据其被访问次数被分为最多 **4 个层级**（`MAX_NR_TIERS = 4`）：

```
访问次数(refs) → tier
    1  → tier 0 (最冷)
  2-3  → tier 1
  4-7  → tier 2
  8+   → tier 3 (最热,被保护)
```

层级通过 `order_base_2()` 函数计算：`tier = order_base_2(refs)`。

**保护机制**：在逐出扫描时，tier 高于当前阈值的页面会被"保护"（promote 到下一代），不会被逐出。

### 3.3 Ghost 条目与 Refaul 检测

Ghost 条目是 cache_ext 实现的关键创新之一：

- **写入时机**：页面被逐出时，`mglru_folio_evicted` 钩子将页面的 `(address_space, file_offset)` 作为 ghost key 插入 `ghost_map`
- **读取时机**：当同一页面被重新读入缓存（refault）时，`lru_gen_add_folio` 在加入新代之前检查 ghost map
- **作用**：检测到的 refault 事件会更新对应 tier 的 `refaulted` 统计，反馈给 PID 控制器

```
Evict:  folio → (insert ghost entry) → 逐出
Refault:  folio re-read → (check ghost) → 命中! → 增加 refaulted[tier] 计数
```

### 3.4 PID 控制器

PID（Proportional-Integral-Derivative）控制器动态决定逐出哪个 tier 的页面：

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐
│ refaulted │    │   PID       │    │ tier_threshold│
│ evicted   │───▶│ Controller  │───▶│ (逐出层级选择) │
│ protected │    │             │    │               │
└──────────┘    └─────────────┘    └──────────────┘
```

| 项 | 含义 |
|----|------|
| **P（比例项）** | `refaulted / (evicted + protected)` 比值 — 当前代中某 tier 的 refault 比例 |
| **I（积分项）** | P 项的指数移动平均（平滑因子 1/2），跨代累积历史信息 |
| **D（微分项）** | 未实现 |
| **SP（设定点）** | tier 0（最冷 tier）的 refault 比率 |
| **PV（过程变量）** | 更高 tier 的 refault 比率 |
| **控制动作** | 当 `PV > SP`（高 tier refault 过多）→ 保护该 tier；当 `SP > PV` → 放宽保护 |

**`get_tier_idx()` 函数**遍历 tier 1 到 tier 3，找到第一个 refault 比率超过 tier 0 的 tier，返回该 tier - 1 作为逐出阈值。如果所有高 tier 都表现良好，则只逐出 tier 0。

---

## 4. 关键数据结构

### 4.1 `folio_metadata_map`（BPF Hash Map）

```c
key:   __u64 (folio 指针)
value: struct folio_metadata {
    s64 accesses;  // 页面被访问次数
    s64 gen;       // 页面所在代
}
max_entries: 4,000,000
```

每个被跟踪的 folio 的元数据，记录其访问频率和所属代。

### 4.2 `ghost_map`（BPF LRU Hash Map）

```c
key:   struct ghost_entry {
    u64 address_space;  // inode 地址
    u64 offset;         // 文件内偏移
}
value: u8 (tier 编号)
max_entries: 400,000
```

LRU 淘汰的 ghost 条目表，最近被逐出的页面信息。使用 `BPF_F_NO_COMMON_LRU` 实现 per-CPU 的独立 LRU 逻辑。

### 4.3 `mglru_global_metadata_map`（BPF Array Map）

```c
key:   int (固定为 0)
value: struct mglru_global_metadata {
    struct bpf_spin_lock lock;
    unsigned long max_seq;        // 最新代序号
    unsigned long min_seq;        // 最旧代序号
    s64 evicted[MAX_NR_TIERS];    // 每 tier 被逐出计数
    s64 refaulted[MAX_NR_TIERS];  // 每 tier refault 计数
    s64 tier_selected[MAX_NR_TIERS]; // 每 tier 被选择的次数
    s64 success_evicted;          // 成功逐出计数
    s64 failed_evicted;           // 失败逐出计数
    unsigned long avg_refaulted[MAX_NR_TIERS]; // refault 的指数移动平均
    unsigned long avg_total[MAX_NR_TIERS];     // 总量的指数移动平均
    unsigned long protected[MAX_NR_TIERS - 1]; // 被保护的页面计数(tier 1-3)
    long nr_pages[MAX_NR_GENS];   // 每代的页面数
}
max_entries: 1
```

全局 MGLRU 策略状态，包含所有代的序列号、逐出统计、PID 控制器运行数据。

### 4.4 `mglru_percpu_array`（Per-CPU Array Map）

```c
key:   u32
value: struct eviction_metadata {
    __u64 curr_gen;       // 当前正在逐出的代
    __u64 next_gen;       // 保护页面的目标代
    __u64 iter_reached;   // 迭代到的位置
    __u64 tier_threshold; // 本次逐出的 tier 阈值
}
max_entries: 1 (per-CPU)
```

逐出操作过程中使用的 per-CPU 元数据 (避免锁竞争)。

### 4.5 `mglru_lists[]`（Static Array）

```c
static __u64 mglru_lists[MAX_NR_GENS]; // 4 个链表指针
```

每代对应一个内核空间的链表，通过 `bpf_cache_ext_ds_registry_new_list()` 分配，通过 `bpf_cache_ext_list_add()` / `bpf_cache_ext_list_iterate_extended()` 操作。

---

## 5. BPF struct_ops 钩子详解

### 5.1 `mglru_init(struct mem_cgroup *memcg)` — 策略初始化

```c
s32 BPF_STRUCT_OPS_SLEEPABLE(mglru_init, struct mem_cgroup *memcg)
```

- 设置 `max_seq = MIN_NR_GENS + 1`（初始有 3 个代）
- 为每个代分配一个内核链表（`bpf_cache_ext_ds_registry_new_list`）
- 在策略被附加到 cgroup 时由内核调用

### 5.2 `mglru_folio_added(struct folio *folio)` — 页面加入缓存

```c
void BPF_STRUCT_OPS(mglru_folio_added, struct folio *folio)
```

1. 通过 `is_folio_relevant()` 过滤：只处理 `inode_in_watchlist()` 中的文件
2. 调用 `lru_gen_add_folio()` 将页面插入对应代：
   - **活跃页面**（`folio_test_active`，refs ≥ 2）→ 插入最新代（`max_seq`）
   - **等待回写的脏页** → 插入 `max_seq - 1` 代
   - **空间不足时**（`min_seq + 2 >= max_seq`）→ 插入最旧代
   - **一般非活跃页面** → 插入 `min_seq + 1` 代
3. 分配 `folio_metadata` 并存入 `folio_metadata_map`
4. 检查 ghost map：若命中则增加对应 tier 的 `refaulted` 计数
5. 将 folio 加入对应代的链表中

### 5.3 `mglru_folio_accessed(struct folio *folio)` — 页面被访问

```c
void BPF_STRUCT_OPS(mglru_folio_accessed, struct folio *folio)
```

- 过滤 `is_folio_relevant()`
- 原子递增 `folio_metadata.accesses` 计数器
- 访问次数直接影响 `lru_tier_from_refs()` 计算出的 tier

### 5.4 `mglru_evict_folios(...)` — 核心逐出逻辑

```c
void BPF_STRUCT_OPS(mglru_evict_folios,
                     struct cache_ext_eviction_ctx *eviction_ctx,
                     struct mem_cgroup *memcg)
```

这是 MGLRU 实现的核心，完整流程如下：

```
mglru_evict_folios()
  │
  ├─ 1. 获取 lrugen 自旋锁
  │
  ├─ 2. Aging 检查
  │    └─ should_run_aging(lrugen, max_seq)?
  │       ├─ 是 → try_to_inc_max_seq(lrugen)
  │       │       ├─ 代数已满(MAX_NR_GENS=4) → try_to_inc_min_seq()
  │       │       │     └─ 最旧代几乎为空 → min_seq++
  │       │       └─ 成功 → max_seq++ + 重置控制统计
  │       └─ 否 → 跳过
  │
  ├─ 3. 代收缩
  │    └─ 若 max_seq - min_seq > MIN_NR_GENS → try_to_inc_min_seq()
  │
  ├─ 4. 确定逐出阈值
  │    └─ tier_threshold = get_tier_idx(lrugen)
  │       (PID 控制器决定逐出到哪个 tier)
  │
  ├─ 5. 第一轮逐出扫描
  │    └─ bpf_cache_ext_list_iterate_extended(
  │         memcg, oldest_gen_list,
  │         mglru_iter_fn, &opts, eviction_ctx)
  │       │
  │       └─ mglru_iter_fn() 对每个节点:
  │            ├─ folio tier > tier_threshold → 保护，移到下一代
  │            ├─ folio locked/writeback/dirty  → 移到下一代
  │            └─ 否则 → 标记逐出 (CACHE_EXT_EVICT_NODE)
  │
  ├─ 6. 第二轮逐出扫描（如果第一轮不够）
  │    └─ 同上，使用更新后的 oldest_gen
  │
  └─ 7. 更新统计
       ├─ success_evicted += 实际逐出数
       └─ failed_evicted += (请求数 - 实际逐出数)
```

### 5.5 `mglru_folio_evicted(struct folio *folio)` — 页面被逐出后

```c
void BPF_STRUCT_OPS(mglru_folio_evicted, struct folio *folio)
```

1. 从 `folio_metadata_map` 查找并读取 folio 的访问次数
2. 计算 tier 并将 ghost 条目插入 `ghost_map`（用于 refault 检测）
3. 更新对应 tier 的 `evicted` 统计
4. 更新对应代的 `nr_pages` 计数（减少）
5. 从 `folio_metadata_map` 中删除该 folio 的记录

---

## 6. 关键辅助函数

### 6.1 Aging 相关

| 函数 | 作用 |
|------|------|
| `should_run_aging()` | 判断是否需要执行 aging：检查各代负载是否平衡，冷热页面比例是否合理 |
| `try_to_inc_max_seq()` | 执行 aging：递增 `max_seq`，创建新一代。如果代数已达上限则先尝试收缩 |
| `try_to_inc_min_seq()` | 收缩最旧代：若最旧代几乎为空（≤4 个页面），递增 `min_seq` |

### 6.2 PID 控制器相关

| 函数 | 作用 |
|------|------|
| `read_ctrl_pos()` | 读取某 tier 的控制位置：refaulted、total(evicted + protected)、gain |
| `reset_ctrl_pos()` | 重置控制统计：carryover 模式保留 1/2 的历史平均，clear 模式清零 |
| `positive_ctrl_err()` | 判断 PV 是否超过 SP：比较 refault 比率，考虑 batch 边界 |
| `get_tier_idx()` | 遍历 tier 1-3，找到 PID 控制器建议的逐出阈值 |

### 6.3 代和层级计算

| 函数 | 作用 |
|------|------|
| `lru_gen_from_seq(seq)` | 从序列号计算代索引：`seq % MAX_NR_GENS` |
| `lru_tier_from_refs(refs)` | 从访问次数计算层级：`order_base_2(refs)` |
| `folio_lru_refs(folio)` | 读取 folio 的访问次数 |
| `folio_test_active(folio)` | 判断是否活跃：访问次数 ≥ 2 |
| `gen_within_limits(gen)` | 验证代索引合法性 |

### 6.4 统计更新

| 函数 | 作用 |
|------|------|
| `update_refaulted_stat()` | 原子更新 refault 计数 |
| `update_evicted_stat()` | 原子更新逐出计数 |
| `update_nr_pages_stat()` | 原子更新代内页面计数 |
| `update_tier_selected_stat()` | 原子更新 tier 选择计数 |
| `update_protected_stat()` | 原子更新被保护页面计数 |

---

## 7. 文件组织

```
cache_ext/
├── policies/
│   ├── cache_ext_mglru.bpf.c          # MGLRU eBPF 策略（核心实现，~920 行）
│   ├── cache_ext_mglru.c              # 用户空间加载器
│   ├── cache_ext_lib.bpf.h            # BPF 辅助库（原子操作、folio flag 检查等）
│   └── dir_watcher.bpf.h              # 目录监听器（inode watchlist 管理）
│
├── linux/
│   ├── include/linux/cache_ext.h      # 内核侧 cache_ext 数据结构定义
│   ├── mm/page_cache_ext.c            # 内核侧 cache_ext 主逻辑
│   ├── mm/page_cache_ext.h            # 内核侧 cache_ext 头文件
│   ├── mm/page_cache_ext_ds.c         # 内核侧数据结构注册与链表实现
│   ├── mm/page_cache_ext_ds.h         # 内核侧数据结构头文件
│   ├── mglru_notes.md                 # MGLRU 开发笔记
│   └── testing/page_cache_ext/
│       ├── page_cache_ext_mglru.bpf.c # 测试版 MGLRU BPF 策略
│       └── page_cache_ext_mglru.c     # 测试版加载器
│
└── utils/
    ├── enable-mglru.sh                # 启用内核 MGLRU
    └── disable-mglru.sh               # 禁用内核 MGLRU
```

---

## 8. 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `MAX_NR_GENS` | 4 | 最大代数 |
| `MIN_NR_GENS` | 2 | 最小代数（保持此数量以支持 aging） |
| `MAX_NR_TIERS` | 4 | 每代最大层级数 |
| `NR_HIST_GENS` | 1 | 保留历史统计的代数量 |
| `MIN_LRU_BATCH` | 64 | LRU 批量操作最小值（PID 控制器的边界） |
| `MAX_NR_FOLIOS` | 4,000,000 | folio 元数据 map 最大条目 |
| `MAX_NR_GHOST_ENTRIES` | 400,000 | ghost 条目 map 最大条目 |

---

## 9. 与 Linux 内核原生 MGLRU 的关系

cache_ext 的 MGLRU 实现借鉴了 Linux 内核 v6.6+ 的原生 MGLRU 设计思想（参见 `linux/mglru_notes.md`），但有以下关键差异：

| 方面 | 内核原生 MGLRU | cache_ext MGLRU |
|------|---------------|----------------|
| 实现位置 | 内核 `mm/vmscan.c` | eBPF `struct_ops` 策略 |
| 灵活性 | 固定编译在内核中 | 可动态加载/卸载 |
| 定制性 | 限于内核参数调节 | 可自由修改策略代码 |
| ANON/FILE 分离 | 支持匿名页和文件页 | 仅处理文件页（监控目录） |
| 粒度 | 全局 | per-cgroup |
| 多代链 | 内核 LRU 链表 | cache_ext 自定义链表 |

---

## 10. 使用方法

### 10.1 启动 MGLRU 策略

```sh
# 确保内核 MGLRU 已启用（cache_ext 使用自己的 MGLRU，但内核侧也需要）
sudo ./utils/enable-mglru.sh

# 编译策略
cd policies && make

# 加载 MGLRU 策略到指定 cgroup
sudo ./cache_ext_mglru --watch_dir /path/to/monitored/dir \
                       --cgroup_path /sys/fs/cgroup/cache_ext_test
```

### 10.2 工作流程

1. **监控目录**：`dir_watcher.bpf.h` 中的 `vfs_open` fexit 探针拦截文件打开事件，将 `inode` 号加入 `inode_watchlist`
2. **Folio 加入**：当属于监控文件的 folio 加入页面缓存时，`mglru_folio_added` 将其分配到合适的代
3. **访问跟踪**：`mglru_folio_accessed` 递增 folio 的访问计数器
4. **内存压力触发逐出**：内核在内存压力下调用 `mglru_evict_folios`，从最旧代中按 tier 阈值逐出冷页面
5. **统计与反馈**：逐出后 `mglru_folio_evicted` 记录 ghost 条目，refault 时反馈给 PID 控制器

---

## 11. 关键设计决策与权衡

1. **仅文件页**：当前实现仅处理文件页（通过 `inode_watchlist` 过滤），不处理匿名页和交换。这与 cache_ext 的设计目标一致（面向存储系统的页面缓存优化）。

2. **Per-CPU Ghost Map**：`ghost_map` 使用 `BPF_F_NO_COMMON_LRU` 标志，为每个 CPU 提供独立的 LRU 逐出逻辑，避免了多核竞争，但意味着 ghost 条目可能在不同 CPU 间不完全一致（这是一种权衡）。

3. **无锁统计更新**：大部分统计通过 `__sync_fetch_and_add` 原子操作更新，避免了重量级锁。仅在需要原子性读取 `min_seq`/`max_seq` 的 aging 阶段使用 `bpf_spin_lock`。

4. **简化的大页面处理**：`folio_nr_pages()` 始终返回 1（未处理大页面的实际页面数），这是一个已知简化。

5. **D 项缺失**：PID 控制器未实现微分项。未来可以考虑加入以抵消长期数据带来的陈旧信息。

6. **eBPF 验证器约束**：所有函数必须通过 eBPF verifier 的检查（无界循环、内存安全等），这限制了一些优化的可能性。

---

## 12. 相关论文

> Tal Zussman, Ioannis Zarkadas, Jeremy Carin, Andrew Cheng, Hubertus Franke, Jonas Pfefferle, Asaf Cidon. **"cache_ext: Customizing the Page Cache with eBPF"**. In *Proceedings of the 29th Symposium on Operating Systems Principles (SOSP '25)*. ACM, 2025. DOI: [10.1145/3731569.3764820](https://doi.org/10.1145/3731569.3764820)

---

*文档生成时间: 2026-06-30*
*基于 cache_ext commit: c50236c*
