# Shadow LRU：per-memcg-per-node、isolated 状态机与并发安全实施计划

## 基线与范围

- 源工作树：`/home/lzx/Desktop/huawei/myself-kswapd-l01`，起点为 `bd1bb6c`。
- 实施工作树：`/home/lzx/Desktop/huawei/myself-kswapd-shadow-lru`，分支 `feat/shadow-lru-memcg-nid`。
- 用户态目标：`用户态模拟器/v1`。Linux 6.17 L0.1 的 observe-only 代码、patch、tracepoint、KUnit 和解析器保持原样；本次不修改其语义。
- 当前用户态实现是单线程的 `page_id -> reclaim_page`、`cgroup_id -> reclaim_domain -> 四条 LRU`，没有 nid、isolated 常驻链、锁或引用计数。

## 实际改动文件

1. `用户态模拟器/v1/include/myself_kswapd/types.h`：增加 Shadow LRU、页面状态、来源、移动原因、validation flag 和显式 nid 类型。
2. `用户态模拟器/v1/include/myself_kswapd/engine.h`：增加显式 `(memcg_id,nid)` 生命周期、事件和扫描 API；保留旧 API 的受限兼容声明。
3. `用户态模拟器/v1/include/myself_kswapd/event.h`、`error.h`、`validator.h`：增加 Shadow 生命周期事件、错误与验证报告字段。
4. `用户态模拟器/v1/src/core/internal.h`：将 domain 改为稀疏 node table，定义 `shadow_lruvec`、页/domain 引用与锁字段。
5. `src/core/{engine,hash,domain,page,reclaim,validator,list,types}.c`：实现容器、迁移、isolated 状态机、显式 node scan、校验和兼容包装。
6. `src/simulator/{event_parser,event_runner}.c`：解析并派发带 seq、memcg 和 nid 的 Shadow 事件，旧 trace 命令明确固定到默认 nid 0。
7. `CMakeLists.txt`：链接 Threads，增加 Shadow 生命周期/并发测试。
8. `tests/{unit,integration,scenarios}`：先新增失败测试，再实现；保留既有测试。
9. `用户态模拟器/v1/docs/`：新增中文 Shadow LRU 架构和事件格式说明。

## 旧接口到新接口

| 旧接口 | 新接口/行为 | 兼容策略 |
|---|---|---|
| `reclaim_engine_add_page(page,cgroup,type,order)` | `shadow_page_add(page,memcg,nid,type,order,seq)` | 旧接口显式包装至 `nid=0`、自动 seq；不跨 node。 |
| `reclaim_engine_recharge_page` | `shadow_page_move` | 旧接口只支持 `nid=0`，新接口以目标 `(memcg,nid)` 为权威。 |
| `reclaim_engine_migrate_page(old,new)` | `shadow_page_move` | 保留旧 page-id 重命名语义；新增 move 不改 page_id。 |
| `reclaim_engine_reclaim_group(cgroup,...)` | `shadow_scan_lruvec(engine,memcg,nid,...)` | 旧接口为兼容固定 `nid=0`；新扫描不接受 NID_ANY。 |
| `reclaim_engine_reclaim_all` | `shadow_scan_node(engine,nid,...)` | 新接口仅扫描明确 nid；旧接口固定 `nid=0`。 |
| 原 trace PAGE 命令 | Shadow PAGE_ISOLATE/PUTBACK/RECLAIMED/MOVE 命令 | 旧命令不获得隐式跨 node 行为。 |

## 最终对象与生命周期

```
reclaim_engine
  page_table: page_id -> shadow_page
  domain_table: memcg_id -> reclaim_domain
    node_table: nid -> shadow_lruvec
      inactive_anon / active_anon / inactive_file / active_file / isolated
  event_seq
```

- `page_id` 永远是唯一 hash key；memcg_id 和 nid 仅决定页面当前容器。
- domain 插表取得 table owner 引用（`refcount=1`）。在 `domain_table_lock` 下确认 `!dying` 后才能 `domain_get`；移表后设 `dying=true`，释放表锁后 `domain_put`。最后一个 put 销毁全部稀疏 lruvec、node table、锁和内存。
- page 插表取得 table owner 引用（`refcount=1`）。普通事件在 `page_table_lock` 下获得临时引用，再以 `page.lock` 串行化。删除先移表并标记 dying，最终由 table owner 与事件临时引用分别 put；最后 put 时页面必须 detached、无容器、无链并释放持有的 domain 引用。
- 空 lruvec 不自动回收；仅在 domain 最终释放时销毁。扫描不创建缺失 nid。

## 锁顺序和引用规则

1. 普通事件：`page_table_lock -> page_get -> unlock -> page.lock -> domain node_table_lock(短暂) -> unlock -> lruvec.lock`。
2. 删除/RECLAIMED：`page_table_lock -> page.lock -> 从表删除/dying -> unlock page_table -> lruvec.lock`，再释放 page lock 和两个引用。
3. node scan：`domain_table_lock -> domain_get -> unlock -> node_table_lock -> unlock -> lruvec.lock`。
4. 跨 lruvec 移动：在已有 page/domain 引用后按 `(memcg_id,nid)` 全序取得一或两个 lruvec.lock；相同容器只锁一次，按逆序释放。
5. 绝不同时持有 domain_table_lock 和 page_table_lock；禁止 `lruvec.lock -> page.lock/node_table_lock/domain_table_lock`、`page.lock -> page_table_lock`、`node_table_lock -> domain_table_lock`。
6. 析构/最后 put 不在任一 page、domain、node_table 或 lruvec 锁下发生。

## 事件状态机与 seq

- `ON_LRU`：`current_lru` 有效，唯一 `list_node` 位于 `lists[current_lru]`。
- `ISOLATED`：`isolated_from`、`putback_hint` 有效，唯一 `list_node` 位于 `isolated`。
- `DETACHED`：无容器、不在链，LRU 字段无语义。
- engine 为缺失 seq 的调用生成原子递增 seq。`seq == last_event_seq` 设置 duplicate flag 并幂等；`seq < last_event_seq` 设置 stale flag，仅补静态元数据；更大 seq 才推进生命周期。
- 未知 `ISOLATE/MOVE/PUTBACK` 创建 provisional 页面；未知 RECLAIMED 只记录 validation，不创建页面。迟到 ADD/SYNC 补元数据并清 provisional，不回退新状态。
- isolate 正常移入同 lruvec 的 isolated；putback 目标容器/目标 LRU 权威；reclaimed 最终删除；move 目标权威、源仅校验，isolated move 保留来源并更新 putback hint。

## 自愈与 validation

实现规格要求的 duplicate、stale、unknown、without-isolate、hint/source mismatch、invalid nid/LRU、chain-state mismatch、refcount error 位。重复跨 node isolate、putback without isolate、on-LRU reclaimed 和 source mismatch 均修正到事件目标状态，不创建长期 putback/reclaimed 链。

## 扫描与执行

- `shadow_scan_lruvec` 只接受具体 `(memcg_id,nid)`。
- `shadow_scan_node` 在 domain table 中只选择已有目标 nid lruvec，扫描缺失 nid 不创建对象。
- 持有 lruvec.lock 仅制作候选快照，不获取 page.lock；执行前重新从 page table 取引用并核对 memcg、nid、状态、LRU、seq。移动或回收后的旧候选失效即跳过。

## TDD 测试矩阵

先添加失败测试，按下列阶段实现：

1. 稀疏 node table：nid 0/2、缺 nid 1、空 lruvec 保留、扫描不创建。
2. 状态机：正常 isolate、重复/跨 node isolate、putback、自愈、reclaimed、provisional、move。
3. seq：递增、重复、乱序 ADD、并发乱序的最大 seq 收敛。
4. 生命周期：page/domain 延迟释放、删除后禁止新引用、失败注入回滚。
5. 扫描：单 lruvec、node 协调器、候选重验证、isolated 排除。
6. 并发：MOVE/RECLAIMED、PUTBACK/RECLAIMED、ISOLATE/MOVE、双页反向迁移、scan/delete、scan/move。
7. 不变量校验：page 唯一性、链唯一性、容器一致性、计数、dying/UNKNOWN 规则。

## 验证与提交点

每阶段运行 `git diff --check`、CMake debug build/CTest；完成后运行 ASan/UBSan，并在可用时尝试 ThreadSanitizer。重新构建 Linux 6.17 L0.1 相关对象并运行其 parser tests，作为回归。

计划提交：

1. `docs: add per-node shadow LRU implementation plan`
2. `core: add sparse per-domain node table and shadow lruvec`
3. `core: add page and domain reference lifetimes`
4. `core: add isolated lifecycle and validation`
5. `core: add explicit page move and per-node scans`
6. `test: cover lifecycle concurrency and per-node invariants`
7. `docs: document per-memcg-per-node shadow model`

## 明确不做

不修改 Linux 6.17 L0.1 tracepoint 或其语义；不添加 Linux folio hook、原生 memcg/lruvec 枚举、原生 LRU 变更、L0.2/L0.3/L0.4、Linux 候选提交、MGLRU、跨 node 候选、NID_ANY、putback/reclaimed 长期链。
