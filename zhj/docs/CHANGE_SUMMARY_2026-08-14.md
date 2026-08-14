# Linux 6.17 内存调度实验代码修改说明

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 仓库 | `lzx2529129215/huawei_mem` |
| 修改目录 | `zhj/` |
| 开发分支 | `codex/zhj-measurement-hardening` |
| 主功能提交 | `e64a380d8effe16324cbd297cd06a79467febac9` |
| Python 包版本 | `memsched-exp 0.2.0` |
| 目标环境 | Linux 6.17.x、cgroup v2、Python 3.10+ |
| 修改日期 | 2026-08-14 |

本文档说明本轮对 Linux 6.17 内存调度实验采集框架所做的修改、修改原因、测量口径、文件对应关系、验证结果以及仍需外部模块提供的能力。本文档只描述实验和代码实现，不涉及桌面自动化操作方案。

## 2. 修改结论

本轮修改将原有“能启动脚本并输出部分指标”的代码，完善为一套具有以下能力的实验测量框架：

1. 采集器、工作负载和 cgroup 使用统一的开始/停止协议，避免漏采应用启动初期数据。
2. 系统级和前台应用 cgroup 级指标在同一正式测量窗口内采集。
3. eBPF Direct Reclaim 事件先在完整事件流中配对，再按正式窗口裁剪，避免跨边界事件被错误判定为丢失。
4. GB 级冷启动场景使用 `mincore` 验证目标文件缓存是否真正被驱逐，不再只依赖清缓存命令是否执行成功。
5. 每轮实验生成正式 manifest，记录实验组、场景、种子、重复编号、内核、策略状态、环境指纹和工作负载指纹。
6. Baseline 与 Candidate 只在实验条件严格一致时配对，并输出成对差异、分位数和 Bootstrap 95% 置信区间。
7. 无效采集轮次输出 `measurement_valid=false` 和具体原因，不使用数值 `0` 冒充缺失数据。
8. 增加 Linux 6.17 集成检查入口及 31 项单元测试。

## 3. 本轮重点解决的数据失真问题

### 3.1 启动阶段漏采

原流程可能在工作负载已经开始执行后才读取 `before.json`。这会漏掉进程 `exec`、文件读取、内存分配、Page Re-fault 和 Direct Reclaim 等启动初期事件。

修改后固定采用六阶段顺序：

```text
before snapshot
  -> collector_ready
  -> workload_start
  -> workload_stop
  -> after snapshot
  -> collector_done
```

所有协议事件均使用原子写入的 JSON marker，并保存单调时钟时间。统计速率使用 `workload_start` 到 `workload_stop` 的正式窗口时长，而不是采集器前后快照的总耗时。

### 3.2 短任务退出导致 cgroup 数据消失

AppFlow 等短任务可能在采集器读取 `after.json` 之前退出，systemd transient service 的 cgroup 随后消失，使 CPU、I/O 和 OOM 指标无效。

新增 wrapper 模式：子任务完成后先发布 `workload_stop`，父进程继续保留 cgroup，直至系统级和 cgroup 级采集器均写出 `collector_done`。

### 3.3 eBPF 跨边界事件错误

Direct Reclaim 可能在正式测量窗口开始前进入、窗口内结束，或在窗口内进入、窗口结束后退出。如果先截取窗口再匹配 begin/end，就会生成伪造的未配对错误。

修改后的处理顺序为：

1. 读取完整 eBPF 事件流；
2. 按线程 TID 配对 `direct_reclaim_begin/end`；
3. 校验丢事件、重复 begin、孤立 end 和负持续时间；
4. 将完整配对投影到正式测量窗口；
5. 分别输出窗口内裁剪时长、完整持续时间和跨边界事件数量。

### 3.4 “冷启动”缺少可验证证据

只执行 `drop_caches` 或 `posix_fadvise` 并不能证明目标文件已经处于冷缓存状态。本轮增加 `mincore` 驻留页检测：

1. 记录驱逐前驻留页数量和比例；
2. 对目标文件执行 `POSIX_FADV_DONTNEED`；
3. 再次读取驻留页状态；
4. 仅当驻留比例低于配置阈值时允许启动工作负载；
5. 将证据保存到 `cache-eviction.json`。

该方案只处理实验目标文件，不会清空整台机器的文件缓存。

### 3.5 实验轮次无法严格配对

原始汇总结果缺少统一的实验身份，容易把不同内核、不同缓存状态、不同随机种子或不同工作负载文件的数据放在一起比较。

新增 schema version 4 manifest。Baseline/Candidate 配对键包括：

```text
scenario + seed + repetition + cache_state + workload_hash
```

同时要求 `environment_hash` 一致。环境指纹包括 CPU、内存、swap/zram、VM sysctl、THP、CPU governor、频率约束、NUMA 和结果文件系统等信息。

### 3.6 进程是否存活判定不可靠

只检查 PID 是否存在可能受到 PID 复用影响。新实现使用以下身份组合：

```text
boot_id + PID + /proc/PID/stat starttime + cgroup
```

据此区分 `cold_start`、`hot_resume`、`cold_restart` 和 `terminated`，并计算后台应用存活数量、存活率和冷重启次数。

### 3.7 策略配置与实际内核状态不一致

当 `/sys/kernel/debug/parp` 存在时，runner 会读取：

- `effective_tier_mode`
- `effective_tier_stats`
- `effective_tier_config`

然后核对 `POLICY_MODE`、`APPLY_COMPILED` 和 `MODEL_PROVENANCE`。声明值与内核实际状态不一致时，工作负载不会开始，避免把未生效的策略误标为 Candidate。

## 4. 指标实现状态

| 指标 | 当前实现 | 数据源或限制 |
|---|---|---|
| Page Re-fault 次数 | 已实现 | `/proc/vmstat` 或 cgroup v2 `memory.stat` 中的 `workingset_refault_*` 窗口差分 |
| Page Re-fault 比率 | 已实现 | `refault_delta / pgsteal_delta`，同时保留分子和分母 |
| Direct Reclaim 次数 | 已实现 | 首选 eBPF tracepoint；`allocstall*` 作为独立回退代理 |
| Direct Reclaim 比率 | 已实现 | 直接扫描页占全部扫描页比例；另输出 direct begin/kswapd wake 事件代理比例 |
| 前台应用页面重错 | 已实现 | 前台应用独立 cgroup 的 `memory.stat` |
| CPU 使用率 | 已实现 | 系统 `/proc/stat` 与 cgroup v2 `cpu.stat` |
| I/O 吞吐量 | 已实现 | cgroup v2 `io.stat`，分母使用正式工作负载时长 |
| Linux OOM kill | 已实现 | `memory.events:oom_kill` 与 eBPF `oom:mark_victim` |
| 应用启动/热启动延迟 | 支持汇总 | 需要自动化或应用探针提供准确的启动、首帧/可交互 marker |
| GB 级应用冷启动 | 合成负载已实现 | 提供 1.2 GiB 实体文件、SHA-256、冷缓存证据和读取吞吐；真实应用首帧仍需外部 marker |
| 冷重启次数 | 已实现判定逻辑 | 需要自动化模块提供切换前后的目标 PID |
| 后台应用存活率 | 已实现判定逻辑 | 使用稳定进程身份比较前后快照 |
| 最大缓存应用数量 | 支持汇总 | 需要逐步增加应用数量的外部场景控制 |
| FPS、FPS 标准差 | 已实现统计 | 需要图形采集器提供帧时间 CSV |
| Jank Ratio | 已实现统计 | 默认按帧预算判断；帧事件必须由外部采集器提供 |
| Java 堆占比 | Fleet/JVM 场景支持 | 按同一应用索引配对 heap 与 RSS；QQ/WPS 原生进程不填写 |
| 对象重访问比率 | 支持汇总 | 需要运行时或应用埋点提供对象重访问事件 |
| GC 工作集大小 | 未直接采集 | 需要 JVM/ART/JVMTI 或运行时探针，不能用 eBPF 页事件替代 |
| LMK 事件 | Linux 不适用 | LMKD 为 Android 机制；通用 Linux 只报告 OOM，不伪装成 LMK |

缺少可信数据源的字段必须输出 `null/N/A`，不能填 `0`。

## 5. 主要代码文件及职责

### 5.1 新增文件

| 文件 | 职责 |
|---|---|
| `memsched_exp/protocol.py` | 原子 marker、协议时间戳、等待 collector/workload 事件 |
| `memsched_exp/cache_state.py` | `mincore` 文件驻留检测、定向冷缓存驱逐和阈值校验 |
| `memsched_exp/schema.py` | schema-v4 manifest、环境指纹和工作负载指纹 |
| `memsched_exp/compare.py` | Baseline/Candidate 严格配对与统计分析 |
| `memsched_exp/process_lifecycle.py` | 稳定进程身份、冷热启动和后台存活判断 |
| `memsched_exp/policy_state.py` | debugfs 策略生效状态读取与核对 |
| `tests/integration/linux617_pipeline.py` | Linux 6.17 真实协议和 cgroup 集成检查入口 |
| `docs/MEASUREMENT_SYSTEM_GUIDE.md` | 完整部署、采集接口和验收手册 |

### 5.2 重点修改文件

| 文件 | 主要修改 |
|---|---|
| `memsched_exp/cli.py` | before/ready/start/stop/after/done 协议、manifest 接入、正式窗口时长和无效轮次处理 |
| `memsched_exp/metrics.py` | 正式窗口速率分母、系统和 cgroup 指标汇总 |
| `memsched_exp/bpf_events.py` | 完整流配对、窗口投影、跨边界统计和错误校验 |
| `memsched_exp/start_marker.py` | 多采集器就绪屏障和短任务 cgroup 保活 wrapper |
| `memsched_exp/report.py` | 新增协议开销、前台 refault、eBPF、manifest 和场景有效性字段 |
| `memsched_exp/snapshot.py` | CPU 型号、频率约束、NUMA、boot ID 等环境信息 |
| `memsched_exp/workload_summary.py` | Fleet Java heap/RSS 按应用索引配对，修正错误聚合 |
| `scripts/preflight.sh` | Linux 版本、cgroup controller、systemd、Python 模块、冷缓存和 debugfs 检查 |
| `scripts/run_qq_wps_round.sh` | 系统级与前台 cgroup 采集器同步启动，输出 manifest |
| `scripts/scenarios/run_acclaim.sh` | 前后台 cgroup 屏障、稳定期和进程保活 |
| `scripts/scenarios/run_appflow.sh` | 冷缓存证据、短任务 wrapper、系统/cgroup/eBPF 同窗采集 |
| `scripts/scenarios/run_fleet.sh` | 标准 marker 协议和正式 manifest |

## 6. 场景脚本行为

### 6.1 QQ/WPS 首轮采集

`run_qq_wps_round.sh` 会并行启动系统级和目标 cgroup 级采集器。只有两个采集器都完成 before 快照并发布 ready 后，应用才允许启动。应用退出或外部自动化发布 stop 后，两个采集器完成 after 快照并分别发布 done。

该脚本负责内核和 cgroup 指标采集，不负责点击坐标、登录账号或识别业务页面。

### 6.2 Acclaim 类型多应用压力场景

`run_acclaim.sh` 增加后台应用稳定时间，并保证前台工作负载和 cgroup 在 after 快照前仍存在。适合测量前台 Page Re-fault、Direct Reclaim、后台应用存活以及内存压力下的前台保护效果。

### 6.3 AppFlow 类型 GB 级冷启动场景

`run_appflow.sh` 在启动前生成或验证 1.2 GiB 实体数据文件，执行目标文件冷缓存驱逐并保存证据。短读取任务完成后由 wrapper 保持 cgroup，直至所有采集器完成。系统级、目标 cgroup 和 eBPF 数据使用同一正式窗口。

### 6.4 Fleet 类型多应用容量场景

`run_fleet.sh` 使用标准 marker 和 manifest，支持对不同应用并发数量、后台存活率、冷重启次数以及 JVM 应用 heap/RSS 比例进行汇总。

## 7. 输出目录约定

每个有效实验轮次应保留以下内容：

```text
RUN/
  manifest.json
  workload-start.marker
  workload-stop.marker
  policy-state.json
  cache-eviction.json
  reclaim-events.jsonl
  reclaim-events-summary.json
  system/
    before.json
    samples.jsonl
    after.json
    summary.json
    collector-ready.json
    collector-done.json
  cgroup/
    before.json
    samples.jsonl
    after.json
    summary.json
    collector-ready.json
    collector-done.json
```

原始数据不应被覆盖。失败轮次也应保留，以便通过 `invalid_reasons` 审核失效原因，但不得进入正式统计配对。

## 8. 统计输出

`memsched-compare` 对每个指标输出：

- 样本数 N；
- 均值和中位数；
- 样本标准差；
- P90、P95、最小值和最大值；
- Candidate - Baseline 成对差异；
- 成对差异均值的 Bootstrap 95% 置信区间；
- 按“越高越好”或“越低越好”方向计算的改善率。

当 Baseline 均值为 0 时，改善率返回 `null`，不进行除零，也不人为标记为 100%。

## 9. 验证结果

Windows 开发环境执行：

```bash
cd zhj
python -B -m unittest discover -s tests -v
```

结果：

```text
Ran 31 tests
OK
```

已覆盖的关键测试包括：

- marker 原子写入与过期 marker 拒绝；
- before/after 对正式工作负载窗口的包围关系；
- eBPF begin/end 按 TID 配对及跨窗口裁剪；
- AppFlow 冷缓存证据强制检查；
- 环境不一致时拒绝 Baseline/Candidate 配对；
- Bootstrap 统计和改善方向；
- PID 复用与冷热启动判定；
- 策略实际状态核对；
- cgroup 指标缺失时标记无效而非填零；
- Fleet Java heap/RSS 按应用匹配。

由于当前开发机为 Windows，尚未在本机实际执行 Linux 6.17 tracepoint、cgroup v2、systemd transient service 和 debugfs 集成路径。对应入口已经提供，正式采集前必须在 Linux 6.17 测试机完成验收。

## 10. Linux 6.17 部署与验收

```bash
git clone https://github.com/lzx2529129215/huawei_mem.git
cd huawei_mem
git switch --track origin/codex/zhj-measurement-hardening

cd zhj
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

bash scripts/preflight.sh
sudo -E python3 tests/integration/linux617_pipeline.py
python3 -B -m unittest discover -s tests -v
```

正式采集前还应确认：

1. `uname -r` 为 6.17.x；
2. cgroup v2 的 memory、cpu、io controller 可读；
3. bpftrace 可以附加所需 tracepoint，且没有 lost/dropped event；
4. `before < ready <= start < stop <= after <= done`；
5. AppFlow 缓存驻留比例满足阈值；
6. Baseline/Candidate 的环境指纹一致；
7. QQ/WPS 账号、窗口状态、内容和网络条件固定；
8. 无升级弹窗、热降频或其他干扰因素。

## 11. 当前边界与后续工作

本轮已经完成测量框架和数据可信性修复，但以下能力仍属于外部依赖或后续工作：

1. QQ/WPS 的鼠标键盘自动化和页面状态识别；
2. 准确的首个可交互帧事件；
3. 游戏帧时间原始数据采集；
4. JVM/ART/JVMTI GC 工作集探针；
5. 应用对象级重访问埋点；
6. Linux 6.17 真机上的完整多轮 Baseline/Candidate 数据采集；
7. 根据正式实验数据生成最终统计图表。

这些外部数据接入现有 marker、CSV 或 workload event 接口后，可以直接进入统一报告和配对统计流程。

## 12. 合并建议

建议通过 Pull Request 将 `codex/zhj-measurement-hardening` 合并到 `master`，并在合并前完成以下检查：

1. 审核 37 个修改文件；
2. 确认 31 项单元测试通过；
3. 在 Linux 6.17 测试机运行 preflight 和集成测试；
4. 至少运行一轮 QQ/WPS 冒烟采集并检查输出目录完整性；
5. 不使用强制推送覆盖 `master`。
