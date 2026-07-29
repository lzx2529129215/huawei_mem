# Linux L0.2 Classic-LRU lruvec Observer 设计规范（修订版）

**状态：设计冻结，可进入实施计划阶段**

**基线：** `main@a89e7f692f51526ef22a51ad246e4cb007a4b9d7`
**目标分支：** `feat/linux-l02-lruvec-observer`
**设计范围：** Linux 6.17 classic LRU 的只读 `lruvec` 观测、用户态解析、聚合存储及 Shadow 对齐
**非目标：** 页面生命周期事件、策略执行、真实 LRU 调整、MGLRU 支持

本文在原始 L0.2 设计规范基础上，关闭了以下接口级未决项：

1. per-memcg isolated 不可获得时的字段作用域；
2. direct reclaim 跨多个 lruvec 时的 request/scan 边界；
3. memcg reclaim 嵌套调用的来源判定与去重；
4. cgroup ID、CSS ID 与 GLOBAL/MEMCG 身份空间；
5. `CONFIG_MEMCG=y/n` 的后端边界；
6. trace 丢失、sequence gap 和 debugfs bounded 输出语义；
7. MGLRU 的启用时与运行时双重拒绝机制。

剩余未完成项均属于**实施证据**，不再改变本设计的数据契约和组件边界。

---

## 1. 背景与目标

### 1.1 当前基础

主分支已经具备用户态 per-`(memcg_id,nid)` Shadow LRU，包含：

- `shadow_domain`；
- 稀疏 `nid -> shadow_lruvec`；
- 四条 classic physical LRU；
- `isolated` 链；
- candidate snapshot 与 revalidation；
- page/domain 生命周期和并发保护；
- quiescent 双向 validator；
- `shadow_lruvec_get_stats()` 只读聚合统计。

L0.1 位于独立 worktree，已经实现 Linux 6.17 `balance_pgdat()` 的 kswapd
observe-only request/priority/end 观测，但尚未提供：

- 当前 `lruvec` 聚合快照；
- direct reclaim 观测；
- memcg reclaim 观测；
- debugfs 快照；
- folio 受限采样；
- 用户态 snapshot store；
- Shadow alignment checker。

### 1.2 L0.2 目标链路

L0.2 的完整数据流固定为：

```text
Linux native reclaim
  ├── request/priority context
  └── current classic lruvec
          ↓
kernel lruvec aggregate snapshot
          ↓
tracepoint / debugfs
          ↓
lruvec_trace_parser
          ↓
kernel_snapshot_store
          ↓
STRICT_COMPARE / BOOTSTRAP_AGGREGATE
          ↓
diagnostic output
```

L0.2 的任务是：

> 观测 Linux 当前正在处理的 classic `lruvec`，将其聚合状态可靠地送入用户态，
> 并与 Shadow physical LRU 做只读诊断比较。

### 1.3 硬边界

L0.2 必须满足：

1. 不改变 Linux 原生回收决策、扫描比例、优先级、写回、换出或 demotion。
2. 不修改任何 Linux 原生 LRU 链、folio flags 或 vmstat。
3. 不调用或替代 `shrink_folio_list()`、`isolate_lru_folios()` 等执行路径。
4. 不修改 Shadow physical 页面链。
5. 不创建 Shadow page/domain/lruvec 以“补齐”内核状态。
6. 不执行 Shadow candidate。
7. 不实现页面级 `PAGE_ADD/MOVE/ACTIVATE/DEACTIVATE/ISOLATE/PUTBACK/RECLAIMED`。
8. 不实现 demote/reclaim/protect/prewash 请求接口。
9. 不支持 MGLRU，也不做 generation 到四条 classic LRU 的近似映射。
10. 任何 observer、trace、debugfs 或用户态错误都不能阻塞或改变 native reclaim。

---

## 2. 分支与历史边界

### 2.1 开发分支

L0.2 从以下基线创建：

```text
main@a89e7f692f51526ef22a51ad246e4cb007a4b9d7
```

目标：

```text
branch:   feat/linux-l02-lruvec-observer
worktree: /home/lzx/Desktop/huawei/myself-kswapd-l02
```

### 2.2 L0.1 导入原则

L0.1 历史不直接 merge。实施阶段只能：

- 逐文件审查；
- 选择性导入 observe-only 基础；
- 保留 request、priority、trace、parser 的必要契约；
- 重新验证导入后的 Shadow `25/25`；
- 不把 `Linux6.17/` 整树纳入 Git；
- 不修改原 L0.1 worktree。

### 2.3 L0.2 完成后的集成边界

L0.2 分支完成前：

- 不 merge main；
- 不 push；
- 不删除任何既有 worktree；
- 不清理 feature/integration/backup 分支；
- 必须完成独立只读审查。

---

## 3. Shadow physical 与 policy 的语义分离

### 3.1 Physical 层

Shadow 中以下五条链只表示**内核真实页面状态的镜像**：

```text
inactive_anon
active_anon
inactive_file
active_file
isolated
```

只有真实内核生命周期事件才有权改变 physical 链。

L0.2 聚合快照本身没有页面身份，因此：

- 不能通过聚合数量移动 Shadow 页面；
- 不能通过数量差值执行“自动修复”；
- 不能从内核快照创建 Shadow 页面；
- 不能把内核快照当作 L0.3 页面事件。

### 3.2 Policy 层

未来策略层可以独立维护：

```text
reclaim_score
protect_score
suggested_action
confidence
valid_until_ns
policy_seq
```

建议动作可包括：

```text
NONE
PROTECT
DEMOTE
RECLAIM
PREWASH
```

关键不变量：

```text
policy DEMOTE_HINT
    ≠
Shadow physical ACTIVE -> INACTIVE
```

正确的未来路径是：

```text
policy 产生建议
  -> 内核执行适配器提交请求
  -> 内核重新验证
  -> 内核接受或拒绝
  -> 内核真实生命周期事件
  -> Shadow physical 链同步
```

### 3.3 L0.2 对齐范围

L0.2 alignment：

- 只读取 physical aggregate；
- 不读取 policy hint 数量；
- 不根据 policy 调整 expected kernel count；
- policy 中存在 20 个 DEMOTE_HINT 时，只要 physical 链与内核一致，仍返回
  `MATCH`。

---

## 4. Classic-LRU 模式与身份键

### 4.1 模式枚举

统一定义两种后端：

```c
enum myks_lru_mode {
    MYKS_LRU_MODE_MEMCG = 0,
    MYKS_LRU_MODE_GLOBAL,
};
```

### 4.2 正式身份键

正式键必须包含模式：

```c
struct myks_lruvec_key {
    enum myks_lru_mode mode;
    u64 memcg_id;
    int nid;
};
```

因此对齐键是：

```text
(mode, memcg_id, nid)
```

而不是单独的 `(memcg_id,nid)`。

这样避免：

- GLOBAL 与 MEMCG 身份空间碰撞；
- 为 root 人为选择“永不冲突”的特殊 cgroup ID；
- 将 root memcg lruvec 错误解释为全局 LRU。

### 4.3 MEMCG_LRUVEC 模式

Linux 6.17 主验证模式：

```text
mode          = MYKS_LRU_MODE_MEMCG
memcg_id      = cgroup_id(memcg->css.cgroup)
memcg_css_id  = memcg->css.id
nid           = pgdat->node_id
lruvec        = mem_cgroup_lruvec(memcg, pgdat)
```

`memcg_id` 是正式键的一部分。

`memcg_css_id` 不作为主键，但作为对象代际和调试保护字段：

```text
同一 (mode, memcg_id, nid)
但 css_id 发生变化
    -> MEMCG_INCARCATION_CHANGED
    -> 旧 store entry 失效
```

实施时必须依据本地 Linux 6.17 源码和运行证据确认具体复用语义，但不再改变上述接口。

### 4.4 GLOBAL_LRU 模式

GLOBAL 后端的正式键固定为：

```text
mode          = MYKS_LRU_MODE_GLOBAL
memcg_id      = 0
memcg_css_id  = 0
nid           = pgdat->node_id
```

#### Linux `CONFIG_MEMCG=n`

此时：

```text
pgdat->__lruvec
```

代表真实 node global classic LRU，GLOBAL 后端可用。

#### Linux `CONFIG_MEMCG=y`

本轮禁止启用 GLOBAL 后端。

原因：

> root memcg lruvec 不代表所有子 memcg 页面，不能冒充整个系统的全局 LRU。

因此 Linux 6.17 `CONFIG_MEMCG=y` 的实际验证模式只能是：

```text
MYKS_LRU_MODE_MEMCG
```

#### OpenHarmony

后续 OpenHarmony 全局 LRU 适配可以复用同一 GLOBAL 数据契约，但使用平台专用
resolver，不要求复用 Linux `mem_cgroup_lruvec(NULL, pgdat)`。

---

## 5. `CONFIG_MEMCG` 后端边界

实现必须通过 wrapper/stub 隔离 MEMCG-only 依赖。

概念接口：

```c
int myks_resolve_lruvec(
    enum myks_lru_mode mode,
    struct mem_cgroup *memcg,
    pg_data_t *pgdat,
    struct myks_lruvec_identity *identity,
    struct lruvec **lruvec);
```

### 5.1 `CONFIG_MEMCG=y`

允许：

```text
MEMCG_LRUVEC  supported
GLOBAL_LRU    rejected on Linux 6.17
```

### 5.2 `CONFIG_MEMCG=n`

允许：

```text
GLOBAL_LRU    supported
MEMCG_LRUVEC  returns UNSUPPORTED_CONFIG
```

### 5.3 编译要求

MEMCG-only 符号不得泄漏到 GLOBAL-only 构建路径。

实施验收必须覆盖：

```text
CONFIG_MEMCG=y
CONFIG_MEMCG=n
```

并确认：

- 公共头文件可编译；
- disabled inline/stub 可用；
- GLOBAL 后端不引用 MEMCG-only 字段；
- MEMCG 后端不会在 `CONFIG_MEMCG=n` 下形成 unresolved symbol。

---

## 6. MGLRU 拒绝机制

本轮只支持 classic LRU。

### 6.1 启用时检查

observer 配置从 inactive 转为 active 前执行：

```text
lru_gen_enabled() == true
    -> 拒绝配置生效
    -> state = REJECTED_MGLRU
    -> 不注册/启用 classic snapshot 输出
```

内核 observer 不自行关闭 MGLRU。

启动脚本可以显式关闭 MGLRU，但必须：

- 记录关闭前状态；
- 检查关闭是否成功；
- 失败时不启动 classic observer。

### 6.2 运行时轻量 guard

仅启用时检查一次不够。每次准备发出 classic 快照前执行轻量检查：

```c
if (unlikely(lru_gen_enabled())) {
    /* record reject and skip classic snapshot */
}
```

运行中发现 MGLRU 被重新开启时：

```text
停止发出 classic 快照
state = REJECTED_MGLRU
runtime_reject_count++
记录 last_error
```

不能：

- 先发一条 classic 快照再拒绝；
- 输出四条全零数据；
- 把拒绝解释成 `MATCH`；
- 自动修改 MGLRU 开关。

---

## 7. Linux 6.17 classic LRU 字段来源

### 7.1 四条普通 LRU

快照字段：

| 字段 | Linux helper/index | 作用域 | 一致性 |
|---|---|---|---|
| `inactive_anon` | `lruvec_page_state(lruvec, NR_INACTIVE_ANON)` | MEMCG_NODE 或 NODE | 近似 |
| `active_anon` | `lruvec_page_state(lruvec, NR_ACTIVE_ANON)` | MEMCG_NODE 或 NODE | 近似 |
| `inactive_file` | `lruvec_page_state(lruvec, NR_INACTIVE_FILE)` | MEMCG_NODE 或 NODE | 近似 |
| `active_file` | `lruvec_page_state(lruvec, NR_ACTIVE_FILE)` | MEMCG_NODE 或 NODE | 近似 |

聚合快照：

- 不遍历 LRU 链；
- 不长期持有 `lru_lock`；
- 不声称四个计数属于同一个强一致瞬间；
- 标记 `consistency=APPROXIMATE`。

### 7.2 isolated 字段

Linux 6.17 当前来源为：

```text
node_page_state(pgdat, NR_ISOLATED_ANON)
node_page_state(pgdat, NR_ISOLATED_FILE)
```

它们是 **NODE scope**，不是 per-memcg `lruvec` scope。

因此字段契约固定为：

```c
enum myks_field_scope {
    MYKS_SCOPE_INVALID = 0,
    MYKS_SCOPE_MEMCG_NODE,
    MYKS_SCOPE_NODE,
};
```

#### MEMCG_LRUVEC

```text
四条普通LRU scope = MEMCG_NODE
isolated scope     = NODE
```

alignment 规则：

- 比较四条普通 LRU；
- 展示 node isolated 作为上下文；
- isolated 不参与该 memcg 的 `MATCH/COUNT_DRIFT`；
- 状态标记为 `FIELD_NOT_COMPARABLE`；
- 禁止将 node isolated 复制给每个 memcg 后参与比较。

#### GLOBAL_LRU

```text
四条普通LRU scope = NODE
isolated scope     = NODE
```

在 GLOBAL 后端真实可用时，两类字段均可参与 node 级比较。

### 7.3 字段有效性

每条快照必须携带：

```text
field_valid_mask
field_scope[]
validation_flags
```

无效字段不能写成未标记的零。

---

## 8. Request、priority 与 scan 分层

### 8.1 三层标识

必须同时存在：

```text
request_id
priority_seq
scan_seq
```

层次：

```text
request_id
  ├── priority_seq
  │     ├── scan_seq -> lruvec A
  │     ├── scan_seq -> lruvec B
  │     └── scan_seq -> lruvec C
  └── priority_seq
        └── ...
```

`snapshot_seq` 仍是 observer 全局单调序列，用于传输顺序和丢失诊断，不替代层次标识。

### 8.2 request 边界

#### kswapd

一次 `balance_pgdat()` 回收请求对应一个 `request_id`，复用 L0.1 上下文。

#### direct reclaim

一次顶层：

```text
try_to_free_pages()
```

或经源码确认的等价顶层调用，对应一个 `request_id`。

一个 direct request 可以跨：

- 多个 node；
- 多个 zone；
- 多个 lruvec；
- 多个 priority。

因此 direct request 绝不能绑定到单一 `(mode,memcg_id,nid)`。

#### memcg reclaim

一次顶层：

```text
try_to_free_mem_cgroup_pages()
```

或经源码确认的等价显式 memcg reclaim 入口，对应一个 `request_id`。

### 8.3 priority 边界

`priority_seq` 是 request 内单调序号。

它与数值型 `priority` 分开：

```text
priority_seq = 第几轮
priority     = scan_control 当前优先级数值
```

### 8.4 scan 边界

每次真实处理一个当前 `lruvec` 时分配一个 `scan_seq`。

canonical 观测边界为：

```text
进入 shrink_lruvec(current_lruvec, sc)
    -> SCAN_BEFORE
执行原生逻辑
离开 shrink_lruvec
    -> SCAN_AFTER
```

实施时可以通过最小 wrapper 或已存在调用点实现，但语义必须保持：

```text
同一 (request_id, priority_seq, scan_seq)
只对应一个明确 lruvec
```

### 8.5 Observer context

推荐使用与 `scan_control` 一一对应的 sidecar/context：

```c
struct myks_reclaim_observer_ctx {
    u64 request_id;
    u64 priority_seq;
    u64 next_scan_seq;
    enum myks_reclaim_source source;
    bool active;
};
```

它可以：

- 作为 `scan_control` 的条件编译字段；
- 或通过严格生命周期的一一对应 sidecar 传递。

禁止：

- 每层嵌套重新推断并生成 request；
- 在同一 memcg reclaim 内部把 source 改为 DIRECT；
- 在 `shrink_lruvec()` 重新创建 request。

### 8.6 Source 判定优先级

来源固定为：

```c
enum myks_reclaim_source {
    MYKS_RECLAIM_KSWAPD = 0,
    MYKS_RECLAIM_DIRECT,
    MYKS_RECLAIM_MEMCG,
    MYKS_RECLAIM_UNKNOWN,
};
```

判定优先级：

```text
显式 observer context
    >
顶层入口初始化信息
    >
防御性运行时推断
```

已有有效 context 时，不得根据内部调用栈覆盖 source。

---

## 9. 事件模型：Request 事件与 lruvec 快照分离

### 9.1 Request 生命周期事件

沿用并扩展 L0.1 的独立事件类型：

```text
request_begin
priority_begin / priority_round
priority_end（可选独立或合并进round）
request_end
```

它们描述 request 级控制流，不强制携带 lruvec 身份。

`REQUEST_BEGIN` 时可能尚未知道具体 memcg/nid，因此不允许填入伪造键。

### 9.2 lruvec snapshot 事件

`myself_kswapd:lruvec_snapshot` 只用于：

```text
SCAN_BEFORE
SCAN_AFTER
HEARTBEAT
DEBUGFS
```

其中 SCAN 事件必须携带：

```text
request_id
priority_seq
scan_seq
lruvec_key
```

HEARTBEAT/DEBUGFS 没有 reclaim request 时：

```text
request_id  = 0
priority_seq = 0
scan_seq = 0
priority = INVALID
```

并通过 stage 和 field-validity 明确标记，而不是伪造 request。

---

## 10. 聚合快照数据契约

概念结构：

```c
struct myks_lruvec_snapshot {
    u64 snapshot_seq;
    u64 timestamp_ns;

    u64 request_id;
    u64 priority_seq;
    u64 scan_seq;

    struct myks_lruvec_key key;
    u32 memcg_css_id;

    enum myks_reclaim_source reclaim_source;
    enum myks_snapshot_stage stage;
    enum myks_snapshot_consistency consistency;

    int priority;

    unsigned long inactive_anon;
    unsigned long active_anon;
    unsigned long inactive_file;
    unsigned long active_file;

    unsigned long isolated_anon;
    unsigned long isolated_file;

    unsigned long scanned_total;
    unsigned long reclaimed_total;

    u64 field_valid_mask;
    u64 validation_flags;
};
```

### 10.1 Stage

```c
enum myks_snapshot_stage {
    MYKS_STAGE_SCAN_BEFORE = 0,
    MYKS_STAGE_SCAN_AFTER,
    MYKS_STAGE_HEARTBEAT,
    MYKS_STAGE_DEBUGFS,
};
```

Request begin/end 不放入该枚举，由独立 request event 负责。

### 10.2 计数语义

四条 LRU：

```text
采集瞬间的聚合状态
```

`scanned_total` / `reclaimed_total`：

```text
当前 reclaim request/scan_control 的累计统计
```

用户态可计算：

```text
scanned_delta
reclaimed_delta
```

但不能：

- 与 LRU 长度相加；
- 解释为页面链计数；
- 跨 request 计算差值。

### 10.3 `snapshot_seq`

`snapshot_seq`：

- 全局单调递增；
- 由原子序列分配；
- 即使 trace 未被用户读取也不复用；
- 溢出按明确 validation/error 状态处理，不静默回绕。

---

## 11. Tracepoint 契约

### 11.1 事件

保留：

```text
myself_kswapd:lruvec_snapshot
myself_kswapd:lruvec_sample
```

sample 默认关闭。

### 11.2 Trace 丢失的可观测边界

普通 trace event 发射路径不能保证向 producer 返回“此次事件是否因 ring buffer
容量不足而丢失”。

因此禁止维护虚假的精确计数：

```text
observer_counters.trace_dropped  // 禁止宣称精确
```

内核侧只维护：

```text
snapshot_generated
trace_emit_attempted
```

用户态和 capture 工具维护：

```text
tracefs per-CPU overrun/dropped evidence
snapshot_seq gap
parser input truncation evidence
```

### 11.3 Gap 状态

在线读取时：

```text
发现 snapshot_seq 间隙
    -> PROVISIONAL_GAP
```

原因可能包括：

- 多 CPU 事件尚未汇合；
- trace filter；
- ring buffer overrun；
- capture 截断；
- 用户态丢记录；
- parser 丢弃坏记录。

完成 capture、按时间/sequence 合并并读取 tracefs overrun 统计后，才可以固化：

```text
CONFIRMED_GAP
```

不能将所有 seq gap 自动归因于内核 ring buffer。

---

## 12. debugfs 接口

目录：

```text
/sys/kernel/debug/myself_kswapd/
├── observer_status
├── observer_config
├── snapshot
└── samples
```

### 12.1 `observer_status`

只读，展示：

- active/state；
- mode；
- MGLRU 状态；
- snapshot generated；
- trace emit attempted；
- config generation；
- sample generation；
- runtime reject count；
- collection errors；
- last error；
- output limit；
- heartbeat 状态。

读取 status 不触发采集。

### 12.2 `observer_config`

管理员读写。

至少支持：

```text
enabled
mode
filter_memcg_id
filter_nid
heartbeat_ms
sample_enabled
sample_limit_per_lru
max_snapshot_entries
max_output_bytes
```

配置更新采用：

```text
解析到临时对象
-> 完整校验
-> 原子替换配置
```

非法写入：

- 返回明确错误；
- 不改变旧配置；
- 不执行快照；
- 不持有 `lru_lock`。

### 12.3 `snapshot`

#### 单次触发语义

每次 `open(snapshot)` 触发**一次**受控采集：

1. 固化本次配置快照；
2. 按过滤条件解析目标；
3. 采集 aggregate；
4. 若 `sample_enabled=1`，同步触发一次 bounded sample；
5. 将文本结果缓存到该 open 实例；
6. 后续分片 `read()` 只读取缓存，不重新遍历。

这样避免：

```text
一次 cat 导致多次 read()
-> 多次重复遍历 LRU
```

### 12.4 `samples`

只返回最近一次成功 sample 的缓存结果。

它本身：

- 不触发新 sample；
- 不重新加 `lru_lock`；
- 无缓存时返回明确 `empty=1`；
- 必须带 sample generation、snapshot seq、limit、total、emitted、truncated。

### 12.5 Bounded 输出

debugfs 快照固定携带：

```text
nr_total
nr_emitted
truncated
max_snapshot_entries
max_output_bytes
```

达到任一上限时：

- 停止继续生成；
- 保留已生成结果；
- `truncated=1`；
- 不把截断当作完整系统快照。

具体常量在实施计划冻结。

---

## 13. Heartbeat

默认：

```text
heartbeat_ms = 0
```

开启条件：

- 仅调试；
- 最小周期 `>= 1000ms`；
- 必须配置明确 filter；
- 禁止无过滤周期性枚举全系统；
- 使用 delayed work；
- observer disable 时取消或使 pending work 失效。

heartbeat 不属于 reclaim request：

```text
request_id = 0
priority_seq = 0
scan_seq = 0
stage = HEARTBEAT
```

失败只记录 observer 统计，不反馈到 reclaim。

---

## 14. Bounded folio sample

### 14.1 目的

sample 只用于验证：

- lruvec 身份；
- PFN；
- nid；
- memcg；
- classic LRU 类型；
- flags 摘要。

不用于：

- 初始化 Shadow page；
- 生成 candidate；
- 页面生命周期同步；
- 聚合计数来源。

### 14.2 锁模型

仅 `sample_enabled=1` 时：

```text
准备固定容量缓冲区
-> 短暂持有 lruvec->lru_lock
-> 每条普通LRU最多复制N项
-> 解锁
-> 锁外格式化/trace/debugfs
```

锁内禁止：

- 动态扩容；
- 内存路径/文件路径解析；
- 用户态拷贝；
- 获取 page lock；
- 调用可能睡眠的 helper；
- 修改 folio；
- 修改 list；
- 采样 isolated/unevictable。

硬上限：

```text
sample_limit_per_lru <= 32
```

---

## 15. 用户态 Parser

`lruvec_trace_parser` 负责：

```text
trace record
-> event type
-> required fields
-> integer/enum/range validation
-> snapshot object
-> store
```

错误至少区分：

```text
MISSING_FIELD
INVALID_INTEGER
INVALID_ENUM
OVERFLOW
UNSUPPORTED_MODE
INVALID_KEY
INVALID_STAGE
INVALID_SCOPE
```

坏记录：

- 记录错误；
- 不进入 store；
- 不阻止后续记录；
- 不修改 Shadow。

Request events 与 lruvec snapshot events 分别解析，再通过标识关联。

---

## 16. Snapshot Store

### 16.1 主键

store 主键：

```text
(mode, memcg_id, nid)
```

并保留：

```text
memcg_css_id
last_snapshot_seq
last_request_id
last_priority_seq
last_scan_seq
last_stage
last_timestamp_ns
latest_snapshot
field_validity
error counters
```

### 16.2 Sequence 处理

```text
seq > last_seq  -> ACCEPT
seq == last_seq -> DUPLICATE
seq < last_seq  -> STALE
```

旧记录不能覆盖新记录。

### 16.3 Scan 配对

`SCAN_BEFORE/SCAN_AFTER` 必须按：

```text
(request_id, priority_seq, scan_seq)
```

配对。

不能仅根据：

```text
request_id + priority
```

推断。

### 16.4 Request 嵌套

不同 request 的事件允许交错，store 必须按 request 分开维护阶段状态。

### 16.5 Memcg incarnation

对于同一 `(mode,memcg_id,nid)`：

```text
css_id变化
-> 标记 MEMCG_INCARCATION_CHANGED
-> 旧记录失效
-> 不跨代计算delta
```

---

## 17. STRICT_COMPARE

输入：

```text
kernel_lruvec_snapshot
Shadow lruvec physical aggregate
```

输出至少包括：

```text
MATCH
COUNT_DRIFT
MISSING_SHADOW_LRUVEC
MISSING_KERNEL_LRUVEC
STALE_KERNEL_SNAPSHOT
MEMCG_INCARCATION_CHANGED
FIELD_NOT_COMPARABLE
UNSUPPORTED_PAGE_LEVEL_COMPARE
UNSUPPORTED_MGLRU
```

### 17.1 Delta

方向固定：

```text
delta = kernel_count - shadow_count
```

### 17.2 四条 LRU

当字段有效且 scope 匹配时逐项比较。

### 17.3 Isolated

MEMCG 模式：

```text
kernel isolated scope = NODE
Shadow isolated scope = MEMCG_NODE
```

因此：

- 不比较；
- 不影响普通四链的 MATCH；
- 单独输出 `FIELD_NOT_COMPARABLE`；
- 展示 node 值作为上下文。

GLOBAL 模式：

- node scope 可比较；
- 前提是 GLOBAL 后端真实可用。

### 17.4 严格只读

STRICT 不得：

- 创建 domain；
- 创建 lruvec；
- 创建 page；
- 修改链；
- 执行 candidate；
- 自动补零；
- 根据 drift 自愈。

---

## 18. BOOTSTRAP_AGGREGATE

BOOTSTRAP 只维护：

```text
kernel aggregate baseline
```

用途：

- 验证 trace/debugfs/parser/store 链路；
- 观察 kernel count 漂移；
- 在 L0.3 尚未接入时提供诊断基线。

禁止：

- 创建 Shadow page；
- 修改 Shadow physical 链；
- 参与 candidate；
- 被命名为页面级 Shadow；
- 伪造 STRICT MATCH。

STRICT 与 BOOTSTRAP 必须使用不同模式字段和输出状态。

---

## 19. 错误隔离

### 19.1 内核 observer

任何错误：

```text
resolve失败
MGLRU enabled
memcg dying
nid offline
字段不可用
sample buffer不足
debugfs输出截断
```

只允许：

- 增加 observer counter；
- 更新 last error；
- 可选发 error trace；
- 跳过本次观测。

不得：

- 修改 `scan_control` 的回收策略字段；
- 改变原生返回值；
- 中断 reclaim；
- 等待用户态；
- 重试到热路径超时。

### 19.2 用户态

parser/store/alignment 退出或崩溃，不影响内核。

### 19.3 Shadow

Shadow 缺失、validator 报错或 count drift 不反馈到 Linux。

---

## 20. 性能边界

正常 reclaim 热路径禁止：

- 遍历全部 memcg；
- 遍历全部 node；
- 遍历 folio 链；
- 动态大内存分配；
- 路径字符串解析；
- debugfs 文本生成；
- 睡眠等待；
- 获取不必要的页锁。

正常快照只处理：

```text
当前 shrink_lruvec 的 lruvec
```

性能统计至少包括：

```text
snapshot_generated
snapshot_skipped_disabled
snapshot_skipped_mglru
snapshot_resolve_failed
snapshot_collect_failed
trace_emit_attempted
sample_requested
sample_completed
sample_truncated
runtime_reject_count
collect_elapsed_total_ns
collect_elapsed_max_ns
```

不提供无法准确获得的“精确 trace dropped”计数。

---

## 21. 测试与验收

### 21.1 设计级不变量

必须验证：

1. observer 关闭不改变 native reclaim。
2. MEMCG/GLOBAL 身份空间不会碰撞。
3. `CONFIG_MEMCG=y` 下 Linux 不启用伪 global 模式。
4. isolated scope 不会被错误解释为 per-memcg。
5. request/priority/scan 三层不会混用。
6. memcg reclaim 内部调用不会重新生成 DIRECT request。
7. MGLRU enable 和运行中重新开启均能拒绝 classic 快照。
8. trace gap 不会被无证据归因于 ring buffer。
9. debugfs 一次 open 只触发一次采集。
10. samples 读取不触发新遍历。
11. STRICT 不创建或修改 Shadow。
12. policy hint 不改变 physical alignment。

### 21.2 内核构建矩阵

至少：

```text
CONFIG_MEMCG=y
CONFIG_MEMCG=n
CONFIG_DEBUG_FS=y
CONFIG_TRACING=y
CONFIG_TRACEPOINTS=y
CONFIG_LRU_GEN=n
CONFIG_LRU_GEN=y
```

要求：

- 两种 MEMCG 配置均可编译；
- LRU_GEN=y 可编译；
- MGLRU enabled 时运行拒绝；
- GLOBAL 后端不泄漏 MEMCG-only 符号。

### 21.3 KUnit/内核对象测试

覆盖：

- mode resolver；
- key 构造；
- css incarnation；
- field scope；
- validation mask；
- request context；
- scan seq；
- MGLRU guard；
- config 原子替换；
- output bound；
- heartbeat filter；
- sample limit；
- error isolation。

### 21.4 Trace 测试

覆盖：

- request 生命周期；
- scan before/after 配对；
- 多 lruvec 同 priority；
- 多 request 交错；
- snapshot seq；
- provisional/confirmed gap；
- tracefs overrun 证据；
- filter 行为。

### 21.5 debugfs 测试

覆盖：

- status 不触发采集；
- config 合法/非法；
- 单目标；
- memcg filter；
- nid filter；
- bounded 全量；
- max entries；
- max bytes；
- truncation；
- snapshot open 一次采集；
- read 分片不重复；
- samples cache；
- empty sample；
- heartbeat 无过滤拒绝。

### 21.6 Parser/store 测试

覆盖：

- 正常记录；
- 缺字段；
- 溢出；
- 非法枚举；
- 非法 key/scope；
- duplicate；
- stale；
- provisional gap；
- confirmed gap；
- stage order；
- scan pairing；
- request 交错；
- css incarnation change。

### 21.7 Alignment 测试

覆盖：

- MATCH；
- COUNT_DRIFT；
- missing kernel；
- missing Shadow；
- stale；
- incarnation change；
- isolated not comparable；
- global isolated comparable；
- delta 方向；
- 不创建对象；
- 不修改链；
- policy hint 不影响 physical。

### 21.8 Runtime Smoke

可启动新 Linux 6.17 内核时：

1. 关闭 MGLRU；
2. 启用 observer；
3. 触发 kswapd；
4. 触发 direct reclaim；
5. 触发 memcg reclaim；
6. 读取 trace；
7. 读取 debugfs；
8. 运行 parser/store/alignment；
9. 运行中重新开启 MGLRU，验证即时拒绝；
10. 关闭 observer；
11. 检查无崩溃、锁死和明显延迟退化。

环境不具备时必须写：

```text
NOT RUN / ENVIRONMENT BLOCKED
```

不能以编译、KUnit 或 parser 测试替代。

---

## 22. 实施证据要求

以下项目不再是接口设计问题，但实施完成前必须取得证据：

| 编号 | 证据项 | 关闭方式 |
|---|---|---|
| E1 | `cgroup_id` 与 `css.id` 的目标内核复用和权限语义 | 本地源码核对 + 受控创建/删除 memcg 测试 |
| E2 | direct reclaim 顶层与 `shrink_lruvec()` 真实调用关系 | ftrace/函数图或受控 trace |
| E3 | memcg reclaim 嵌套调用 source 传播 | 受控 memcg reclaim trace |
| E4 | `CONFIG_MEMCG=y/n` 编译矩阵 | 两套内核对象构建 |
| E5 | tracefs overrun 与 seq gap | 受控小 buffer 压力测试 |
| E6 | debugfs max entries/max bytes/truncation | KUnit + runtime |
| E7 | MGLRU enable/runtime re-enable 双重拒绝 | 新内核运行测试 |
| E8 | observer 热路径开销 | 采集耗时统计与关闭/开启对照 |
| E9 | runtime smoke | 启动新内核后执行 |

这些项目允许在实施计划中拆分，但任何未完成项必须如实标记，不能写成通过。

---

## 23. 实施阶段建议

后续实施计划按以下顺序展开：

1. 选择性导入 L0.1 observe-only 前置；
2. 定义公共 key、scope、snapshot、request context；
3. 完成 `CONFIG_MEMCG` 双后端 resolver；
4. 完成 MGLRU 双重 guard；
5. 接入 kswapd request 与 lruvec scan；
6. 接入 direct reclaim；
7. 接入 memcg reclaim；
8. 实现 tracepoint；
9. 实现 debugfs status/config/snapshot；
10. 实现 bounded sample 与 sample cache；
11. 实现 heartbeat；
12. 实现 parser；
13. 实现 store；
14. 实现 BOOTSTRAP_AGGREGATE；
15. 实现 STRICT_COMPARE；
16. 实现 CLI/capture；
17. 完成 build/KUnit/runtime 验证；
18. 独立只读审查；
19. 不 push、不 merge main，等待人工决定。

每一步必须：

- TDD；
- 小提交；
- 目标测试先失败；
- 实现后目标测试通过；
- 阶段回归；
- `git diff --check`。

---

## 24. L0.3 与后续执行阶段边界

L0.3 才负责：

```text
PAGE_ADD
PAGE_ACTIVATE
PAGE_DEACTIVATE
PAGE_MOVE
PAGE_ISOLATE
PAGE_PUTBACK
PAGE_RECLAIMED
```

更后续的执行阶段才负责：

```text
DEMOTE request
RECLAIM request
PROTECT request
PREWASH request
内核重新验证
真实执行结果
策略反馈
```

L0.2 只能为这些阶段保留：

```text
request_id
priority_seq
scan_seq
snapshot_seq
lruvec key
source
stage
field scope
```

不能提前实现执行闭环。

---

# 附录 A：Shadow 现有接口映射

| 设计概念 | 当前真实边界 | L0.2 使用方式 |
|---|---|---|
| Engine | `struct reclaim_engine` | 只作为 alignment 查询宿主 |
| Domain | `struct shadow_domain` | 只通过公开键查询，不直接暴露 |
| lruvec | `struct shadow_lruvec` | 通过 `shadow_lruvec_get_stats()` 获取 physical aggregate |
| Physical 链 | 四条 lists + isolated | 只读比较 |
| Candidate | collect/revalidate | L0.2 不调用 |
| Validator | quiescent-only | 不自动触发，不用于热路径 |
| Policy | v1 policy 类型 | 不作为 L0.2 physical 状态 |

---

# 附录 B：L0.1 候选前置

| 原 SHA | 内容 | L0.2 处理 |
|---|---|---|
| `4557c010a451ca161a2b431b2f93d7294d7ac359` | L0.1 adapter、trace、parser 基础 | 不整提交导入；选择必要 observe-only 文件和契约 |
| `dfe5107e7207fb9f68b87a50f1cd770e600df288` | Linux patch 刷新 | 只作为受控 patch 参考 |
| `362611828bac62c4a820498ccc718c2b87861fef` | parser validation/fixture | 复用测试风格，不直接导入实现 |
| `f427ffca0e21e9a88513e396ca200890bbcbaf84` | per-CPU capture 统计 | 不是内核前置，按 capture 需求评估 |
| `bd1bb6c4d435eb0a29c23181e82ba960814ad0a5` | begin snapshot 类型修正 | 不单独导入，随必要 patch 重验 |

---

# 附录 C：Linux 6.17 接口映射

| 观测项 | 结构/helper | 作用域/锁 | 设计结论 |
|---|---|---|---|
| lruvec | `struct lruvec` | list 受 `lru_lock` | 聚合不遍历链 |
| node | `pglist_data::node_id` | node | 正式 nid |
| memcg | `mem_cgroup::css` | 生命周期受 CSS/memcg 规则约束 | ID + incarnation |
| lru mapping | `enum lru_list`、`folio_lru_list()` | sample 时短持锁 | 仅 debug sample |
| lruvec counts | `lruvec_page_state()` | 近似 vmstat | 四条普通 LRU 来源 |
| global counts | `node_page_state()` | node 近似统计 | isolated 来源 |
| mapping | `mem_cgroup_lruvec()` | 配置相关 | MEMCG resolver |
| MGLRU | `lru_gen_enabled()` | static key 轻量读取 | enable/runtime 双重 guard |
| classic scan | `shrink_lruvec()` | 一个明确 lruvec | canonical scan_seq |
| request context | `scan_control` + observer ctx | request 生命周期 | source/request/priority/scan 传播 |
| isolation lock | `lruvec->lru_lock` | 短临界区 | 仅 bounded sample 使用 |

---

# 附录 D：设计关闭清单

以下设计问题已经关闭：

- [x] isolated 在 MEMCG 模式下为 NODE scope，不参与 per-memcg 对齐；
- [x] direct reclaim 顶层定义 request，`shrink_lruvec()` 定义 scan；
- [x] memcg reclaim 通过显式 observer context 传播 source；
- [x] key 使用 `(mode,memcg_id,nid)`；
- [x] css ID 用作 incarnation guard；
- [x] `CONFIG_MEMCG=y/n` 使用双后端 wrapper；
- [x] Linux `CONFIG_MEMCG=y` 禁止伪 GLOBAL_LRU；
- [x] trace producer 不宣称精确 dropped；
- [x] gap 分 provisional/confirmed；
- [x] debugfs snapshot open 一次触发一次采集；
- [x] samples 只读缓存；
- [x] MGLRU 使用启用时与运行时双重 guard；
- [x] request event 与 lruvec snapshot event 分离；
- [x] 增加 `priority_seq` 与 `scan_seq`；
- [x] physical 与 policy 严格分离。

因此，本规范不再包含会改变接口的 `OPEN QUESTION`，可进入详细实施计划阶段。
