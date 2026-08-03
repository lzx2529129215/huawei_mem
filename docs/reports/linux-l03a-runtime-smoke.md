# Linux L0.3A 首次真实运行时验证报告

日期：2026-08-03

结论：**L0.3A RUNTIME SMOKE PARTIAL**

## 1. 目标与结论边界

本轮在人工选择 GRUB 启动项后，验证已合并 L0.3A 的 Linux 6.17 内核
6.17.0-myks-l03a。

页级生命周期事件、独立 replay、Shadow Page Table 容量/清理、匿名页/文件页、
L0.2 request/lruvec 回归和 15 分钟有界稳定性均取得真实运行证据。运行期间
未出现严重内核错误，所有临时状态已恢复。

本次结论不是 PASSED，因为内核配置为 CONFIG_LRU_GEN=n，没有 MGLRU 运行时
接口，无法真实验证 MGLRU guard 的拒绝计数和开关恢复。该项标记为
NOT RUN / ENVIRONMENT BLOCKED。

## 2. 启动与接口基线

- Git branch：main
- 启动时 main：51e30d01a74075744adba719e97814fe43add43f
- running kernel：6.17.0-myks-l03a
- CONFIG_MYSELF_KSWAPD=y
- CONFIG_MYSELF_KSWAPD_PAGE_LIFECYCLE=y
- CONFIG_MEMCG=y
- CONFIG_TRACING=y
- CONFIG_TRACEPOINTS=y
- CONFIG_DEBUG_FS=y
- CONFIG_LRU_GEN=n
- debugfs、tracefs、cgroup v2：均已挂载。
- L0.2 四个事件与 L0.3A page lifecycle event：均存在。
- 启动日志严重错误扫描：0。

默认状态符合设计：page tracking 关闭、tracked entries 为 0、observer 关闭、
全部项目 trace event 关闭。

## 3. 目标 cgroup 与 memcg 映射

基础 smoke 使用专用 cgroup，memory.high=256M、memory.max=512M，
cgroup_id=11039、target_nid=0、target_mode=MEMCG。

没有直接猜测 cgroup ID 等于 memcg ID。先把 11039 写入 L0.2 observer filter，
再读取 debugfs snapshot；snapshot 成功返回 memcg_id=11039、nid=0，据此证明
该 ID 可由内核 observer 解析。

## 4. 匿名页、文件页与真实事件

匿名页压力上限 384 MiB，按 4 MiB 分块；文件页使用仓库外 128 MiB 临时文件。
两者均放入专用 cgroup，只执行 memory.reclaim=64M，未使用全局 drop_caches、
swappiness、OOM、水位或无界压力。

基础 trace：

    /home/lzx/Desktop/huawei/outputs/linux-l03a-runtime-smoke-20260803/traces/basic.trace

| 项目 | 数量 |
|---|---:|
| 页级事件 | 79,710 |
| 唯一生命周期 | 21,176 |
| 匿名页事件 | 41,074 |
| 文件页事件 | 38,636 |
| request events | 337 |
| lruvec snapshots | 81,312 |

| Action | 数量 | 结论 |
|---|---:|---|
| DISCOVER | 0 | NOT OBSERVED |
| ADD_LRU | 15,715 | OBSERVED |
| ACTIVATE | 0 | NOT OBSERVED |
| DEACTIVATE | 0 | NOT OBSERVED |
| ISOLATE | 26,862 | OBSERVED |
| PUTBACK | 14,459 | OBSERVED |
| RECLAIMED | 12,403 | OBSERVED |
| FREE | 9,203 | OBSERVED |
| MIGRATE | 534 | OBSERVED |
| DOMAIN_CHANGE | 534 | OBSERVED |

规范不要求每种事件都出现，因此没有为追求缺失事件而提高压力。

## 5. Parser、replay 与 L0.2 回归

三个 parser 均读取真实 ftrace 文本并退出 0：

- request parser：337 events，18 个完整请求，0 个不完整请求。
- 18 个请求共 301 轮，扫描 66,606 页，回收 54,250 页，均以 BALANCED 结束。
- lruvec parser：81,312 个 snapshot event。
- page parser/replay：79,710 events、21,176 lifecycles、21,176 terminal、
  active-at-end 0。

Page replay 指标：

| 指标 | 值 |
|---|---:|
| parse issues | 0 |
| trace truncation | 0 |
| invalid transition | 0 |
| missing isolate | 0 |
| putback without isolate | 0 |
| reclaimed without isolate | 0 |
| late discovery | 5,461 |
| duplicate terminal | 964 |
| reuse detected | 4,156 |

964 个 duplicate terminal 全部是同一 lifecycle 的 RECLAIMED 后出现最终 FREE，
属于回收确认和最终 refcount 释放两个权威 hook 的可解释重叠。

基础过容量测试的内核 status 累计 124,166 个 invalid transition，但 trace 中
没有 INVALID_TRANSITION flag，独立 replay 也为 0。源码与容量实验表明，这些
计数来自表满后未被跟踪页的 PUTBACK：entry 因 capacity drop 未创建，随后
PUTBACK 找不到 entry 而只增加内部计数、不发事件。小容量可控实验和未超容量
soak 均证明该计数不再增加，因此归类为可解释过容量记账，不等同于已跟踪
生命周期损坏。

## 6. Shadow Page Table 容量与清理

主测试 max entries=4,096，tracked peak=4,096，basic 结束、进程退出并关闭
tracking 后为 0；capacity drop=282,328，alloc fail=0。

小容量门禁：

| 指标 | 结果 |
|---|---:|
| max entries | 128 |
| tracked peak | 128 |
| capacity drop delta | 16,272 |
| invalid transition delta | 0 |
| duplicate terminal delta | 0 |
| tracked after exit | 0 |
| tracked after disable | 0 |

小容量 replay 为 256 events、128 lifecycles、128 ADD_LRU、128 FREE，
parse/invalid/duplicate/truncation 均为 0。

## 7. 15 分钟有界稳定性

时间：2026-08-03 18:44:05 至 18:59:05。

- 30 轮，每轮间隔 30 秒。
- 每轮只分配/访问 4 MiB 匿名页。
- 每 3 轮执行一次 memory.reclaim=4M。
- 始终受 memory.high=256M、memory.max=512M 约束。
- events：79,966 → 211,218。
- tracked peak：1,025/4,096。
- 每轮进程退出后 tracked：0。
- alloc fail：0 → 0。
- capacity drop：298,600 → 298,600。
- invalid transition：124,166 → 124,166。
- duplicate terminal：964 → 964。
- disable 后 tracked：0。
- 无系统失去响应、OOM、Oops、BUG、panic、lockup 或 hung task。

## 8. MGLRU 覆盖

- MGLRU guard：NOT RUN / ENVIRONMENT BLOCKED。
- Classic-LRU switch：NOT RUN / NOT APPLICABLE。
- MGLRU restored：NOT RUN / NOT APPLICABLE。

实际启动配置为 CONFIG_LRU_GEN=n，系统不存在
/sys/kernel/mm/lru_gen/enabled。当前内核从启动起就是 classic-LRU，因此
classic-LRU observer/page lifecycle 已真实验证，但不能用编译态测试代替
MGLRU guard 运行证据。

## 9. 清理审计

最终状态：

- page tracking 关闭，tracked entries 为 0。
- observer 关闭。
- 项目 trace events 全部关闭。
- tracing_on 恢复为 1。
- buffer_size_kb 恢复为原请求值 7。
- 测试 cgroup、压力进程、临时文件均不存在。
- 最终 dmesg 与启动基线相比没有新增严重错误。

observer config generation 因合法写入单调增加，这是设计内版本计数，其余
配置语义已恢复。

## 10. 最终判定

- Critical：0。
- Important：0。
- Minor：3。

Minor：

1. MGLRU guard/切换/恢复因 CONFIG_LRU_GEN=n 未取得运行证据。
2. DISCOVER、ACTIVATE、DEACTIVATE 未观察到。
3. 过容量测试会把未跟踪页的 PUTBACK 计入内核 invalid counter；真实 replay
   无非法转换，且小容量/soak 不新增该计数。

独立只读审查最初提出 2 个 Important，均已关闭：

1. 基础日志保留首次 trace buffer 恢复失败。随后已特权恢复原值 7，
   三个 smoke 脚本均改为让 cleanup 失败传播到退出码，并保存
   logs/cleanup-final-verification.txt；该快照证明控制项、事件、cgroup、
   进程和临时文件均已恢复。
2. 最终外部报告和 release 字段缺失。外部完成报告在最终提交后按实际
   main/remote/tag 填写并复审。

独立审查最终门禁：Critical 0，Open Important 0。

依据规范，核心状态机和表行为通过、仅剩明确环境/难触发覆盖缺口时可判
PARTIAL。因此结论为：

    L0.3A RUNTIME SMOKE PARTIAL

证据目录：

    /home/lzx/Desktop/huawei/outputs/linux-l03a-runtime-smoke-20260803
