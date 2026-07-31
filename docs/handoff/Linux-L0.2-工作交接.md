# Linux L0.2 正式跨设备工作交接

## 1. 目标与边界

L0.2 是 Linux 6.17 上的 observe-only 观测原型。它为未来 OpenHarmony classic global LRU 迁移收集 reclaim request、priority、scan、lruvec 和 trace 数据，但不改变 Linux 原生 reclaim 决策，不执行页面优先级策略，不跟踪页面生命周期，也不依赖 eBPF。

目标接手者只需从远端 `main` clone，并按 [快速复现](Linux-L0.2-快速复现.md) 执行脚本，即可从公开固定 URL 下载精确基线、校验来源、应用 0002/0003、编译 `bzImage + modules` 并完成静态构建验证。完整 Linux 源码不进入普通 Git；`Linux6.17/` 仍是 ignored 路径。

## 2. 为什么做 L0.2

目标系统是 classic global LRU，而 Linux 6.17 同时存在 memcg/lruvec 语义及可选 MGLRU。L0.2 将 Linux 内核当前可见状态作为观测输入，保持 GLOBAL 与 MEMCG 分离，并在 MGLRU 开启时拒绝把 generation 状态伪装成 classic snapshot。这样可以先验证语义和数据链，再在 OpenHarmony 中替换平台接口。

研究链为：

```text
内核状态采集 -> reclaim request/priority/scan -> lruvec snapshot
-> 用户态 parser -> Shadow LRU -> workload/policy engine
-> OpenHarmony 全局 LRU 适配
```

Shadow physical state 与 policy metadata 分离；Shadow 只提供候选和统计，不接管真实页面释放、页表拆除、回写或 swap。

## 3. 架构

- `mm/vmscan.c`：最小 hook，采集 kswapd/direct/memcg reclaim 的生命周期和标量快照。
- `mm/myself_kswapd/`：独立 observer、lruvec snapshot、debugfs、heartbeat、配置和 KUnit 接入。
- `include/trace/events/myself_kswapd.h`：trace ABI。`request_id -> priority_seq -> scan_seq` 保持可关联；producer 参数不超过 12 个，复杂状态通过结构体指针传入。
- `tools/myself_kswapd/`：现有 parser、CLI、用户态测试和 L0.2 检查。
- `scripts/handoff/`：跨设备下载、校验、补丁、配置、构建、验证和安全安装流程。

root memcg 不伪装为 GLOBAL；GLOBAL 只来自明确的 global lruvec。MGLRU guard 在 classic snapshot 不安全时拒绝采样。heartbeat 只在 observer 允许且配置 generation 匹配时工作；禁用 debugfs、memcg、或 classic LRU 的四组门禁都必须可构建。

## 4. 精确基线与补丁

当前成功构建使用的 pristine 基线已调查为 kernel.org 官方 Linux `v6.17`，Git commit `e5f0a698b34ed76002dc5cff3804a61c80233a7a`，归档 URL 为 `https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.17.tar.xz`。归档 SHA256 和 90,506 条 `mode path sha256` 文件清单见 `checksums/`。

补丁必须按顺序严格应用：

1. `patches/0002-linux617-myself-kswapd-l01.patch`，在源码目录使用 `-p1`。
2. `patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch`：脚本先仅规范化其 `Linux6.17/` 文件头前缀，再以 `-p1` 应用正文；这避免依赖 clone 目录名，也不会改写 patch 内容或放宽上下文匹配。

脚本禁止 `--3way`、`--reject`、`--whitespace=fix` 和模糊应用；重复执行会报告 `ALREADY_APPLIED`，部分或未知状态直接失败。

## 5. 配置、构建与产物

默认继承当前系统配置，也支持显式 `--config FILE` 或 `--defconfig`。脚本固定清空 trusted/revocation keys，启用 `MYSELF_KSWAPD`、`MEMCG`、`TRACING`、`TRACEPOINTS`，并设置 `LOCALVERSION=-myks-l02`。`CONFIG_DEBUG_INFO_BTF=y` 而缺少 `pahole` 时会失败，只有显式 `--disable-btf` 才允许关闭。

构建使用 `O=builds/linux-6.17-l02`，保存完整日志、`BUILD-METADATA.txt`、`SHA256SUMS`、`.config` 和 kernelrelease。验证要求 `bzImage`、`vmlinux`、`System.map`、`modules.order`、`Module.symvers`、observer objects、config 门禁、vermagic/kernelrelease 和 trace 参数门禁均通过。

## 6. 安装、回退与运行时

安装脚本默认 dry-run，只有 `--execute` 才需要 root；执行时会检查 Secure Boot、备份 GRUB、执行 `modules_install`、复制内核文件、生成 initramfs 和更新 GRUB，绝不自动 reboot。首次启动应人工选择新内核；启动失败时在 GRUB 选择旧内核，确认旧内核可用后再处理安装文件。

runtime smoke 默认 `--read-only`：确认 `uname -r`、读取 dmesg、定位 tracefs/debugfs、读取 MGLRU guard，并检查 L0.2 trace 目录。`--bounded-reclaim --output-dir DIR -- COMMAND` 才会调用既有 capture helper，短时启用 L0.2 trace events、保存 raw trace 并用现有 parser 解析；helper 的 cleanup trap 会关闭这些 events。它不改 global sysfs；任何 disposable cgroup 压力实验都必须由接手者在直接监督下执行。

## 7. 当前状态与证据规则

以下状态必须区分当前执行与历史证据：

- L0.1/L0.2 实现、0002/0003 补丁链和既有用户态测试：历史报告已记录通过；新机器仍应执行本交接测试。
- 当前 `main` 起始 HEAD：`1863e2723800a929c28d7326941a45d37f2c4ca2`；远端是否一致必须在最终报告中重新记录。
- 既有 runtime smoke：报告记录为 `NOT RUN / ENVIRONMENT BLOCKED`，不能改写为完成。
- TSan：环境 `unexpected memory mapping` 阻塞，记录为 `NOT RUN / ENVIRONMENT BLOCKED`。
- Secure Boot、硬件内存、并发度和构建时间会因设备变化；公开 URL 长期可访问性仍需在未来 release 再确认。
- OpenHarmony 源码版本尚未对齐，L0.3 尚未开始。

## 8. 已解决的交接风险

历史实现中已处理磁盘空间、Canonical 证书路径、heartbeat.c allowlist、observer_config 的 `mm.h` 依赖、tracepoint 12 参数上限以及 final patch-applied tree 门禁。跨设备流程将这些检查变成脚本门禁，而不是依赖某台机器的 ignored 源码或构建目录。

## 9. OpenHarmony 迁移关系

Linux L0.2 是语义和验证原型。OpenHarmony 可能没有 eBPF，因此核心观测链不得把 eBPF 当作前提；后续只替换 trace/debugfs/内存域等平台接口。OpenHarmony 的全局 LRU 数据结构可能没有 Linux memcg lruvec，不能直接复制 Linux memcg 代码，必须保持 GLOBAL 数据源和 policy adapter 的独立边界。

## 10. 后续路线

P0 复验/完成 runtime smoke；P1 冻结 L0.2 release/tag；P2 第二台机器独立复现；P3 OpenHarmony 内核能力探测；P4 global-LRU adapter；P5 L0.3 页面级生命周期；P6 策略执行与灰度。

## 11. 入口索引

- 快速流程：`docs/handoff/Linux-L0.2-快速复现.md`
- 故障处理：`docs/handoff/Linux-L0.2-故障排查.md`
- 文件与提交：`docs/handoff/Linux-L0.2-文件与提交清单.md`
- 验证结果：`docs/handoff/Linux-L0.2-交接验证报告.md`
- 全流程：`scripts/handoff/reproduce_all.sh`
