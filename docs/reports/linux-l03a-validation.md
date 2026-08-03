# Linux L0.3A 页生命周期观测验证报告

## 结论

Result: `LINUX L0.3A PAGE LIFECYCLE OBSERVER COMPLETE`

Linux 6.17 classic-LRU 页生命周期观测、有界 Shadow Page Table、页级 trace、用户态 parser/replay、严格补丁链、对象矩阵及完整 `bzImage + modules` 均已完成。独立审查发现的并发状态写入和交接脚本幂等问题均已修复并回归，未保留 Critical 或 Important 问题。

## Git 与范围

- Main start HEAD: `6f4c2adbadffe9ad9b5ccee339b7cc20bc8e07d0`
- Feature branch: `feat/linux-l03a-page-lifecycle`
- Implementation/review HEAD: `d87f1db35`（本报告提交后的最终 HEAD 以 `git rev-parse HEAD` 为准）
- Feature remote: `NOT PUSHED`
- Main merged: `no`
- Main pushed: `no`
- Installed: `no`
- GRUB modified: `no`
- Rebooted: `no`

实现严格保持 observe-only：未改变 Linux 原生 LRU 分类、隔离选择、回收结果、释放返回值或策略执行路径；未实现四条策略 Shadow LRU 链、planner、executor、预测、eBPF、安装或启动。

## Hook 审计

Hook audit: [linux-l03a-page-lifecycle-hook-audit.md](../design/linux-l03a-page-lifecycle-hook-audit.md)

权威观测转换：

- `ADD_LRU`：`mm/swap.c::lru_add()`
- `ACTIVATE`：`mm/swap.c::lru_activate()`
- `DEACTIVATE`：classic-LRU deactivate/lazyfree 路径
- `ISOLATE`：`mm/vmscan.c::isolate_lru_folios()` 成功清除 LRU 标志后
- `PUTBACK`：`move_folios_to_lru()` 的普通与非 evictable 放回路径
- `RECLAIM`：`shrink_folio_list()` 确认回收成功路径
- `FREE`：最终 refcount 归零的释放路径

条件观测转换：

- `MIGRATE`：成功迁移的源 folio 终态；本阶段不建立源/目标映射。
- `DOMAIN_CHANGE`：同一已跟踪物理身份随后观测到 memcg/nid 改变时生成。

Not reliably observable transitions:

- 启用 observer 前的历史状态；以 `late_discovery/unknown_previous` 表示。
- 所有 compound folio split/merge 的完整一一映射。
- 没有后续页事件的 memcg reparent。
- 所有非 LRU 页的完整分配到释放生命周期。

## Shadow Page Table

- Shadow table: 固定容量、预分配哈希桶 + entry free list + 同容量 tombstone ring。
- Identity scheme: 对外 token 为 `(u64 page_id, u32 lifecycle_gen, u32 order)`；内部仅用 folio head PFN，不输出指针/PFN。
- Max entries: 硬上限 `4096`，默认 `1024`。
- Default enabled: `false`；必须提供合法 mode、memcg、nid、page type 与容量后才可启用。
- Allocation strategy: 仅在 debugfs enable 的进程上下文使用 `kvcalloc(GFP_KERNEL)` 一次性预分配；页级 hook 不分配、不睡眠、不持有 folio/page 引用。
- Concurrency structure: 表内所有 entry/tombstone/counter 由 `spin_lock_irqsave()` 保护；全局 enable/disable 由 mutex 串行化；disable 先在锁内关闭并摘除指针，再在锁外释放。
- Capacity behavior: 满容量只增加 `capacity_drop`，不淘汰活跃 entry，不改变原生 MM。
- MGLRU: enable 时和每次观察前检查，检测到后安全停用并累计 `mglru_rejected`。

## Trace、parser 与 replay

- Trace event: `myself_kswapd_page_lifecycle`
- Producer args: `1`（record 指针），低于 12 参数门禁。
- Trace fields: action、稳定 token、order/nr_pages、页类型、from/to、LRU class、mode、memcg/nid、request/priority/scan、source、reason、flags 完整。
- L0.2 ABI regression: PASS；既有 4 个事件的名称、字段和文本块未改变。
- Parser: `tools/myself_kswapd/parse_page_lifecycle_trace.py`
- Replay oracle: 与内核状态转换实现独立，按 `(page_id, lifecycle_gen)` 重放。
- 异常分类: `TRACE_TRUNCATION`、`LATE_DISCOVERY`、`INVALID_TRANSITION` 分离。
- 输出: 文本 summary、JSON、CSV transitions。

## 测试与验证

### 用户态

- Parser/replay tests: 10 个 L0.3A 测试 PASS。
- Existing Python tests: 19 个 L0.1/L0.2 测试 PASS。
- Python total: 29/29 PASS。
- CTest default: PASS，42/42。
- 100-run tests: PASS，100 轮均为 42/42。
- ASan/UBSan + leak detection: PASS。
- TSan: `NOT RUN / ENVIRONMENT BLOCKED`；二进制成功构建，运行时为 `ThreadSanitizer: unexpected memory mapping`，未声称通过。

### 内核与交接

- Handoff tests: PASS；全新 v6.17 严格执行 `0002 -> 0003 -> 0004`，无 `--3way`、reject 或 fuzz。
- Handoff idempotence: 首次应用 PASS；再次执行 `ALREADY_APPLIED` PASS。
- Final-tree equality: 完整构建源树 final-v2 与严格应用树 final-v3 全树 `diff -qr` 无差异。
- KUnit: 四组配置中的 `page_lifecycle_test.o` 均成功构建；本次安装配置未启用
  运行态 KUnit，因此没有把对象构建替代为运行态 KUnit PASS。
- Config matrix:
  - `MEMCG=y, LRU_GEN=n, DEBUG_FS=y`: PASS
  - `MEMCG=n, LRU_GEN=n, DEBUG_FS=y`: PASS
  - `MEMCG=y, LRU_GEN=y, DEBUG_FS=y`: PASS
  - `MEMCG=y, LRU_GEN=n, DEBUG_FS=n`: PASS
- Object builds: `swap.o`、`vmscan.o`、`migrate.o`、page lifecycle、trace、observer config、heartbeat、debugfs、KUnit 对象均 PASS。
- Shell syntax/self-tests: PASS。
- `git diff --check`（补丁文件除外，实际应用源码另行检查）: PASS。
- checkpatch: `0 errors, 11 warnings, 71 checks`；warning 为 trace/debugfs 长格式字符串及 MAINTAINERS 提示。

### 性能门禁

1000 万次循环的用户态等价快路径 microbenchmark：

- disabled: `0.201 ns/op`
- enabled non-target: `0.334 ns/op`
- enabled target: `0.598 ns/op`

这些数字仅用于实现级相对比较，不代表真实内核 wall-clock 开销。内核 disabled 路径是一次 `READ_ONCE(enabled)` 后返回；hook 内无字符串格式化、无分配、无无界容器增长。

## 补丁与完整构建

- Patch 0002 SHA: `ecc0e4f473ea4a657578568b2a57658ed37590c1a89e366ede7c2c81814d2711`
- Patch 0003 SHA: `35bacaea2de3aae1552f24564d853b0ffb352f7d9929091da3d6026d2cd70b89`
- Patch 0004 SHA: `fd79c09bc78acf2edaf5e3ddb3bb837090492341f5271caea2cc2b8ac0c02ae7`
- Final patch-chain apply: PASS。
- Full bzImage/modules: PASS，初始干净输出完整构建 `build_rc=0`，审查修复后增量完整重链接 `build_rc=0`。
- Kernel release: `6.17.0-myks-l03a`
- Build duration: 初始完整构建 `1:10:45`；审查修复增量重链接 `1:09.93`。
- Modules: `6755` 个 `.ko`。
- Build output: `/home/lzx/Desktop/huawei/outputs/linux-l03a-20260802/builds/linux617-l03a-final`

Artifact hashes:

- `bzImage`: `4f99cacb7ade3692ecf389c01a3891427e936e62dad102bce553994897323f46`
- `vmlinux`: `67eadda36d988f40afb5dce21761c4233022f20ad4e59cde8a01b22b920a726e`
- `System.map`: `9791466ccca3e127e062a231db41f9883518645ac959a039ec3b642db8370a10`
- `modules.order`: `d4f45fc0a3e3f434262308cb06fde1d6b60b6aa0df7957c7a863be2f81df91a6`
- `Module.symvers`: `27090b6a6d04c33f7f63897df0fe1de3f16ff893768c64b37b09f777f9b27e6e`
- `.config`: `57b74de5953c8a8e5bc94c13e59f1d5ab3092a10b6c12d6be8ac3cdcbb921f8b`

## 独立审查

- Critical findings: `0`
- Important findings: `0`
- Minor findings: `3`

已关闭的审查问题：

1. 无效 enable 配置写 `last_error` 未与 status 读取使用同一自旋锁；已修复并增加 KUnit 回归断言。
2. L0.3A 交接脚本先做 L0.2 检测，导致已应用树无法进入 `ALREADY_APPLIED`；已修复并验证首次/重复应用。

保留的 Minor：

1. 完整构建有 7 条 `-Wframe-larger-than`，其中 1 条为既有 L0.2 debugfs 1040-byte 栈帧，其余来自上游基线；L0.3A 新对象无 warning。
2. checkpatch 保留长 trace/debugfs 格式字符串和 MAINTAINERS 提示；`0 errors`。
3. 合并前阶段按禁止项未安装/启动 L0.3A；该缺口现已由下述真实 runtime
   smoke 补充，运行态 KUnit 仍未启用。

Runtime smoke: **L0.3A RUNTIME SMOKE PARTIAL**。

2026-08-03 已人工启动 6.17.0-myks-l03a 并完成真实运行时验证：

- L0.2 request parser：PASS，18 个完整请求、301 轮、总扫描 66,606 页、
  总回收 54,250 页，0 个不完整请求。
- lruvec parser：PASS，真实 trace 中 81,312 个 snapshot event。
- L0.3A page parser/replay：PASS，79,710 个真实页事件、21,176 个生命周期，
  parse issues、invalid transition、missing isolate 和 trace truncation 均为 0。
- 匿名页 41,074 个事件，文件页 38,636 个事件。
- max entries 128 门禁峰值为 128，capacity drop 增长 16,272，
  invalid/duplicate 均不增长，退出和关闭后均清空。
- 15 分钟有界 soak 峰值 1,025/4,096，错误计数不增长。
- 测试状态已恢复，运行前后未发现新增严重内核错误。

结论为 PARTIAL 而非 PASSED：已安装内核是 CONFIG_LRU_GEN=n，系统不存在
/sys/kernel/mm/lru_gen/enabled，所以 MGLRU guard 的真实拒绝及切换/恢复
标记为 NOT RUN / ENVIRONMENT BLOCKED。

完整报告：[linux-l03a-runtime-smoke.md](linux-l03a-runtime-smoke.md)。

## 下一步

L0.3B：仅在人工接受本次 PARTIAL 的 MGLRU 覆盖缺口后，在已验证的
Shadow Page Table 上实现每个 (mode, memcg_id, nid) domain 的四条
Shadow LRU 链及一致性校验。不要自动开始 L0.3B，也不要引入策略排序或
内核执行器。
