# Shadow LRU 合并前审查修复计划

## 审查意见复核记录

| 审查项 | 结论 | 代码证据 | 处理决定 |
| --- | --- | --- | --- |
| Important 1：scan/validator 与事件元数据数据竞争 | VERIFIED | `shadow_lru.c` 中事件在仅持有 `page.lock` 时更新 metadata，而扫描在仅持有 `lruvec.lock` 时读取 | 以 lruvec 锁保护所有 scan 可见字段；validator 改为 quiescent-only。 |
| Important 2：sequence gate 前创建目标对象 | VERIFIED | 已有页 ISOLATE/PUTBACK/MOVE 在 gate 前调用 `shadow_domain_get_or_create()` | 对已有页先在 `page.lock` 下 gate；仅 APPLY 再创建目标。 |
| Important 3：无 candidate identity/revalidation | VERIFIED | 现有 scan 只返回聚合计数 | 新增稳定 candidate 快照、容量/截断结果和重验证接口。 |
| Important 4：validator 覆盖不足 | VERIFIED | 未双向检查 page table、链位置和 node bucket；公开 chain flag 未写入 | 明确 quiescent-only 契约，建立 table/chain 双向集合检查，真实写入 chain flag。 |
| Minor 1：重复 RECLAIMED 归类 UNKNOWN | VERIFIED | 页面删除后无序列记录 | 保持无 tombstone 的状态幂等语义，增加测试和文档说明。 |
| Minor 2：计划与独立 Shadow 实现不一致 | VERIFIED | parser/runner 保持 legacy API，最终文档已说明独立子系统 | 更新原计划和最终文档，明确 parser/runner 适配为后续任务。 |

## 字段与锁所有权

| 字段类别 | 保护锁 | 读者 |
| --- | --- | --- |
| 同一页面事件串行化、`last_event_seq`、`dying` | `page.lock`（查表引用由 `page_table_lock`） | 生命周期事件、candidate revalidate |
| 页面位置、分类和 scan 可见 metadata：`domain`、`memcg_id`、`nid`、`container`、`state`、`current_lru`、`page_type`、`order`、`isolated_from`、`putback_hint`、`provisional` | 所在 lruvec 的 `lock`；跨容器移动时同时持有源/目标 lruvec 锁 | scan、candidate collect、quiescent validator |
| DETACHED 页面的位置字段 | `page.lock` | 不允许 scan/candidate collect 观察 |

Validator 选择 **quiescent-only** 契约：调用者必须确保没有并发 Shadow 生命周期事件、scan、candidate collect/revalidate、domain destroy 或 engine destroy。该选择避免在持有 lruvec 锁时获取 `page.lock`，且不引入额外全局串行化。

## 实施顺序与测试

1. 先新增 stale/duplicate ISOLATE、PUTBACK、MOVE 的不存在目标测试；修改 gate 后再运行测试并提交。
2. 先新增同步屏障并发测试；将 scan 可见字段更新移入 lruvec 临界区，记录字段所有权并提交。
3. 先新增 candidate collect/revalidate 失败测试；实现稳定值快照、明确失效原因、容量截断并提交。
4. 先新增 quiescent validator 故障注入测试；补齐双向不变量和 validation flag 并提交。
5. 增加 duplicate RECLAIMED 状态幂等、错误路径、invalid nid、并发压力与超时测试；校正文档并提交。
6. 运行默认、ASan/UBSan、TSan 尝试、L0.1 回归；随后以只读方式复审 `0e8a355..HEAD`。

## 锁图复核目标

```text
page_table_lock -> page.lock -> lruvec.lock
domain_table_lock -> node_table_lock
node_table_lock -> lruvec.lock
lruvec(A) -> lruvec(B)  (按 memcg_id,nid 全序)
```

`domain_table_lock` 和 `page_table_lock` 不同时持有；任何最终 `domain_put()` 和 `page_put()` 都必须在 page/node/lruvec/table 锁外发生。

## 范围边界

本计划不修改 Linux 6.17 L0.1 事件语义，不接入 L0.2/L0.3，也不把 legacy parser/event runner 自动映射到 Shadow nid 0。parser/runner 适配是后续独立任务。
