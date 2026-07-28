# Shadow LRU 第二次复审剩余 Important 关闭计划

## 范围与基线

- 工作区：`/home/lzx/Desktop/huawei/myself-kswapd-shadow-lru`
- 分支：`feat/shadow-lru-memcg-nid`
- 基线：`a6da62e`
- 本轮只处理第二次复审剩余的三个 Important：确定性交错并发测试、candidate 完整矩阵、validator 双向集合与故障注入。
- 不修改 Linux L0.1 适配层，不开始 L0.2/L0.3，不处理预测策略，不重构已关闭的 sequence gate 或元数据同步路径。

## Important 1：确定性交错并发与有界超时

### 验收标准

覆盖 scan+MOVE、scan+ISOLATE、scan+PUTBACK、scan+domain destroy、MOVE+RECLAIMED、PUTBACK+RECLAIMED，以及双向 MOVE；每个场景使用显式起始屏障和阶段控制，验证关键前后顺序，不依赖随机调度。每个场景至少 100 轮，全套并发场景再重复 100 轮。每轮所有线程均正常退出并 join，场景结束在静止点运行 validator，检查引用计数、链表、状态与统计。CTest 为并发测试设置有限 TIMEOUT，死锁必须被测试框架判失败而非无限等待。

### RED 测试与预期失败原因

先新增测试专用阶段控制器和上述场景的失败断言，先运行并记录 RED：现有测试没有屏障控制、没有这些交错证据或测试级超时，至少一个目标断言应因覆盖/保护缺失失败；不修改生产调度接口来制造 RED。

### 最小实现与验证

- 测试侧优先使用 `pthread_barrier_t` 与 `pthread_mutex_t`/`pthread_cond_t`，不向生产公开头文件增加调度 hook。
- 必要时仅在测试编译单元使用内部结构锁住 lruvec 以控制 API 进入顺序；生产锁图保持不变。
- 为并发 CTest 目标设置 `TIMEOUT`，避免不可移植的无界 timed join；健康路径仍显式 join 全部线程。
- 运行精确并发测试，随后运行完整 CTest 和 100 轮压力测试。

## Important 2：candidate 收集与重验证完整矩阵

### 验收标准

保持现有 `shadow_candidate` 字段和 API 兼容，不暴露 `shadow_page *`。覆盖精确 `(memcg_id,nid)`、同 memcg 不同 nid、不同 memcg 同 nid、Node 0/1 隔离；四条普通 LRU、isolated/detached/dying 排除；capacity 为 0、少于、等于、大于可选数量；明确表达总符合数、实际输出数和截断状态。独立测试 VALID、PAGE_MISSING、PAGE_DYING 的可达性说明、LOCATION_CHANGED 三种移动方向、STATE_CHANGED、LRU_CHANGED、EVENT_SEQ_CHANGED，以及多变化时原因优先级。

### RED 测试与预期失败原因

先扩展测试矩阵并对总符合数/输出数/截断字段及每个失效原因分别断言。预期现有 result 结构缺少总符合数或截断表达，且现有收集/重验证覆盖不足，测试先 RED；PAGE_DYING 若当前公开查找不可达，测试与文档应明确这是防御性枚举，不伪造公共可达性。

### 最小实现与验证

- 只对 result 增加表达统计所必需的字段，保留现有字段语义和名称。
- 收集过程中先统计 eligible，再按 capacity 写入，保证不越界且 `nr_total_eligible`、`nr_candidates`/emitted、truncated 一致。
- 使用真实事件构造 LOCATION_CHANGED、STATE_CHANGED、LRU_CHANGED、EVENT_SEQ_CHANGED；不添加跨 node candidate API。
- 运行 candidate 精确测试并检查 Node 隔离和优先级。

## Important 3：validator 双向集合、复杂度与故障注入

### 验收标准

validator 继续是 quiescent-only，文档明确调用者须停止生命周期事件、scan、candidate 收集和销毁并 join 工作线程。静止点建立独立 page-table 集合 A 与五条链集合 B，完成 A→B、B→A、page_id/page/list_node 唯一性、domain/memcg、container/nid、node bucket/key、链长度/统计、状态/LRU/isolated 约束检查；正常状态通过，所有主要损坏类别失败并设置对应 flags，真实链/状态不一致设置 `SHADOW_VALIDATION_CHAIN_STATE_MISMATCH`。实现使用 O(P+L) 级临时哈希集合；临时分配失败必须返回明确失败，不得报告一致，也不得修改 Shadow 状态。

### RED 测试与预期失败原因

先加入测试专用内部故障注入 helper 和合法状态基线测试，再逐项注入 table-only、chain-only、重复对象/page_id/list_node、错误 LRU/状态、domain/memcg、container/nid、错误 node bucket/key、四类计数、dying、invalid current_lru、orphan/duplicate 等损坏。预期当前 validator 对 table/chain 反向缺失、重复链、部分字段损坏不能完整命中，先 RED。

### 最小实现与验证

- 在 validator 内建立只读临时集合；不引入在线全局热路径锁，不修改业务状态。
- 测试 helper 仅编译到测试目标并放在 `tests/integration`；生产公开头文件不暴露任意破坏接口。
- 对无法安全构造 libc 链表破坏的情形，使用 validator 可接受的内部抽象注入，避免未定义行为。
- 运行 validator 精确测试、故障注入矩阵和 ENOMEM 路径（若现有分配注入基础设施允许）；否则在报告中保留真实阻塞证据。

## 分阶段提交与命令

1. `docs: add final shadow review closure plan`
2. `test: add deterministic shadow interleaving coverage`
3. `test: complete shadow candidate matrix`
4. `fix: complete bidirectional shadow validation`
5. `test: add shadow validator fault injection matrix`
6. `docs: document final shadow guarantees`

每次提交前执行 `git diff --check` 与对应目标测试。最终执行：

```sh
cmake -S 用户态模拟器/v1 -B /tmp/shadow-lru-final-default -DRECLAIM_ENABLE_TESTS=ON
cmake --build /tmp/shadow-lru-final-default -j"$(nproc)"
ctest --test-dir /tmp/shadow-lru-final-default --output-on-failure
```

并补充 100 轮关键测试、ASan/UBSan（含 leak detection）、TSan 重试、可用时 Helgrind、L0.1 回归、`git diff --check a6da62e..HEAD` 与工作区检查。TSan 若仍因环境 `unexpected memory mapping` 无法启动，记录为 `NOT RUN / ENVIRONMENT BLOCKED`，不改代码绕过。

## 最终独立只读复审

实现和验证提交完成后，仅审查 `a6da62e..FINAL_HEAD`：确认三个 Important 的测试真实、candidate 语义完整、validator 双向集合与故障注入完整，并回归检查 sequence gate 仍先于 target 创建、元数据锁保护未退化、Node 隔离未退化、L0.1 未修改。报告写入 `/home/lzx/Desktop/huawei/shadow-lru-memcg-nid-final-review.md`。本轮不 push、不合并。
