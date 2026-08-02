# Linux L0.3A 页生命周期观测设计

## 1. 目标与非目标

L0.3A 在 L0.2 聚合观测之上建立 observe-only 页身份、物理状态和可重放
事件链。它不改变 Linux LRU、隔离、回收、迁移或释放结果，也不实现价值
评分、预测、planner、executor、保护提示或四条有序 Shadow LRU 链。

## 2. 物理状态机

最小状态：`UNKNOWN`、`ON_LRU_INACTIVE`、`ON_LRU_ACTIVE`、`ISOLATED`、
`RECLAIMED`、`DEAD`。

合法主路径：

```text
UNKNOWN -> ON_LRU_INACTIVE/ACTIVE          DISCOVER or ADD_LRU
ON_LRU_INACTIVE -> ON_LRU_ACTIVE           ACTIVATE
ON_LRU_ACTIVE -> ON_LRU_INACTIVE           DEACTIVATE
ON_LRU_INACTIVE/ACTIVE -> ISOLATED          ISOLATE
ISOLATED -> ON_LRU_INACTIVE/ACTIVE          PUTBACK
ISOLATED -> RECLAIMED                       RECLAIMED
任意非终态 -> DEAD                          FREE
任意非终态 -> DEAD                          MIGRATE(source)
```

observer 中途启用时，首次在 `ISOLATE` 等事件见到对象可从 UNKNOWN 建立
`late_discovery` 生命周期。PUTBACK 没有先前 isolate、重复 terminal 及与当前
物理状态冲突的 activate/deactivate 会计数且打 flag，不改变 Linux 行为。

## 3. 页身份

对外 token：

```c
struct myks_page_token {
	u64 page_id;
	u32 lifecycle_gen;
	u32 order;
};
```

- `page_id` 来自全局单调序列；
- 内部 key 是 `page_folio()` 归一化后的 head PFN；
- 活跃表终态后立即删除，不持有 folio/page 指针或引用；
- 固定容量 tombstone 保存最近 head PFN 与 generation，物理页再次出现时
  generation 增加并累计 `reuse_detected`；tombstone 可覆盖但不会淘汰活跃项；
- trace/debugfs 不输出 PFN、folio 指针或 page 指针。

## 4. 有界 Shadow Page Table

enable 时预分配：固定数量 entry、哈希 bucket 与同规模 tombstone ring。
entry 通过 bucket hlist 索引，空闲 entry 来自固定 freelist；全部由一个短
`spin_lock_irqsave()` 临界区保护。查找是有界哈希链，容量达到 `max_entries`
后拒绝新对象并累计 `capacity_drop`，绝不淘汰活跃 entry。

关闭流程先关闭 enabled gate，再在配置 mutex 下清空 bucket、entry、tombstone
并释放预分配内存。表不持有 folio 引用，因此没有 drain 页引用问题。

## 5. 配置与过滤

独立 debugfs 文件 `page_lifecycle_config` 和 `page_lifecycle_status`，不改变
L0.2 既有文件文本 ABI。配置字段：

- `page_tracking_enabled`，默认 0；
- `target_mode`：MEMCG/GLOBAL；
- `target_memcg_id`；
- `target_nid`；
- `page_type_mask`：ANON/FILE bitmask；
- `max_entries`，范围 1..4096。

enable 必须同时具备有效 target、非零 page type mask、合法容量且 MGLRU 未
启用。MEMCG 模式匹配 `(memcg_id,nid)`；GLOBAL 只允许 `CONFIG_MEMCG=n`。

## 6. 热路径与并发

disabled fast path 是单次 `unlikely(READ_ONCE(page_tracking_enabled))`。
enabled 非目标页只读取 head folio 的 nid/type/memcg 并做常数次比较。目标页
进入固定哈希表短临界区；事件 record 在锁内复制到栈、锁外调用 tracepoint。

hook 不分配、不睡眠、不获取 folio 引用、不改变原生 flags/list/refcount/
返回值。所有分配仅发生于 debugfs enable 的进程上下文。

## 7. L0.2 上下文关系

页事件 record 包含 request_id、priority_seq、scan_seq、reclaim_source、mode、
memcg_id、nid。reclaim 路径只从 active `myks_reclaim_observer_ctx` 复制；普通
LRU 和 release 路径全部填 0/UNKNOWN。L0.2 四个 trace event 的名称、字段、
打印文本及 parser 契约保持不变。

## 8. Trace ABI

新增 `myself_kswapd_page_lifecycle`。producer 仅接收一个不可变 event record
指针（1 个参数），record 包含 action、token、nr_pages、page_type、from/to、
lru_class、mode、memcg_id、nid、request/priority/scan、source、reason、flags。
对外不暴露 PFN 或内核地址。

## 9. Debugfs 与统计

status 一次 open/read 使用一致的配置和原子计数快照，字段包括 enabled、
tracked/max、events、alloc/capacity drop、late/invalid/duplicate/reuse、MGLRU
拒绝和 last_error。L0.3A 不提供全表 dump；最近 transition sample 若实现也
必须固定上限。

## 10. 用户态独立 replay

`parse_page_lifecycle_trace.py` 独立定义状态转换 oracle，不复用内核代码。
它精确识别真实 ftrace event 字段和 legacy fixture 名，按
`(page_id,lifecycle_gen)` 分组，输出文本、JSON 和 CSV transition，并区分：

- `LATE_DISCOVERY`：采集从中间开始；
- `TRACE_TRUNCATION`：输入头尾不完整或显式丢失证据；
- `INVALID_TRANSITION`：在证据完整前提下违反状态机。

## 11. 已知缺口与 L0.3B

split/merge 全量映射、无后续事件的 domain reparent 与 migrate 的源目标原子
配对不在本阶段可靠性承诺内。L0.3A 只证明有界 identity/state 基础；尚未
维护每个 `(mode,memcg_id,nid)` domain 的四条 Shadow LRU 链，以免未经验证的
身份或释放错误扩散成排序结构损坏。

L0.3B 将在本表和 replay 证据通过后增加四链镜像与一致性校验，仍不得由
policy hint 直接移动 physical 链。
