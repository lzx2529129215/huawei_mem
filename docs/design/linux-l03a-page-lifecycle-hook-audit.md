# Linux L0.3A 页生命周期 Hook 审计

日期：2026-08-02

基线：Linux v6.17 + `0002` + `0003`

范围：classic LRU、observe-only

## 1. 审计方法

本审计在 `work/linux-6.17-l03a-dev` 中对固定 Linux 6.17 源码应用
`0002 -> 0003` 后完成。审计以实际调用点、锁上下文和对象存活期为依据，
不把函数名相似或统计计数点视为生命周期权威点。

必须保持的总约束：页级 hook 不改变 Linux 原生返回值，不持有额外 folio
引用，不在 `lru_lock`、IRQ-disabled 或其他原子上下文中睡眠或执行不受控分配。

## 2. 候选路径与结论

| 行为 | Linux 6.17 权威位置 | 上下文与锁 | 可获得信息 | L0.3A 结论 |
|---|---|---|---|---|
| 加入 LRU | `mm/swap.c:lru_add()` 中 `lruvec_add_folio()` 之后 | `lruvec->lru_lock` 已持有，IRQ disabled；不可睡眠 | head folio、order、nid、memcg、anon/file、active | 权威观测 `ADD_LRU` |
| access | `folio_mark_accessed()` | 可能无 LRU 锁；可能只置 referenced，不发生物理 LRU 转换 | folio 及 flags | 不单独发状态事件；真正 activate 在 `lru_activate()` 观测 |
| activate | `mm/swap.c:lru_activate()` 中重新加入后 | `lruvec->lru_lock` 已持有，IRQ disabled | 新 active class、domain | 权威观测 `ACTIVATE` |
| deactivate | `lru_deactivate()`、`lru_deactivate_file()` 中重新加入后 | `lruvec->lru_lock` 已持有，IRQ disabled | 新 inactive class、domain | 权威观测 `DEACTIVATE`；仅成功改变状态时发出 |
| reclaim isolate | `mm/vmscan.c:isolate_lru_folios()` 成功清除 LRU flag 并移动到 `dst` 后 | 调用者持有 `lruvec->lru_lock`，IRQ disabled | 原 LRU class、`scan_control`、request/priority/scan | 权威观测 `ISOLATE` |
| 显式 isolate | `folio_isolate_lru()` | 入口要求未持有 `lru_lock` 且 IRQ enabled，内部会持锁 | 无 `scan_control` | 可观测但无 reclaim 上下文；首版只覆盖 reclaim isolate，其他首次后续事件按 late discovery 处理 |
| putback | `move_folios_to_lru()` 中 `lruvec_add_folio()` 之后，以及 `folio_putback_lru()` 的实际 add 路径 | 前者持 `lruvec->lru_lock`；后者最终经 per-CPU batch 进入 `lru_add()` | active/inactive 目标 class；caller 可提供 reclaim ctx | reclaim caller 在 move 前/成功后关联上下文；普通 putback 退化为 `ADD_LRU`/late discovery |
| reclaim success | `shrink_folio_list()` 的 `free_it:`，计入 `nr_reclaimed` 前 | folio 已解锁、仍有 isolation ref，尚未 uncharge/free；可 `cond_resched` 的进程上下文 | 完整 folio 元数据及 `scan_control` | 权威观测 `RECLAIMED`，随后立即从 active shadow table 删除 |
| release/free | `__folio_put()` 与 `folios_put_refs()` 的 refcount-to-zero 分支，在 memcg uncharge 前 | 可在进程或 IRQ 上下文；批量 API 文档允许持 spinlock | folio、order、memcg、nid；无 reclaim ctx | 权威观测被跟踪对象的 `FREE`；未知对象不创建新生命周期 |
| migration | `mm/migrate.c:migrate_folio_done()` 附近的成功完成路径 | src/dst 均受迁移协议保护；具体 caller 可睡眠 | src/dst folio、nid、memcg、order | 条件观测 `MIGRATE`；以源生命周期终止和目标 late discovery 表达，不伪造跨 token 原子关系 |
| memcg charge | `mem_cgroup_charge()` 及 charge commit 路径 | 早于 LRU add；可能分配/睡眠 | folio 与 memcg | 不作为必需 discover 点；`ADD_LRU` 时读取最终绑定 |
| memcg reparent/domain change | memcg offline/reparent 与后续 folio 访问分散 | 不存在覆盖所有 folio 且低成本的单一事件点 | 后续事件可重新读取 domain | 条件观测：已跟踪 entry 的后续事件发现 domain 改变时发 `DOMAIN_CHANGE`；无后续事件则不可观测 |
| compound split | `split_huge_page_to_list_to_order()` / `__split_folio_to_order()` | 锁、xarray、memcg 与 LRU 操作交织 | 原 head 与新 heads | **NOT RELIABLY OBSERVABLE**：L0.3A 不侵入 split 内部；后续新 head 事件创建新 token，旧记录在终态/disable 清理 |
| compound merge | THP collapse/hugetlb 等路径分散 | 多种锁与分配上下文 | 无统一 classic-LRU 单点 | **NOT RELIABLY OBSERVABLE**；后续 LRU 事件按 head folio 归一化 |

## 3. 锁与分配审计

### 3.1 LRU 热路径

`folio_batch_move_lru()` 在调用 `lru_add()`、`lru_activate()`、
`lru_deactivate*()` 前通过 `folio_lruvec_relock_irqsave()` 获取
`lruvec->lru_lock`。`isolate_lru_folios()` 也在该锁下运行。因此这些 hook：

- 不能 `GFP_KERNEL`；
- 不能等待 mutex；
- 不能格式化字符串或遍历无界结构；
- 不能通过 `folio_get()` 延长对象生命周期；
- 只能执行 disabled 快速判断、固定哈希查找、短自旋锁临界区和 trace record 拷贝。

### 3.2 release 路径

`folios_put_refs()` 明确允许在 IRQ 上下文或持有 spinlock 时调用。
`__folio_put()` 也不是只限可睡眠上下文。因此 FREE hook 使用同一无分配接口。
观测必须发生在 `mem_cgroup_uncharge*()` 和物理页归还 allocator 之前。

### 3.3 预分配策略

运行时 enable 在 debugfs write 的进程上下文完成：预先分配固定 entry 数组、
bucket 数组和固定 tombstone 数组。hook 永不分配。enable 失败只增加
`alloc_fail` 并返回错误；MM 原生路径不感知 observer 失败。

## 4. 上下文关联

L0.2 的 `scan_control.myks_observer_ctx` 是 reclaim 上下文权威来源。
L0.3A 在 `myks_reclaim_ctx_begin_scan()` 保存当前 `scan_seq`，并在
`isolate_lru_folios()`、`shrink_folio_list()` 与 putback caller 中只读：

- `request_id` 来自 active request；
- `priority_seq` 来自当前 priority；
- `scan_seq` 来自当前 `shrink_lruvec()`；
- `reclaim_source` 原样传播；
- 非 reclaim 的 add/activate/deactivate/free 使用 0/UNKNOWN，绝不沿用旧值。

## 5. 可靠性分类

### 权威观测

- ADD_LRU、ACTIVATE、DEACTIVATE；
- reclaim ISOLATE；
- reclaim RECLAIMED；
- 已跟踪对象的 FREE；
- reclaim caller 中成功返回 LRU 的 PUTBACK。

### 条件或近似观测

- MIGRATE：成功迁移可观察，但首版不承诺跨源/目标 token 的原子配对；
- DOMAIN_CHANGE：仅在已跟踪对象发生后续事件时发现；
- 非 reclaim 显式 isolate/putback：缺少 request/scan，上游事件可能早于 enable。

### NOT RELIABLY OBSERVABLE

- 没有后续事件的 memcg reparent；
- 所有 compound folio split/merge 的完整一一映射；
- observer 启用前已经发生的历史事件；
- trace buffer 覆盖掉的事件。

这些缺口通过 `late_discovery`、`unknown_previous_state` 与用户态
`TRACE_TRUNCATION` 分类表达，不伪造事件。

## 6. MGLRU 边界

L0.3A 只声明 classic-LRU 语义。enable 时调用现有 MGLRU runtime guard；
MGLRU 已启用则拒绝并累计 `mglru_rejected`。运行中每个热路径还执行极短
enabled 判断；若 MGLRU 状态后来改变，观测停止并记录错误，不把 generation
LRU 冒充 active/inactive classic LRU。
