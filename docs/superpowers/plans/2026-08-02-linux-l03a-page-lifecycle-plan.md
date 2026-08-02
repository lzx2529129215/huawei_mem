# Linux L0.3A 页生命周期实施计划

基线：`6f4c2adbadffe9ad9b5ccee339b7cc20bc8e07d0`

分支：`feat/linux-l03a-page-lifecycle`

每项严格执行 RED（目标行为缺失导致失败）→ GREEN（最小实现）→ REFACTOR
→ 回归 → `git diff --check` → 单独提交。Critical/Important 未关闭不得进入
高风险后续项。

## Task 1：基线和真实路径审计

- 验证 main/remote/补丁 SHA 和 clean worktree；创建功能分支。
- 从固定 archive 创建 pristine Linux 6.17 开发树，严格应用 0002、0003。
- 审计 add/access/activate/deactivate/isolate/putback/reclaim/free/migrate/
  memcg/split/merge 的锁、分配和覆盖范围。
- 落盘 hook audit 与设计；确认不修改 0002/0003。

## Task 2：用户态 replay RED/GREEN

- 先新增 fixtures 和测试：合法转换、late isolate、错误 putback/activate、
  重复 terminal、reuse、混合 page/request、截断、真实/legacy event name。
- 实际运行并保存缺少 parser/replay 的 RED。
- 最小实现 parser、独立 oracle、文本/JSON/CSV；运行新增与既有 19 项。
- 增加 disabled/non-target/target 的纯用户态状态机 microbenchmark。
- 提交 `test/tools: add L0.3A lifecycle replay`。

## Task 3：内核纯状态机与表 RED/GREEN

- KUnit RED：合法/非法转换、token、reuse、terminal、capacity、filter、
  alloc failure、MGLRU、enable/disable/clear、context、compound head helper。
- 新增 Kconfig、header、固定哈希表、预分配 entry/tombstone 和统计。
- 只构建新增对象和 KUnit object；关闭配置时验证 hook stub。
- 提交 `mm: add bounded shadow page table`。

## Task 4：Trace 与 Linux hook RED/GREEN

- 先扩展 trace 字段/arg-limit/L0.2 ABI 静态测试并取得 RED。
- 新增单参数 page lifecycle trace record。
- 在审计确认的 post-transition 点接入 hook；reclaim 路径传播当前 scan ctx。
- 编译 swap/vmscan/migrate/trace/observer 对象，检查 warning 与原生返回值 diff。
- 提交 `mm: observe page lifecycle transitions`。

## Task 5：Debugfs RED/GREEN

- 测试严格配置、target、容量、MGLRU、状态快照和 disable clear。
- 新增同目录 page lifecycle config/status，不改 L0.2 文本 ABI，不提供无界 dump。
- 运行 KUnit/object/config parser 回归。
- 提交 `mm: expose bounded lifecycle controls`。

## Task 6：0004 与 handoff

- RED：allowlist/开发树 touched path 差异、遗漏文件、错误补丁顺序。
- 修复 L0.2 handoff 脚本的 check/apply 顺序问题；新增 L0.3A refresh/check 脚本。
- 生成仅含 L0.3A 的 0004，确认 0002/0003 SHA 不变。
- pristine → 0002 → 0003 → 0004，禁止 3way/reject/fuzz；逐路径归一化比较。
- 提交 `build: add Linux 6.17 L0.3A patch chain`。

## Task 7：回归和配置矩阵

- 既有 Python 19 项、新增 parser/replay、CTest、handoff、L0.2 shell/self、
  trace 参数上限、L0.2 ABI。
- 在开发树和最终补丁树重复新增对象、trace.o、observer_config.o、heartbeat.o、
  built-in.a、KUnit object。
- 验证 MEMCG/LRU_GEN/DEBUG_FS 四组矩阵及 `CONFIG_MYSELF_KSWAPD_PAGE_LIFECYCLE=n`。
- 所有失败按系统化调试记录根因、最小修复与回归。

## Task 8：完整内核构建

- 只在最终 patch-applied tree out-of-tree `-j2` 构建 bzImage + modules。
- 验证 bzImage、vmlinux、System.map、modules.order、Module.symvers。
- 生成 kernelrelease、SHA256SUMS、BUILD-METADATA.txt；不安装、不改 GRUB、不重启。

## Task 9：独立只读审查与报告

- 审查 reclaim 语义、原子上下文、引用/UAF、复用、边界、disabled 成本、
  0004 完整性、0002/0003 哈希和 L0.2 ABI。
- 关闭全部 Critical/Important；Minor 记录处置。
- 写仓库 validation 与外部 completion report；运行 `git diff --check` 和 clean 检查。
- 小提交收尾；默认不 push、不 merge。
