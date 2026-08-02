# Linux L0.3A 合并前独立审查

日期：2026-08-02

审查对象：`feat/linux-l03a-page-lifecycle@bbccb7c5c1bdb7abc9dcf0deb51b05bc38eb0889`

基线：`main@6f4c2adbadffe9ad9b5ccee339b7cc20bc8e07d0`

## 结论

- Critical：0
- Important：0
- Minor：3，均已明确处置，不阻塞安装前合并。
- 结论：`READY TO MERGE`，前提是 Phase B 最终回归继续通过。

审查确认实现保持 observe-only：未改变 Linux 原生隔离选择、LRU 分类、回收计数、释放返回值或迁移结果；页 hook 不分配、不睡眠、不持有额外 folio/page 引用。Shadow Page Table 固定容量，关闭时在锁内先关闭 gate 和摘除存储指针，再在锁外释放；未发现 UAF、引用泄漏、无界增长或 page token 复用安全问题。

## Minor 1：完整构建栈帧 warning

- 现象：完整构建日志有 7 条 `-Wframe-larger-than=1024`。其中 `myks_debugfs_append_snapshot()` 为 1040 bytes，属于既有 L0.2；另外 6 条来自 Linux 6.17 上游基线的 maple tree、random、AMD display 和 WireGuard。
- 影响范围：编译期栈帧阈值提示；L0.3A 新增 `page_lifecycle.c`、trace 和 KUnit 对象无 warning。
- 是否影响运行安全：没有证据表明当前 16-byte 超限会导致溢出；仍在安装后 dmesg/soak 中监控 stack/lockup warning。
- 是否影响页身份/生命周期：否。
- 是否影响 patch 完整性：否，0004 未遗漏文件。
- 是否必须安装前修复：否。为避免超出 L0.3A 范围，不顺带重构 L0.2 snapshot 或上游代码。
- 处置结果：接受为非阻塞 Minor，保留构建日志证据，运行期继续监控。

## Minor 2：checkpatch 风格提示

- 现象：当前 0004 checkpatch 为 `0 errors, 11 warnings, 71 checks`。warning 是 trace/debugfs 长格式字符串、测试 fixture 长字符串及 MAINTAINERS 提示；checks 主要是项目既有续行风格。
- 影响范围：源码排版与维护元数据，不涉及执行语义。
- 是否影响运行安全：否。
- 是否影响页身份/生命周期：否。
- 是否影响 patch 完整性：否；严格 allowlist、trace 合约和全新 patch-chain 已通过。
- 是否必须安装前修复：否。拆分 trace 文本会增加冻结 ABI 风险，机械重排也不提供运行安全收益。
- 处置结果：接受为非阻塞 Minor；保持 `0 errors`，不改变 L0.2/L0.3A trace ABI。

## Minor 3：尚无 L0.3A 运行态证据

- 现象：上一阶段按禁止项未安装或启动 `6.17.0-myks-l03a`，因此 debugfs、ftrace、MGLRU guard、容量门禁和运行态 KUnit 尚未在该内核上执行。
- 影响范围：运行覆盖缺口，不是已确认代码缺陷。
- 是否影响运行安全：安装后必须先检查 dmesg/journal 和默认关闭状态；出现 Oops/BUG/lockup/UAF 即停止。
- 是否影响页身份/生命周期：尚待真实 ftrace replay 验证，但内核 KUnit 对象、独立用户态 oracle 和完整构建均已通过。
- 是否影响 patch 完整性：否。
- 是否必须安装前修复：不适用；本轮目标正是安装后完成人工启动和 runtime smoke。
- 处置结果：转为 Phase E–M 的强制运行门禁。安装阶段不自动重启，必须等待人工选择新内核。

## 安全与并发复审

- disabled fast path：`READ_ONCE(enabled)` 后返回。
- 分配：仅 debugfs enable 进程上下文预分配三个固定数组；热 hook 无分配。
- 锁：entry、tombstone、计数器和配置存储由 `spin_lock_irqsave()` 保护；全局 enable/disable 使用 mutex。
- 释放：表不持有页引用；disable 的并发观察者在同一自旋锁 gate 下退出。
- token：trace 仅输出 `(page_id,lifecycle_gen,order)`，不输出 PFN 或指针。
- 终态：RECLAIMED/DEAD 立即移出活跃表；固定 tombstone ring 只辅助复用和重复终态检测。
- 容量：硬上限 4096；满容量只累计 `capacity_drop`，不淘汰活跃 entry。
- 原生语义：hook 调用不参与 Linux 原生条件判断或返回值；`move_folios_to_lru()` 只新增只读 `scan_control` 上下文参数。
- MGLRU：enable 和每次观察均有 guard，不把 generation LRU 冒充 classic-LRU。

## 补丁与 ABI

- 0002 SHA256：`ecc0e4f473ea4a657578568b2a57658ed37590c1a89e366ede7c2c81814d2711`
- 0003 SHA256：`35bacaea2de3aae1552f24564d853b0ffb352f7d9929091da3d6026d2cd70b89`
- 0004 SHA256：`fd79c09bc78acf2edaf5e3ddb3bb837090492341f5271caea2cc2b8ac0c02ae7`
- L0.2 trace ABI：未改变。
- L0.3A producer args：1。
- 全新 `pristine -> 0002 -> 0003 -> 0004`：已通过，无 3-way/reject/fuzz。

## Phase B 门禁

已在 feature HEAD `bbccb7c5c1bdb7abc9dcf0deb51b05bc38eb0889` 上完成，证据目录：

`/home/lzx/Desktop/huawei/outputs/linux-l03a-premerge-20260802/logs/`

- Python parser/oracle：29/29 PASS。
- 用户态 CTest：42/42 PASS。
- ASan/UBSan 与 leak detection：42/42 PASS。
- 用户态全套 100 轮：每轮 42/42，共 4200 次测试，PASS。
- handoff、L0.2/L0.3A shell self-tests 与 shell syntax：PASS。
- 全新 `pristine -> 0002 -> 0003 -> 0004`：PASS；L0.2 ABI 和 L0.3A trace contract：PASS。
- 四组 Linux 对象矩阵：`MEMCG=y/n`、`LRU_GEN=y/n`、`DEBUG_FS=y/n` 全部 PASS。
- KUnit 对象：四组配置中的 `page_lifecycle_test.o` 全部实际生成且非空。
- `git diff --check`（排除补丁载荷本身）：PASS。
- TSan：本阶段未重新宣称通过；历史环境结果仍为 `NOT RUN / ENVIRONMENT BLOCKED`（`ThreadSanitizer: unexpected memory mapping`）。

Phase B 未产生新的 Critical、Important 或 Minor。合并门禁满足，最终结论保持 `READY TO MERGE`。
