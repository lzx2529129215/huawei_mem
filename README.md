# huawei_mem — 鸿蒙内存分析与 Linux 页面缓存优化

围绕鸿蒙 PC 内存采集分析和 Linux 内核页面缓存优化的多模块研究仓库，涵盖设备端内存快照、桌面应用自动化、运行时监控、eBPF 页面缓存策略、操作预测建模和 MGLRU 内核改进。

## 项目总览

```
huawei_mem/
├── memcap.c                              # 设备端 C 采集程序（C11）
├── analyze_memory.py                     # 跨快照对比分析
├── lzx/                                  # 龙子翔 — 主开发
│   ├── mem/Harmony/v6-Homeny/            # WPS v6 hdc Referenced 采集 + workload 向量
│   ├── automation/                       # Linux 桌面应用自动化（xdotool）
│   ├── runtime_monitor/                  # PC runtime 数据采集器 v0
│   ├── cache_ext/                        # eBPF 页面缓存逐出策略（SOSP 2025）
│   ├── operation_predictor/              # 应用/操作预测建模（Markov/GAM/SCNN/MOGP）
│   ├── mem/Linux/                        # Linux 侧内存分析（v3-v8: page_idle, 内核模块）
│   ├── design/                           # 设计文档（Markov 架构、Hint 计数等）
│   ├── configs/                          # 场景和应用配置文件
│   ├── doc/                              # 版本说明文档
│   ├── MGLRU-test/                       # MGLRU 内核构建归档（v0-v4）
│   └── outputs/                          # 实验输出
├── zb/                                   # MYYU-notice — MGLRU + cache_ext 内核
│   ├── MGLRU/                            # MGLRU 页控制 + eBPF Markov 预测内核补丁
│   └── operation_predictor/              # 操作预测（副本）
├── ljw/TRACER/                           # wency — eBPF Page Cache 事件追踪器
├── xty/mglru_kernel_transfer_0705/       # MGLRU 二级水位线 Per-Cgroup 改进
├── wzx/automation-wps/                   # WPS 自动化（旧版）
├── zhj/                                  # 占位
└── docs/                                 # 实验报告与文档
```

## 各模块详情

### 1. memcap — 鸿蒙 PC 应用内存页快照采集

通过 hdc 连接鸿蒙 PC 设备，对目标进程做单次内存页快照采集（maps + smaps + pagemap），输出 6 张 CSV 供跨快照对比分析。

- **数据链路**：`/proc` 内核接口 → memcap (C, aarch64) → CSV → analyze_memory.py → 报告
- **对比模式**：exact（同 PID 地址匹配）/ fuzzy（跨 PID 语义匹配）
- **输出分类**：Hot（持久化 ≥90%）/ Dynamic（间歇）/ Cold（虚拟预留）

```bash
source scripts/device/setup_env.sh
bash scripts/device/collect.sh douyu
python3 scripts/analysis/analyze_memory.py -i memcap_out/ --pid 9376
```

详见 `CLAUDE.md` 中的完整快速开始指南。

### 2. WPS v6 鸿蒙 Referenced 采集 (`lzx/mem/Harmony/v6-Homeny/`)

基于 `clear_refs → 操作 → smaps/Referenced` 链路的鸿蒙 PC 内存观察窗口采集，支持 WPS 自动化场景和重复 workload 向量实验。

- **核心文件**：`wps_v6_session.py`（55KB，WPS 会话管理）、`mem_analyze-v6.c`（设备端采集）
- **WPS 自动化**：一键脚本 `run_wps_v6.sh`，覆盖打开→新建→写入→保存→后台→重开→关闭全流程
- **Workload 向量**：`build_workload_feature_vector.py` 为每个操作生成 56 维特征向量，支持重复实验稳定性分析

```bash
# WPS 自动化采集
./lzx/mem/Harmony/v6-Homeny/run_wps_v6.sh

# 重复 workload 向量实验（3 轮）
./lzx/mem/Harmony/v6-Homeny/run_wps_workload.sh --repeats 3
```

### 3. Linux 桌面应用自动化 (`lzx/automation/`)

基于 xdotool 的 Linux X11 桌面自动化框架，支持 WPS/QQ/Firefox/Files 等应用的启动、点击、按键、输入、拖拽和关闭。配合 `runtime_monitor` 生成标注数据。

- 场景配置：JSON 文件定义 action 序列（launch/wait/focus/key/click/close/shell）
- 支持 Wayland + Xwayland 混合环境、Snap Firefox systemd-run 注入
- 可与 `runtime_monitor` 对齐生成 `automation_trace.csv` → `features_1s.labeled.csv`

```bash
cd lzx
automation/run_automation.sh --scenario configs/automation/scenario_local_files.json
```

### 4. Runtime Monitor v0 (`lzx/runtime_monitor/`)

PC runtime 数据采集器，基于 procfs/cgroup v2 做 1 秒粒度特征采集，不依赖 eBPF。

- **输出**：`events.csv`（文件事件）、`app_events.csv`（应用生命周期/窗口状态）、`features_1s.csv`（全局特征窗口）、`app_features_1s.csv`（应用级特征）
- **前台检测**：X11 `_NET_ACTIVE_WINDOW`，Wayland 降级为 manual
- **路径隐私**：raw / hash / basename 三种模式

```bash
cd lzx
python3 runtime_monitor/monitor.py \
  --config configs/runtime/config.yaml \
  --target-apps WPS,QQ,FILES \
  --sample-interval 1 \
  --path-mode hash
```

### 5. cache_ext — eBPF 页面缓存逐出策略 (`lzx/cache_ext/`)

SOSP 2025 论文 [cache_ext](https://dl.acm.org/doi/10.1145/3731569.3764820) 的 artifact 仓库，支持用 eBPF 自定义 Linux 页面缓存逐出策略。

- 基于 Linux v6.6.8 修改内核，含 libbpf/bpftool 适配
- 实验场景：YCSB、File Search、CPU Overhead、Isolation (per-cgroup)、Twitter Trace
- 包含 LevelDB 修改版和 My-YCSB C++ 基准测试框架

### 6. MGLRU 内核改进

#### zb/MGLRU — 页控制 + eBPF Markov 预测

基于 Linux 6.17 的内核补丁，在 MGLRU 回收流程中嵌入 cache_ext：

- MGLRU 扫描周期开始时调用 eBPF Markov 预测 `next_op`
- Aging/Isolation 路径匹配 `app_id + op + dev + ino + index`，命中则 promote 或跳过回收
- 补丁：`merged_cache_ext.patch`（`mm/vmscan.c`, `mm/cache_ext.c` 等）

#### xty/mglru_kernel_transfer_0705 — 二级水位线 Per-Cgroup

基于 Linux 6.17.13 的 MGLRU 改进：

- Node-level 和 Per-Cgroup 二级水位线（tier2_watermark）
- Cgroup v2 接口：`memory.tier2_enabled/alloc_scale/demote_scale`
- Workqueue 异步回收 + MGLRU 代际感知 + 全局 vmstat 计数器

### 7. eBPF Page Cache Tracer (`ljw/TRACER/`)

基于 eBPF (BCC) 的页面缓存事件追踪器，捕获 ACCESS/INSERT/EVICT/OP_DONE 事件：

- `tracer.py`：Kprobe 挂载，输出二进制 raw trace
- `parser.py`：离线解析，生成 `aligned_trace_features.csv`（ML 特征）和 `operation_to_pages.json`（映射表）
- 特征：page_time_delta、seq_distance、inode_hotness_ema 等

### 8. 操作预测建模 (`lzx/operation_predictor/` + `zb/operation_predictor/`)

应用/操作预测实验框架，包含数据生成流水线和多模型对比：

- **数据**：角色化合成数据（学生/程序员/工程师/网红等 9 种用户群体），按会话阶段生成操作序列
- **模型**：Markov baseline（1-4 阶）、参数化回归、GAM、神经分位数回归、SCNN、MOGP
- **评估**：Top-K Accuracy、MRR

```bash
cd lzx/operation_predictor
python src/train/train_op_markov.py --train data/processed/train_op.pkl ...
```

### 9. Linux 内存分析版本演进 (`lzx/mem/Linux/`)

Linux 侧页面级内存访问追踪的版本迭代（v3-v8），从 PFN delta 分析演进到内核模块直接操作 PTE：

- **v3/v4**：早期 PFN delta 分段分析
- **v6**：Linux 等效版 `clear_refs` + `smaps` Referenced 方案
- **v7**：`/proc/<pid>/pagemap` + `/sys/kernel/mm/page_idle/bitmap`，mark-idle → 操作 → 查询，精确定位操作窗口内访问的物理页
- **v8**：自定义内核模块 `/dev/v8_page_access`，直接清空/查询 PTE/PMD Young 位，不依赖 PFN 可见性

### 10. DAMON Region Monitor (`lzx/runtime_monitor/region_monitor/`)

Observe-only 的 cgroup + DAMON 区域追踪组件，将 DAMON 动态虚拟地址区间映射到稳定区域键：

- 文件页：`dev+major+minor+inode+offset_bucket+perms`
- 匿名页：`type+name+size_bucket+relative_offset_bucket`
- 预留对接 automation trace 做操作识别器训练

### 11. 语义化自动化框架 (`lzx/automation/semantic/`)

高层语义自动化，定义可复用的操作、场景、窗口配置文件和素材，编译到 `trace_marker` 与 runtime monitor 时间区间对齐。包含安全门禁防止破坏性操作（真实消息发送、发布、关注等）。

### 12. MGLRU 内核构建归档 (`lzx/MGLRU-test/`)

版本化 MGLRU 内核源码构建快照（v0-v4）：

- **v0**：基线 `6.17.13-mglru`
- **v4**（当前）：`6.17.13-mglru-dual-observe-bindfix`，含完整自包含源码包

### 13. 设计文档 (`lzx/design/`)

- `current_markov_architecture.md`：双模式 Markov 架构（CONTINUE/REENTRY），debugfs ABI
- `双模式Markov完整修复说明.md`：CONTINUE 模式（同前台 epoch 内 2 阶 workload 转移）+ REENTRY 模式（回前台首次 workload 预测）
- `AppBind表修复说明.md`：32 槽位 bind 表满时过期槽位复用修复
- `Hint计数语义说明.md`：CONTINUE/REENTRY hint 四计数器语义、去重逻辑、REENTRY 综合强度公式

## 实验环境

| 环境 | 配置 |
|------|------|
| 鸿蒙设备 | HUAWEI MateBook Pro HAD-W32, HongMeng Kernel 1.12.0, aarch64 |
| Linux 内核 | 6.17.13 / 6.17.0-cacheext-v2 (自定义) |
| 主机 | Ubuntu 22.04 / macOS / Windows |
| 连接工具 | hdc (鸿蒙) / SSH (Linux) |
| eBPF 工具链 | BCC / libbpf / bpftool |

## 协作者

- **龙子翔 (lzx)** — 鸿蒙内存采集、自动化、runtime monitor、操作预测
- **MYYU-notice (zb)** — MGLRU + cache_ext 内核补丁、操作预测
- **wency (ljw)** — eBPF Page Cache Tracer
- **xty** — MGLRU 二级水位线 Per-Cgroup
- **cvue (zhairui1995)** — WPS v6 workload vector automation
- **wzx** — WPS 自动化（旧版）
- **zhj** — 占位

## 引用

如果使用 cache_ext，请引用：

```bibtex
@inproceedings{cacheext,
  author = {Zussman, Tal and Zarkadas, Ioannis and Carin, Jeremy and Cheng, Andrew and Franke, Hubertus and Pfefferle, Jonas and Cidon, Asaf},
  title = {cache_ext: Customizing the Page Cache with eBPF},
  year = {2025},
  publisher = {Association for Computing Machinery},
  doi = {10.1145/3731569.3764820},
  series = {SOSP '25}
}
```
