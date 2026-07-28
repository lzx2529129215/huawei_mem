# Shadow LRU：memcg 与 NUMA node 维度

## 目标

本模块为用户态模拟器增加独立的 Shadow LRU。页面稳定身份仍是 `page_id`；
`memcg_id` 表示策略域，`nid` 表示 NUMA node，二者共同唯一定位一个
`shadow_lruvec`。因此一个 memcg 可以只在实际使用的 node 上创建 LRU 容器，
而 page hash table 不会因 nid 复制页面记录。

对象关系如下：

```
reclaim_engine
  ├── shadow_pages: page_id -> shadow_page
  └── shadow_domains: memcg_id -> shadow_domain
                                  └── node_table: nid -> shadow_lruvec
```

原有的 v1 回收模拟器数据结构和接口继续保留。Shadow LRU 是并列的观测与状态机
子系统，不会改变既有 trace 的解析、执行或回收语义。

## 状态机

每个 Shadow 页面只能处于以下一种状态：

| 状态 | 链位置 | 有效字段 |
| --- | --- | --- |
| `SHADOW_PAGE_ON_LRU` | 四条普通 LRU 中的一条 | `current_lru` |
| `SHADOW_PAGE_ISOLATED` | 当前 lruvec 的 `isolated` 链 | `isolated_from`、`putback_hint` |
| `SHADOW_PAGE_DETACHED` | 无 | `container == NULL` |

`SHADOW_LRU_ORIGIN_UNKNOWN` 只描述未知的历史来源，绝不作为 `lists[]` 下标。
普通链长期只包含 inactive/active anon、inactive/active file 和 isolated；模块不保留
putback 或 reclaimed 的长期链。

未知的 `ISOLATE`、`PUTBACK`、`MOVE` 会创建 provisional 页面，供迟到的 `ADD`
补全静态元数据；未知 `RECLAIMED` 只记录校验标志，不创建页面。`event_seq` 更大
的事件更新生命周期状态，相同序号幂等，小于当前序号的事件不回退位置或状态。

## 公开接口

`include/myself_kswapd/shadow_lru.h` 定义生命周期事件和以下接口：

- `shadow_page_add/isolate/putback/reclaimed/move`
- `shadow_scan_lruvec(engine, memcg_id, nid, ...)`
- `shadow_scan_node(engine, nid, ...)`
- `shadow_lruvec_get_stats`、`shadow_page_get_info`、`shadow_engine_validate`
- `shadow_collect_lruvec_candidates`、`shadow_candidate_revalidate`

所有扫描接口都要求具体的 `nid`。不存在的 node 不会创建空 lruvec，也不会自动扫描
其他 node；旧的 memcg-only 回收接口不会隐式调用 Shadow 扫描。

### 候选快照

候选快照只复制 `page_id`、`memcg_id`、`nid`、期望状态、期望 LRU 和事件序号，
不会暴露内部 `shadow_page *`。收集只遍历指定 `(memcg_id, nid)` 的四条普通 LRU，
isolated、detached 和 dying 页面不会进入候选。

`shadow_candidate_result` 中：

- `nr_total_eligible` 是满足位置、状态和 LRU 条件的总页面数；
- `nr_candidates` 是实际写入调用者缓冲区的数量；
- `nr_truncated` 与 `truncated` 表示受 capacity、max_candidates 或 max_pages 限制而未写入的页面。

重验证按位置、状态、LRU、事件序号的顺序返回第一个失效原因。页面已删除返回
`PAGE_MISSING`；仍在表但标记 dying 返回防御性状态 `PAGE_DYING`。公开查找不会把
dying 页面交给普通事件，因此该状态主要用于静止点诊断。位置变化覆盖 memcg、node
及二者同时变化；同位置状态、LRU 或序列变化分别返回对应原因。

## 并发与生命周期

domain 和 page 分别使用 refcount；从全局表取到对象后先取得引用，再释放表锁。
删除时先从表移除并设置 `dying`，最后一个引用才销毁对象。普通事件使用 page lock
串行化；跨 lruvec MOVE 按 `(memcg_id, nid)` 全序获取一把或两把 lruvec lock，避免
反向迁移的 ABBA 死锁。扫描持有 lruvec lock 时不获取 page lock。

校验器在静止点建立独立的 page-table 集合和五条链集合，双向核对页面对象、page_id、
链节点、domain/memcg、container/nid、node bucket/key、状态、LRU 和计数。临时集合使用
开放寻址哈希，验证复杂度为 O(P+L)；集合分配失败会返回 `RECLAIM_ERR_NO_MEMORY`，
不会错误报告为一致。真实链与状态不一致时设置
`SHADOW_VALIDATION_CHAIN_STATE_MISMATCH`；校验标志还保留重复/过期事件、未知事件、
自愈和源位置不匹配的证据。

`shadow_engine_validate()` 是 quiescent-only 接口：调用时不得并发执行 Shadow
生命周期事件、扫描、候选收集或对象销毁。扫描可见的位置与分类字段由所属 lruvec 锁
保护；`page.lock` 只串行化同一页面事件和序列门控。

测试编译单元使用同步屏障控制关键锁交错，并在每个场景结束后调用校验器；完整并发
场景重复 100 轮，CTest 对测试进程设置 30 秒上限。故障注入 helper 只存在于测试代码，
生产公开头文件不提供任意破坏链表的接口。

首次 `RECLAIMED` 会删除页面记录。没有无限 tombstone 表时，后续相同事件会被记录为
`RECLAIM_UNKNOWN_PAGE`；它仍是状态幂等的，不会再次摘链、计数或释放。

现有 legacy parser/event runner 继续调用原 `reclaim_engine_*` API，不会自动进入
Shadow 状态机，也不会隐式映射到 nid 0；Shadow trace 适配属于后续独立任务。

## 边界

本实现只覆盖用户态 Shadow 引擎。它不实现 Linux 6.17 的 L0.2/L0.3 适配，不修改
L0.1 Observe-Only trace 语义，也不引入预测策略或真实内核回收动作。
