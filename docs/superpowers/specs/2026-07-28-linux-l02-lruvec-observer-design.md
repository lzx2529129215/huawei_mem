# Linux L0.2 Classic-LRU lruvec Observer 设计

状态：设计规范，等待人工审阅

本文只规定 Linux 6.17 classic-LRU 的只读 `lruvec` 观测边界、数据契约、
验证方式和后续实现拆分。本轮不实现其中任何内核、用户态或测试代码。

## 1. 背景、目标与非目标

### 1.1 目标链路

L0.2 的数据链路固定为：

```text
Linux reclaim path
  -> 当前 (memcg_id, nid, lruvec) 聚合快照
  -> tracepoint / debugfs
  -> lruvec_trace_parser
  -> kernel_lruvec_snapshot store
  -> Shadow alignment checker
```

L0.2 只把 Linux 原生 classic-LRU 的当前聚合状态送入用户态，供后续对照
现有 Shadow LRU。观测对象是实际正在处理的 `(memcg_id, nid, lruvec)`，不是
全系统页面图。

### 1.2 硬边界

L0.2 必须满足以下不变量：

1. 不改变 Linux 原生回收、优先级、扫描比例、写回、换出、demotion 或
   kswapd/direct/memcg 决策。
2. 不修改 Shadow 页面链，不创建 Shadow domain/lruvec，不移动页面，不执行
   candidate，也不把内核聚合计数解释成页面级对齐。
3. 不实现 `PAGE_ADD`、`PAGE_ACTIVATE`、`PAGE_DEACTIVATE`、`PAGE_MOVE`、
   `PAGE_ISOLATE`、`PAGE_PUTBACK`、`PAGE_RECLAIMED` 等生命周期事件。
4. 不调用或改变 `shrink_folio_list()`、`isolate_lru_folios()`、原生 LRU 链、
   folio flags 或任何原生回收决策。
5. 不实现 demote/reclaim/protect/prewash 执行接口，不实现预测策略，不做
   MGLRU generation 到四条 classic LRU 的映射。
6. 观测器关闭、采集失败、trace 缓冲区满、debugfs 无人读取或用户态组件退出
   时，Linux 行为必须等同于未启用观测器。

## 2. 基线、分支与历史策略

L0.2 从 `main@a89e7f692f51526ef22a51ad246e4cb007a4b9d7` 创建：

- 分支：`feat/linux-l02-lruvec-observer`
- worktree：`/home/lzx/Desktop/huawei/myself-kswapd-l02`
- 原 L0.1 worktree：`/home/lzx/Desktop/huawei/myself-kswapd-l01`

主分支已有 per-`(memcg_id,nid)` Shadow LRU、candidate snapshot/revalidation、
双向 validator 和 physical Shadow 链。L0.1 worktree 与 Shadow、integration
等既有 worktree 均为只读输入，不在本任务中修改、合并、删除或 push。

后续实施若需要 L0.1 前置，只能以审阅过的提交边界选择性引入 observe-only
前置；不直接 merge 整个 L0.1 历史。L0.1 的 patch 只作为 Linux 6.17 本地源树
的受控迁移材料，不能把 `Linux6.17/` 整树纳入仓库。

## 3. 现有实现事实与复用边界

### 3.1 Shadow 侧

当前 Shadow 实际对象关系为：

```text
reclaim_engine
  +-- shadow_pages: page_id -> shadow_page
  +-- shadow_domains: memcg_id -> shadow_domain
                         +-- node_table: nid -> shadow_lruvec
```

`shadow_lruvec` 由 `(memcg_id,nid)` 唯一定位，含四条普通链和一条
`isolated` 链。`shadow_lruvec_get_stats(engine, memcg_id, nid, stats)` 是现有
只读 aggregate 接口，返回四条链的 `nr_pages[]`、isolated 计数、回收/迁移计数
和 validation flags。`shadow_collect_lruvec_candidates()` 只复制候选快照，
`shadow_candidate_revalidate()` 按位置、状态、LRU 和 event sequence 重验证。

Shadow 的 `shadow_engine_validate()` 只能在没有并发 Shadow 事件、扫描、候选
收集、domain destroy 或 engine destroy 的 quiescent 点调用。L0.2 alignment
必须调用公开只读统计接口；不得触碰 `shadow_page *`、内部锁或生命周期接口。

当前 Shadow 有 `reclaim_domain` 的既有 v1 策略/统计对象，但没有 L0.2 所需的
`kernel_lruvec_snapshot` store、对齐状态机或内核事件适配器。当前公开
`policy.h` 的动作/配置不构成 L0.2 policy overlay，不能用它改变 physical 链。

### 3.2 L0.1 事实

L0.1 分支为 `feat/linux617-myself-kswapd-l01`，当前 HEAD 为
`bd1bb6c4d435eb0a29c23181e82ba960814ad0a5`。它在 `balance_pgdat()` 中观测
kswapd request、priority round 和 request end，使用：

- `struct myks_kswapd_request_ctx` 保存 request id、pass/round 序号、累计
  scanned/reclaimed、停止/冻结/退出原因和 validation flags；
- `myks_kswapd_request_begin()`、`myks_kswapd_round_begin()`、
  `myks_kswapd_priority_round()`、`myks_kswapd_request_end()` 等函数生成
  observe-only 事件；
- trace 事件 `myself_kswapd_request_begin`、`priority_round`、`request_end`；
- `tools/myself_kswapd/parse_kswapd_trace.py` 将文本解析成请求、round 和
  efficiency CSV，并保留不完整请求、序号错误、总量不符和 validation flags。

L0.1 的真实 trace 字段包括 `request_id`、`nid`、`priority`、`reclaim_idx`、
`nr_to_reclaim`、`main_scanned`、`soft_scanned`、`total_scanned`、
`main_reclaimed`、`soft_reclaimed`、`reclaimed_delta`、回收能力布尔值、
`pass_seq`/`round_seq`、`elapsed_ns` 和 `validation_flags`。这些字段可作为
L0.2 的 request/stage 关联输入，但不能替代 lruvec snapshot 字段。

L0.1 当前只覆盖 kswapd；没有 direct reclaim 或 memcg reclaim 的完整观测
基础，也没有 lruvec 聚合、debugfs、sample、heartbeat 或 Shadow 对齐。

## 4. 双模式与身份映射

### 4.1 模式

观测器启动时必须选择一个且仅一个模式：

| 模式 | `memcg_id` | `nid` | 原生对象 | 用途 |
| --- | --- | --- | --- | --- |
| `MEMCG_LRUVEC` | `cgroup_id(memcg->css.cgroup)` | `pgdat->node_id` | `mem_cgroup_lruvec(memcg, pgdat)` | Linux 6.17 主验证模式 |
| `GLOBAL_LRU` | `SHADOW_ROOT_MEMCG_ID` | `pgdat->node_id` | `mem_cgroup_lruvec(NULL, pgdat)` | 后续 OpenHarmony 传统全局 LRU |

`memcg_css_id = memcg->css.id` 仅作为 debug 字段输出，不作为稳定对齐键。
对齐键永远是 `(memcg_id,nid)`。`SHADOW_ROOT_MEMCG_ID` 必须与真实
`cgroup_id()` 返回值建立明确的保留值约束，不能与任意真实 cgroup id 冲突。

`CONFIG_MEMCG=n` 时只允许 `GLOBAL_LRU`。此时 Linux 的
`mem_cgroup_lruvec()` 是返回 `&pgdat->__lruvec` 的 inline helper，不能把
不存在的 memcg 解释为 `MEMCG_LRUVEC`。

### 4.2 classic-LRU 运行条件

本轮只支持 classic LRU。`lru_gen_enabled()` 位于 Linux 6.17
`include/linux/mm_inline.h`，通过 LRU_GEN static key 表示运行时状态。

- `lru_gen_enabled() == false`：允许 classic-LRU observer；
- `lru_gen_enabled() == true`：observer 拒绝启动，状态为
  `REJECTED_MGLRU`，不输出伪装的四链快照；
- `CONFIG_LRU_GEN=y` 可以编译，但运行时仍必须拒绝；
- 内核模块不得自行改变 MGLRU 开关；启动脚本可在外部显式关闭 MGLRU。

拒绝发生在配置生效前，不得进入 reclaim 热路径。用户态 parser/store 也必须
保留 `UNSUPPORTED_MGLRU`，不能把拒绝记录当作零值快照。

## 5. Linux 6.17 观测模型

### 5.1 真实结构和 LRU 映射

Linux 6.17 `include/linux/mmzone.h` 中的 `struct lruvec` 包含
`lists[NR_LRU_LISTS]`、`spinlock_t lru_lock`、cost/refault 状态、可选的
`lrugen` 和 `pgdat`。`enum lru_list` 的四条 classic 链为：

```text
LRU_INACTIVE_ANON
LRU_ACTIVE_ANON
LRU_INACTIVE_FILE
LRU_ACTIVE_FILE
```

`include/linux/mm_inline.h:folio_lru_list()` 根据 unevictable、file 和 active
flags 计算 folio 应处的 LRU 枚举；它只能用于受控的 debug sample，不能遍历
folio 链构成聚合统计。

`struct pglist_data` 的 `node_id` 是 nid，`__lruvec` 是 memcg 关闭时的节点
LRU；在 memcg 开启时，注释明确要求使用 `mem_cgroup_lruvec()` 查找 lruvec。
`struct mem_cgroup` 含 `css` 和 `nodeinfo[]`，其中 per-node `lruvec` 是
memcg 模式的原生对象。

四条聚合字段的来源固定为：

| 快照字段 | Linux helper/index | 语义 |
| --- | --- | --- |
| `inactive_anon` | `lruvec_page_state(lruvec, NR_INACTIVE_ANON)` | 当前 lruvec 的近似计数 |
| `active_anon` | `lruvec_page_state(lruvec, NR_ACTIVE_ANON)` | 当前 lruvec 的近似计数 |
| `inactive_file` | `lruvec_page_state(lruvec, NR_INACTIVE_FILE)` | 当前 lruvec 的近似计数 |
| `active_file` | `lruvec_page_state(lruvec, NR_ACTIVE_FILE)` | 当前 lruvec 的近似计数 |
| `isolated_anon` | `node_page_state(pgdat, NR_ISOLATED_ANON)` | 当前 Linux 版本的 node 级计数 |
| `isolated_file` | `node_page_state(pgdat, NR_ISOLATED_FILE)` | 当前 Linux 版本的 node 级计数 |

`lruvec_page_state()`/`lruvec_page_state_local()` 位于
`include/linux/memcontrol.h`；memcg 版本从 lruvec 的 vmstat 读取，memcg 关闭
版本退化到 `node_page_state(lruvec_pgdat(lruvec), idx)`。这些读取是近似
统计快照，不长期持有 `lru_lock`，不能声称四条链在同一时刻具有强一致性。

真实 classic reclaim 的锁区间也必须保持只读设计：
`shrink_inactive_list()` 在 `isolate_lru_folios()` 前持有
`spin_lock_irq(&lruvec->lru_lock)`，完成 isolate 计数后解锁；folio list 在锁外
交给 `shrink_folio_list()`，随后再次持有同一把锁执行 putback/回链和计数更新。
`shrink_active_list()` 同样围绕 LRU 摘取和回链分段持有该锁，不能把其内部
folio 操作当作可插入的长期锁区间。L0.2 聚合 observer 不插入这些锁区间，
bounded sample 才允许在明确的短锁区间内复制轻量字段。

当前 Linux 6.17 的 isolated 统计在 `mm/vmscan.c` 中通过
`__mod_node_page_state(pgdat, NR_ISOLATED_ANON + file, ...)` 更新，因此
`MEMCG_LRUVEC` 下不能按 memcg 归属拆分。快照必须同时带
`field_valid_mask`/`field_scope`：memcg 模式的 isolated 字段标记
`NODE_SCOPE_UNSUITABLE_FOR_MEMCG`，alignment 不得比较该字段；global 模式
可以比较 node 级 isolated 值。不能以 node 值复制到每个 memcg 快照。

### 5.2 回收上下文关联

`struct scan_control` 的 `nr_scanned`、`nr_reclaimed`、`priority`、
`reclaim_idx`、`nr_to_reclaim` 和 `target_mem_cgroup` 是回收上下文统计。
它们不是 LRU 链长度。L0.2 快照中的 `scanned_total` 和 `reclaimed_total`
保留上下文的累计值，用户态通过同一 request 的前后 snapshot 计算 delta，
不将累计值与链长度相加或混用。

回收来源枚举固定为：`RECLAIM_KSWAPD`、`RECLAIM_DIRECT`、
`RECLAIM_MEMCG`、`RECLAIM_UNKNOWN`。每条记录必须带
`request_id`、`snapshot_seq`、`timestamp_ns`、`reclaim_source`、`stage`、
`priority`、`memcg_id` 和 `nid`。

阶段枚举固定为：`REQUEST_BEGIN`、`PRIORITY_BEGIN`、`SCAN_BEFORE`、
`SCAN_AFTER`、`PRIORITY_END`、`REQUEST_END`、`HEARTBEAT`、`DEBUGFS`。
接入顺序是 kswapd、direct reclaim、memcg reclaim。每个接入点必须记录
实际 lruvec，而不是在 request 结束时枚举所有 memcg×nid。

Linux 6.17 的候选接入位置如下：

| 来源 | request/priority 关联 | scan-before/after 关联 | 说明 |
| --- | --- | --- | --- |
| kswapd | `balance_pgdat()` 中已有 L0.1 request/round 边界 | `shrink_node()` 调用前后及 `scan_control` 累计值 | 复用 request 上下文，不改控制流 |
| direct | `try_to_free_pages()`/`do_try_to_free_pages()` 的一次调用 | `shrink_node()` 或其当前 lruvec 调用前后 | 需避免把一个 zonelist 调用误标成单一 lruvec |
| memcg | `try_to_free_mem_cgroup_pages()`、`mem_cgroup_shrink_node()` | `shrink_lruvec()` 当前 lruvec 调用前后 | 以 `target_mem_cgroup` 和 pgdat 映射 |

`shrink_node_memcgs()` 已按 memcg 迭代并调用
`mem_cgroup_lruvec(memcg, pgdat)`；`shrink_lruvec()` 是 classic LRU 的主要
聚合关联点。L0.2 只在这些真实上下文存在时采样，不为没有明确归属的记录
猜测 memcg 或 nid，无法关联时使用 `RECLAIM_UNKNOWN` 并设置错误计数。

### 5.3 锁与一致性

聚合快照：

- 不遍历 `folio` 链；
- 不长期持有 `lru_lock`；
- 使用现有统计 helper，标记 `consistency=APPROXIMATE`；
- 不把多个 helper 读取包装成强一致事务；
- 不能在统计 helper 失败时回退为未标记的零值。

folio 调试 sample 只在 `sample_enabled=1` 时执行。它短暂持有当前
`lruvec->lru_lock`，每条普通 LRU 最多复制 `N` 项，建议硬上限
`sample_limit_per_lru <= 32`，锁内只复制固定大小轻量字段，立即解锁，
锁外再格式化、trace 或写 debugfs。sample 的 `consistency` 为
`LOCKED_SAMPLE`。

锁内禁止动态扩容、路径解析、用户态拷贝、获取会形成反向锁序的 page lock、
修改 folio/LRU。默认不采样 isolated 或 unevictable；未来若支持必须新增
明确的数据契约和验证项。

## 6. 聚合快照契约

### 6.1 结构

`kernel_lruvec_snapshot` 至少包含：

```text
snapshot_seq       : 全局单调递增 u64
timestamp_ns       : monotonic timestamp
request_id         : request 关联 u64
memcg_id           : 稳定对齐键
memcg_css_id       : 仅 debug
nid                : pgdat->node_id
reclaim_source     : 枚举
lru_mode           : MEMCG_LRUVEC 或 GLOBAL_LRU
consistency        : APPROXIMATE 或 LOCKED_SAMPLE
stage              : 阶段枚举
priority           : scan_control priority；无上下文时显式无效
inactive_anon      : 采集瞬间数量
active_anon        : 采集瞬间数量
inactive_file      : 采集瞬间数量
active_file        : 采集瞬间数量
isolated_anon      : 按 field_scope 解读
isolated_file      : 按 field_scope 解读
scanned_total      : 回收上下文累计统计
reclaimed_total    : 回收上下文累计统计
field_valid_mask   : 字段可比较性
validation_flags   : 采集/溢出/关联错误
```

四条 LRU 数量是采集瞬间状态；`scanned_total`/`reclaimed_total` 是回收
上下文统计。用户态可计算 delta，但不能把它们当成链长度。全局
`snapshot_seq` 分配必须使用不可回退的原子序列；trace 丢失不会复用序号。

### 6.2 source/stage 顺序与丢失

同一 request 的正常顺序是 `REQUEST_BEGIN`，一个或多个
`PRIORITY_BEGIN -> SCAN_BEFORE -> SCAN_AFTER -> PRIORITY_END`，最后
`REQUEST_END`。并发 CPU 的不同 request 不要求全局按时间串行；store 必须
按 `(request_id, snapshot_seq)` 保存原始顺序并报告交错。

trace buffer 满只增加 `observer_counters.trace_dropped`，不阻塞、不重试到
回收上下文、不改变 reclaim。parser 看到 `snapshot_seq` 间隙必须报告 GAP，
但坏记录不能阻止后续记录解析。

## 7. Tracepoint 与 debugfs 接口

### 7.1 Tracepoint

新增事件组为 `myself_kswapd`：

- `myself_kswapd:lruvec_snapshot`：默认的聚合快照事件；
- `myself_kswapd:lruvec_sample`：默认关闭，仅受 `sample_enabled` 和
  固定容量限制控制。

两个事件都使用第 6 节字段契约；sample 额外带每条 LRU 的 sample count、
sample limit 和 sample field validity。事件只在 observer active 且对应事件
启用时发出。字段缺失、枚举非法、序列溢出和 MGLRU 拒绝必须进入
`validation_flags`/error trace，不伪造数据。

### 7.2 debugfs

目录固定为 `/sys/kernel/debug/myself_kswapd/`：

| 文件 | 方向 | 内容/限制 | 错误语义和权限 |
| --- | --- | --- | --- |
| `observer_status` | 只读 | active、mode、MGLRU 状态、计数器、最后错误、丢失数 | 普通读取不触发全量快照 |
| `observer_config` | 读写 | enable、mode、memcg/nid 过滤、sample、heartbeat、输出上限 | 仅管理员可写；非法枚举/越界返回 `-EINVAL`，并保持旧配置 |
| `snapshot` | 只读 | 单目标或已配置过滤的聚合快照 | 固定最大输出；读取失败只记 observer error |
| `samples` | 只读 | 最近一次有界 sample 或 truncation 信息 | 无 sample 时返回明确空状态，不触发 sample |

配置写入使用临时解析结果，完整校验通过后一次性替换；不允许并发写者
交错形成半套配置。配置生效时不得等待 lru_lock 或执行全量枚举。读者看到的
快照是固定上限的 bounded 输出，超限必须带 `truncated=1`。

人工 `snapshot` 允许单目标、按 memcg、按 nid 或有上限的全量枚举。无过滤的
全量请求必须拒绝或严格截断，并在结果中标明上限；它不能被热路径复用。

## 8. Heartbeat 与人工观测

`heartbeat_ms` 默认值为 `0`，只用于调试。启用后由延迟 workqueue 执行，最小
周期不得低于 `1000ms`，且必须设置明确的 memcg 或 nid 过滤。没有过滤时
拒绝周期性的全量枚举。heartbeat 失败只增加统计和 error trace，不影响任何
reclaim。observer 关闭时取消或使待处理 heartbeat 失效，不向 native reclaim
路径插入睡眠或同步等待。

## 9. 用户态组件和严格边界

### 9.1 Parser

`lruvec_trace_parser` 将 trace 文本转为 `kernel_lruvec_snapshot`。解析步骤
是字段存在性检查、整数范围检查、枚举检查、序列/阶段检查，再提交 store。
错误类型至少包括 `MISSING_FIELD`、`INVALID_INTEGER`、`INVALID_ENUM`、
`OVERFLOW`、`UNSUPPORTED_MODE`。坏记录标记并跳过，不阻止后续记录。

现有 L0.1 parser 只解析 kswapd request/round/end，不能直接当作本组件的
parser；它的保留错误证据和测试风格可以作为行为参考。

### 9.2 Store

`kernel_snapshot_store` 按 `(memcg_id,nid)` 保存最新有效快照，同时保留：

`last_snapshot_seq`、`last_request_id`、`last_priority`、`last_stage`、
`last_timestamp`、最新 snapshot、字段有效性和错误计数。

状态检查至少识别 `DUPLICATE`、`STALE`、`GAP`、`STAGE_ORDER_ERROR`。旧数据
不能覆盖新数据；重复数据可记录但不可重复计入 delta。跨 request 的阶段交错
按 request_id 分开判断，不能用单一全局 stage 状态误报。

### 9.3 Alignment

`shadow_alignment` 只读 kernel snapshot 和 Shadow physical aggregate，输出：

`MATCH`、`COUNT_DRIFT`、`MISSING_SHADOW_LRUVEC`、`MISSING_KERNEL_LRUVEC`、
`STALE_KERNEL_SNAPSHOT`、`UNSUPPORTED_PAGE_LEVEL_COMPARE`、
`UNSUPPORTED_MGLRU`。

计数方向固定为：`delta = kernel_count - shadow_count`。对四条 physical LRU
逐项报告 raw kernel、raw Shadow、delta、validity 和 consistency；Linux
memcg 模式 isolated node-scope 字段不参与比较并报告字段不可比，而不是
报告 MATCH 或 COUNT_DRIFT。

Alignment 严禁创建 Shadow domain/lruvec、创建 `shadow_page`、移动页面、
自愈、执行 candidate 或把缺失对象补零。它也不比较 policy 字段。

### 9.4 STRICT 与 BOOTSTRAP_AGGREGATE

`STRICT` 只接受当前 mode、键、MGLRU 状态和 freshness 均符合要求的快照；
任何缺失或不支持字段都输出明确状态，不创建对象。

`BOOTSTRAP_AGGREGATE` 仅建立独立的 kernel aggregate baseline，允许没有
Shadow 对象，但不创建 `shadow_page`、不修改 Shadow 四链、不参与 candidate，
不能称为页面级 Shadow 对齐。两种模式的输入、输出和通过条件必须分开，不能
用 bootstrap baseline 伪造 strict match。

`lruvec_observer_cli` 只负责配置、读取、解析、store 查询和 alignment 展示，
不提供 reclaim 执行命令。

## 10. Physical 与 policy 双层语义

Shadow physical 层的可比较字段是：

`active_anon`、`inactive_anon`、`active_file`、`inactive_file` 和
`isolated`。它们代表内核真实状态，只能由后续真实内核生命周期事件更新；
L0.2 聚合快照本身不更新 Shadow physical 链。

policy 层仅固定未来边界，可含 `reclaim_score`、`protect_score`、
`suggested_action`、`confidence`、`valid_until_ns`、`policy_seq`，动作名可
表达 `NONE`、`PROTECT`、`DEMOTE`、`RECLAIM`、`PREWASH`。L0.2 不实现完整
policy overlay，alignment 只比较 physical。

特别地，policy 的 `DEMOTE_HINT` 不能自动把 Shadow physical active 链移到
inactive 链。正确的未来流程是：

```text
policy 产生 DEMOTE 请求
  -> 内核验证并真实执行
  -> 内核生命周期事件
  -> Shadow physical 链更新
```

## 11. 错误隔离与资源上限

所有 observer 错误只通过 `observer_counters`、error trace 和
`observer_status` 暴露。错误路径必须：

- 不向 reclaim 返回策略性失败，不改变原生返回值；
- 不在热路径动态分配大对象；
- 不遍历全部 memcg×nid，不遍历 folio 链，不解析 cgroup 路径字符串；
- 不因用户态 parser/store/alignment 退出而阻塞内核；
- 不因 Shadow 缺失、错误或 validator flags 反向修改 Linux。

热路径只处理当前 lruvec。debugfs 人工全量操作另行受过滤和硬上限约束。
sample 每条 LRU 的上限默认由配置给出，但绝不能超过 32；heartbeat 的最小
周期为 1000ms。

## 12. 验收与测试设计

后续实现必须用 TDD、小提交和每阶段独立验证；本节是验收契约，不是本轮
实施计划。

### 12.1 内核/KUnit

覆盖：

- `MEMCG_LRUVEC`/`GLOBAL_LRU` 模式识别、身份映射、`CONFIG_MEMCG=n` 限制；
- MGLRU 运行时拒绝，包括 `CONFIG_LRU_GEN=y` 可编译但 enabled 时拒绝；
- 四条 LRU 统计、isolated scope/validity、全局 seq 单调递增；
- request、source、stage、priority 和 scan-before/after 关联；
- 关闭观测、过滤、非法配置、trace 丢失和错误隔离；
- sample 默认关闭、`N=0`、`N=32`、超过上限、锁外输出和采样失败；
- heartbeat 默认关闭、最小周期、过滤必需和失败不影响 reclaim。

### 12.2 Trace/debugfs

覆盖 tracepoint 字段、阶段顺序、request 交错、丢失和 seq gap；debugfs
覆盖单目标、memcg/nid 过滤、有界全量、truncation、非法配置、heartbeat
过滤和 sample 上限。检查读 debugfs status 不触发全量快照。

### 12.3 用户态

Parser/store 覆盖正常记录、缺字段、非法整数、非法枚举、溢出、duplicate、
stale、gap 和阶段交错。Alignment 覆盖全部状态、delta 方向、缺对象、过期、
MGLRU、isolated 不可比、不创建对象、不修改链和 policy 不影响 physical。
Bootstrap 覆盖不创建 page、不修改四链、不参与 candidate。

### 12.4 构建和 runtime smoke

至少准备：`CONFIG_MEMCG=y`、`CONFIG_DEBUG_FS=y`、`CONFIG_TRACING=y`、
`CONFIG_LRU_GEN=n` 的构建验证；另验证 `CONFIG_LRU_GEN=y` 可以编译且运行时
拒绝 observer。需要提供关闭 observer 后的行为等价检查。

当前环境没有已重启到 L0.2 observer 的 Linux 内核，因此真实 runtime smoke
在本设计阶段记录为 `NOT RUN / ENVIRONMENT BLOCKED`；不得用离线 parser 测试
或静态阅读替代真实运行时结论。

## 13. 后续实施边界

后续建议按独立可审阅提交推进：必要 L0.1 observe-only 前置、classic lruvec
snapshot model、kswapd、direct reclaim、memcg reclaim、debugfs、bounded
folio sample、heartbeat、parser、store、bootstrap、alignment、CLI，最后再
做 tests/runtime review。每阶段必须 TDD、独立验证，并保持 native reclaim
和 Shadow physical 链不变。实施阶段不得提前扩展到执行器、MGLRU 映射或完整
policy engine；完成后需独立只读审查，不 push、不合并 main。

L0.3 的边界是生命周期事件、内核真实执行反馈、policy overlay 和执行器闭环。
L0.2 可以为这些后续能力保留稳定的 snapshot/source/stage 字段，但不得在
本阶段提前添加执行请求、页面事件或由 policy 驱动物理链迁移。

## 附录 A：Shadow 现有接口映射

| 设计概念 | 真实文件 | 真实结构/函数 | 直接复用 | L0.2 新增只读边界 |
| --- | --- | --- | --- | --- |
| Shadow engine | `用户态模拟器/v1/src/core/internal.h` | `struct reclaim_engine` | 仅作宿主对象 | 不向 engine 注入 kernel state |
| domain | `用户态模拟器/v1/src/core/internal.h` | `struct shadow_domain`，`memcg_id` | 不直接暴露 | alignment 只用键查询 |
| lruvec | `internal.h`、`shadow_lru.h` | `struct shadow_lruvec`、`shadow_lruvec_get_stats()` | 是 | 不扩展生命周期接口 |
| physical 四链/isolated | `shadow_lru.c`、`shadow_lru.h` | `lists[]`、`isolated`、`shadow_lruvec_stats` | 是 | kernel snapshot 只读对照 |
| candidate | `shadow_lru.h`、`shadow_lru.c` | collect/revalidate API | 否 | L0.2 明确不调用执行 |
| validator | `shadow_lru.c`、`validator.c` | `shadow_engine_validate()` | 仅静止点诊断 | 不由 kernel trace 自动触发 |
| policy | `include/myself_kswapd/policy.h` | 现有 v1 policy 类型 | 不作为 L0.2 overlay | 不更新 physical 链 |

## 附录 B：L0.1 候选前置提交清单

以下是只读检查得到的候选边界；本轮不 cherry-pick、不复制、不导入。

| 原 SHA | 提交主题 | 主要修改路径 | L0.2 依赖理由 | 建议 |
| --- | --- | --- | --- | --- |
| `4557c010a451ca161a2b431b2f93d7294d7ac359` | add Linux 6.17 kswapd observe-only adapter | `patches/0002-linux617-myself-kswapd-l01.patch`、`tools/myself_kswapd/*`、`.gitignore`、`patches/README.md` | 提供 request context、trace 基础、parser 行为参考 | 不整提交导入；后续按文件和验证边界选择必要 observe-only 前置 |
| `dfe5107e7207fb9f68b87a50f1cd770e600df288` | refresh Linux 6.17 adapter patch | `patches/0002-linux617-myself-kswapd-l01.patch` | 使受控 patch 与当前本地 Linux 源保持一致 | 不单独 cherry-pick；以后以审阅后的 patch 内容为准 |
| `362611828bac62c4a820498ccc718c2b87861fef` | cover kswapd observer validation paths | patch、`tools/myself_kswapd/parse_kswapd_trace.py`、parser fixtures/tests | parser 的坏记录与 validation 证据可复用 | 仅作为测试契约参考，不导入 L0.2 实现 |
| `f427ffca0e21e9a88513e396ca200890bbcbaf84` | preserve per-cpu trace statistics | `tools/myself_kswapd/capture_kswapd_trace.sh` | 只影响 L0.1 捕获脚本的统计保存 | 不属于 L0.2 内核前置 |
| `bd1bb6c4d435eb0a29c23181e82ba960814ad0a5` | preserve begin snapshot order types | `patches/0002-linux617-myself-kswapd-l01.patch` | 依赖 L0.1 patch 的类型修正 | 不单独导入；随必要 patch 边界重新验证 |

L0.1 的 Kconfig/Makefile 真实路径为
`Linux6.17/mm/myself_kswapd/Kconfig` 和 `Makefile`；其 adapter、公开头文件、
trace 唯一实例和工具测试均保持在 L0.1 worktree，未被本设计分支修改。

## 附录 C：Linux 6.17 接口定位

| 观测项 | 结构/helper | 真实文件 | 锁/一致性 | CONFIG 依赖 |
| --- | --- | --- | --- | --- |
| lruvec | `struct lruvec`、`lru_lock`、`lists[]`、`pgdat` | `include/linux/mmzone.h:654` 附近 | list 变更受 lru_lock；聚合读取近似 | 基础；`pgdat` 字段随 MEMCG 条件编译 |
| node | `struct pglist_data::node_id`、`__lruvec` | `include/linux/mmzone.h:1360` 附近 | node stats 近似 | NUMA/UMA 均有 node id |
| memcg | `struct mem_cgroup::css`、`nodeinfo[]` | `include/linux/memcontrol.h` | 生命周期需遵循内核 memcg 规则 | `CONFIG_MEMCG` |
| lru mapping | `enum lru_list`、`folio_lru_list()` | `mmzone.h`、`mm_inline.h` | sample 时在 lru_lock 内 | classic LRU；MGLRU 另有路径 |
| lruvec counts | `lruvec_page_state()` | `include/linux/memcontrol.h`、`mm/memcontrol.c` | 近似 vmstat | MEMCG 版本和 disabled stub 均存在 |
| global counts | `node_page_state()` | `include/linux/vmstat.h`、`mm/vmscan.c` | 近似 node vmstat | 基础 |
| lruvec mapping | `mem_cgroup_lruvec()` | `include/linux/memcontrol.h` | 当前 pgdat/memcg 映射 | `CONFIG_MEMCG=n` 返回 `pgdat->__lruvec` |
| isolated | `NR_ISOLATED_ANON/FILE`、`__mod_node_page_state()` | `include/linux/vmstat.h`、`mm/vmscan.c` | node scope；不是 memcg lruvec | 基础 |
| runtime MGLRU | `lru_gen_enabled()` | `include/linux/mm_inline.h` | static key 读取 | `CONFIG_LRU_GEN` |
| classic scan | `shrink_lruvec()`、`shrink_node_memcgs()` | `mm/vmscan.c` | 内部阶段会持有/释放 lru_lock | classic path |
| isolation lock | `spin_lock_irq(&lruvec->lru_lock)`、`unlock_page_lruvec_irq()` | `mm/vmscan.c`、`mm/mmzone.c`/inline helpers | 只读 sample 短持有 | classic path |
| context counters | `struct scan_control` | `mm/vmscan.c` | request 上下文累计 | 基础；memcg 字段随配置 |

### C.1 OPEN QUESTION

以下问题必须在实施前用 Linux 6.17 构建、符号/配置检查或受控运行证据关闭，
不能用猜测替代：

1. 当前 Linux 6.17 只有 node 级 isolated 统计；若 L0.2 必须在
   `MEMCG_LRUVEC` 下提供可比较的 per-memcg isolated 数量，需要确认是否能
   在不改动原生语义的前提下获得真实来源，否则该字段必须保持不可比。
2. direct reclaim 的一个 `try_to_free_pages()` 可能跨多个 zone/lruvec；需要
   构建验证最终采用 `shrink_node()` 周期还是 `shrink_lruvec()` 调用作为
   canonical request/priority 边界，并证明 request_id 不跨调用错误复用。
3. memcg reclaim 的嵌套调用（`try_to_free_mem_cgroup_pages()`、
   `mem_cgroup_shrink_node()` 和 `shrink_node_memcgs()`）需要用真实调用栈
   验证 source 判定及 request 生命周期，避免重复计数。
4. 需要在目标配置下确认 `memcg->css.cgroup` 的 `cgroup_id()` 与
   `memcg->css.id` 的稳定性、复用时序和 debug 输出权限，最终冻结保留
   `SHADOW_ROOT_MEMCG_ID` 的不冲突约束。
5. 需要用 CONFIG_MEMCG=y/n 的编译矩阵确认 observer 头文件依赖、
   `mem_cgroup_lruvec()` disabled inline 和 `lruvec_page_state()` stub 的
   可用性，确保 GLOBAL_LRU 不引入 MEMCG-only 符号。
6. 需要实测 tracepoint 过滤/环形缓冲区丢失时的 `snapshot_seq` gap 证据和
   debugfs bounded 输出边界；静态接口检查不能替代该证据。
7. 需要在真实启用/关闭 MGLRU 的内核上确认 `lru_gen_enabled()` 拒绝时机，
   确保 observer 不会在拒绝前发出任何 classic-LRU 快照。

OPEN QUESTION 不代表本轮失败；它们是设计已明确、证据尚需补齐的边界，
后续未关闭前不得标记实现完成。
