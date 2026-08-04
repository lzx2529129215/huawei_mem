# MGLRU v4 内核修改详细说明

## 修改版本：v4.1 → v4.2

### 概述

本次修改在原有 v4 MGLRU（Multi-Gen LRU）内核的基础上，新增了 **Per-Memcg Tier2 Watermark 预测系统**。该系统支持：
- 基于 Markov 链的应用操作预测
- 与 eBPF 兼容的预测数据交换格式
- Per-memcg 的精细化内存水位线管理
- 主动的内存回收预判和页面优先级调整

---

## 文件级修改详情

### 1. `include/linux/tier2_watermark.h`（重写）

**原始版本**：仅包含 per-node 的 tier2 watermark 统计和 API。

**当前版本**（新增）：
- **eBPF 兼容预测数据结构**：
  - `struct tier2_hist_entry`：操作历史环形缓冲区
  - `struct tier2_markov_entry`：Markov 转移表条目
  - `struct tier2_profile_entry`：页面 profile 映射表
  - `TIER2_MAX_HISTORY`（16）、`TIER2_MAX_MARKOV`（512）、`TIER2_MAX_PROFILES`（128）

- **Per-Memcg 水位线状态**（`struct tier2_wmark_memcg`）：
  - `enabled`/`alloc_scale`/`demote_scale`：用户可配置参数
  - `alloc_wmark_bytes`/`demote_wmark_bytes`：计算出的水位线（字节）
  - `ewma_headroom`：EWMA 平滑头空间
  - `last_headroom`/`last_ewma_jiffies`：预测所需的历史数据
  - `reclaim_work`：异步回收工作队列
  - `predict_dwork`：主动预测延迟工作
  - `predict_scheduled`/`predict_executed` 等统计计数器

- **Per-Memcg API**（新增）：
  - `tier2_wmark_memcg_alloc()`/`_offline()`/`_free()`：生命周期管理
  - `tier2_wmark_memcg_update()`：水位线更新
  - `tier2_wmark_memcg_check()`/`_check_and_reclaim()`：状态检查和异步回收
  - `tier2_wmark_update_ewma_memcg()`：EWMA 更新
  - `tier2_wmark_predict_time_to_wmark()`：预测到达水位线时间
  - `tier2_predict_adjust_pages()`：基于预测调整页面优先级
  - `tier2_predict_load_markov_csv()`/`_profile_csv()`：CSV 数据加载
  - `tier2_predict_clear_tables()`：清除预测表

- **Cgroup v1 文件接口**（新增）：
  - `tier2_memcg_enabled_show/write`
  - `tier2_memcg_alloc_scale_show/write`
  - `tier2_memcg_demote_scale_show/write`
  - `tier2_memcg_alloc_wmark_show`
  - `tier2_memcg_demote_wmark_show`
  - `tier2_memcg_headroom_show`
  - `tier2_memcg_below_show`
  - `tier2_memcg_stats_show`

- **预测 Sysctl 全局变量**（新增）：
  - `sysctl_tier2_predict_enabled`
  - `sysctl_tier2_predict_latency_ms`
  - `sysctl_tier2_predict_horizon_ratio`

- **CONFIG_TIER2_WATERMARK_MEMCG=n 时的空桩函数**（新增）

---

### 2. `mm/tier2_watermark.c`（大幅修改）

**新增头文件**：
- `#include <linux/mm_inline.h>`
- `#include <linux/page-flags.h>`
- `#include <linux/uaccess.h>`
- `#include <linux/string.h>`
- `#include <linux/sysctl.h>`（CONFIG_TIER2_WATERMARK_MEMCG）

**新增全局变量**（CONFIG_TIER2_WATERMARK_MEMCG）：
- 预测表：`hist_table[]`、`markov_table[]`、`profile_table[]`
- 统计计数器：`tier2_ebpf_markov_hits/misses`、`tier2_ebpf_profile_hits/misses`

**新增 Sysctl 变量**：
- `sysctl_tier2_predict_enabled`（默认 0）
- `sysctl_tier2_predict_latency_ms`（默认 100）
- `sysctl_tier2_predict_horizon_ratio`（默认 3）

**新增函数**：

1. **EWMA 头空间跟踪**：
   ```c
   void tier2_wmark_update_ewma_memcg(struct mem_cgroup *memcg)
   ```
   - 使用指数加权移动平均（EWMA）平滑跟踪 per-memcg 的头空间变化
   - 使用 `TIER2_EWMA_SHIFT` 进行整数移位计算

2. **预测到达水位线时间**：
   ```c
   long tier2_wmark_predict_time_to_wmark(struct mem_cgroup *memcg)
   ```
   - 基于 EWMA 趋势计算头空间消耗速率
   - 返回预计到达 demote 水位线的毫秒数
   - 使用 `jiffies_to_msecs()` 转换时间单位

3. **预测工作函数**：
   ```c
   static void tier2_wmark_prediction_work_fn(struct work_struct *work)
   ```
   - 由延迟工作队列调度执行
   - 更新 EWMA → 预测时间 → 调整页面优先级

4. **Markov 预测查找**：
   ```c
   static int tier2_predict_markov_lookup(...)
   ```
   - 1-4 阶 Markov 链预测，高阶优先，低阶回退
   - 匹配 app_id + context（最近 1-4 个操作）
   - 返回预测的下一个操作和置信度（count）

5. **Profile 查找**：
   ```c
   static int tier2_predict_profile_lookup(...)
   ```
   - 根据 app_id + 预测的操作 ID 查找页面范围
   - 返回 device、inode、文件偏移范围、优先级

6. **页面优先级调整**（核心）：
   ```c
   void tier2_predict_adjust_pages(struct mem_cgroup *memcg)
   ```
   - **eBPF 路径**：使用 Markov 预测 + Profile 查找确定页面范围
   - **内置回退**：遍历 MGLRU 代际页面链表
     - 最高代际（最冷）→ folio_clear_active（标记为可淘汰）
     - 最低代际（最热）→ folio_mark_accessed（标记为活跃）
   - 最多扫描 `SWAP_CLUSTER_MAX * 4` 个页面
   - 更新统计计数器

7. **check_and_reclaim 增强**：
   - 在 `tier2_wmark_memcg_check_and_reclaim()` 中集成预测逻辑
   - 计算预测时间，若在阈值内则调度 `predict_dwork`
   - 延迟 = predicted_ms - latency_ms（最小 1ms）

8. **CSV 数据解析**：
   ```c
   static int tier2_parse_markov_line(const char *line)
   static int tier2_parse_profile_line(const char *line)
   static int tier2_parse_history_line(const char *line)
   ```
   - CSV 格式兼容 huawei_mem/lzx 导出
   - Markov: `M,app_id,ctx0,ctx1,ctx2,ctx3,next_op,count`
   - Profile: `P,app_id,op_id,dev:maj:min,ino,start,end,pri`
   - History: `H,app_id,op0,op1,op2,op3,length`
   - 支持 `clear` 命令重置所有表格

9. **Debugfs 写入处理**：
   - 通过 `/sys/kernel/debug/tier2_watermark/predict_data` 接收数据
   - 流式解析行，支持注释（`#` 开头）
   - 最大输入限制 `PAGE_SIZE * 4`
   - 空行和空白行自动跳过

10. **Stats 输出增强**：
    - 在 `tier2_memcg_stats_show()` 中添加预测相关统计：
      - `predict_ewma_headroom`、`predict_scheduled`、`predict_executed`
      - `predict_pages_protected`、`predict_pages_demoted`
      - `ebpf_markov_hits/misses`、`ebpf_profile_hits/misses`
      - `ebpf_tables_markov/profile/history`

**修改的已有功能**：
- `tier2_wmark_memcg_alloc()`：新增预测延迟工作和统计初始化
- `tier2_wmark_memcg_offline()`：新增 `cancel_delayed_work_sync(&tm->predict_dwork)`
- `tier2_wmark_memcg_free()`：同上
- `tier2_wmark_debugfs_init()`：新增 `predict_data` 文件节点
- 缩进格式修复（1 处）

---

### 3. `mm/page_alloc.c`（小幅修改）

在 sysctl 注册表中，`#endif /* CONFIG_TIER2_WATERMARK */` 之前新增：

```c
#ifdef CONFIG_TIER2_WATERMARK_MEMCG
{
    .procname   = "tier2_predict_enabled",
    .data       = &sysctl_tier2_predict_enabled,
    .maxlen     = sizeof(sysctl_tier2_predict_enabled),
    .mode       = 0644,
    .proc_handler = proc_dointvec_minmax,
    .extra1     = SYSCTL_ZERO,
    .extra2     = SYSCTL_ONE,
},
{
    .procname   = "tier2_predict_latency_ms",
    .data       = &sysctl_tier2_predict_latency_ms,
    .maxlen     = sizeof(sysctl_tier2_predict_latency_ms),
    .mode       = 0644,
    .proc_handler = proc_dointvec_minmax,
    .extra1     = SYSCTL_ZERO,
    .extra2     = SYSCTL_ONE_THOUSAND,
},
{
    .procname   = "tier2_predict_horizon_ratio",
    .data       = &sysctl_tier2_predict_horizon_ratio,
    .maxlen     = sizeof(sysctl_tier2_predict_horizon_ratio),
    .mode       = 0644,
    .proc_handler = proc_dointvec_minmax,
    .extra1     = SYSCTL_ZERO,
    .extra2     = SYSCTL_ONE_HUNDRED,
},
#endif /* CONFIG_TIER2_WATERMARK_MEMCG */
```

---

## 配置依赖

复现需要以下内核配置项：

```
CONFIG_TIER2_WATERMARK=y              # 基础 tier2 watermark（原始 v4 即有）
CONFIG_TIER2_WATERMARK_MEMCG=y        # Per-memcg 预测支持（新增，默认 n）
CONFIG_DEBUG_FS=y                     # Debugfs 支持（预测数据加载）
```

---

## 运行时接口

### Sysctl（/proc/sys/vm/）

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `tier2_predict_enabled` | 0 | 0-1 | 启用预测引擎 |
| `tier2_predict_latency_ms` | 100 | 0-1000 | 预测提前触发的延迟 |
| `tier2_predict_horizon_ratio` | 3 | 0-100 | 预测时间范围倍数 |

### Debugfs（/sys/kernel/debug/tier2_watermark/）

| 文件 | 权限 | 说明 |
|------|------|------|
| `predict_data` | 0200 | 预测 CSV 数据写入接口 |

### Cgroup v1（/sys/fs/cgroup/memory/<group>/）

| 文件 | 权限 | 说明 |
|------|------|------|
| `memory.tier2_enabled` | 0644 | 启用/禁用 per-memcg tier2 |
| `memory.tier2_alloc_scale` | 0644 | 分配水位线比例（1/10000） |
| `memory.tier2_demote_scale` | 0644 | 淘汰水位线比例（1/10000） |
| `memory.tier2_alloc_wmark` | 0444 | 当前分配水位线（只读） |
| `memory.tier2_demote_wmark` | 0444 | 当前淘汰水位线（只读） |
| `memory.tier2_headroom` | 0444 | 当前头空间 |
| `memory.tier2_below` | 0444 | 是否低于水位线 |
| `memory.tier2_stats` | 0444 | Per-memcg 统计信息 |

---

## extraneous 文件

以下文件是在开发过程中产生的，**不应**包含在最终复现中：

| 文件 | 说明 |
|------|------|
| `folios` | 空文件，开发残留 |
| `include/linux/tier2_watermark.h.bak` | 头文件备份 |
| `mm/tier2_watermark.c.bak` | 源文件备份 |
| `mm/tier2_watermark.c.bak2` | 源文件备份（第二版） |

---

## 修改统计

| 指标 | 数值 |
|------|------|
| 修改/新增文件数 | 3（内核源文件） + 2（README.md、SHA256SUMS） |
| 新增代码行数 | ~820 行（包含注释） |
| 新增函数数 | 11 |
| 新增数据结构 | 5 |
| 新增 sysctl 参数 | 3 |
| 新增 cgroup 文件 | 9 |
| 新增 debugfs 节点 | 1 |
