# Workload → 应用操作：代码交接文档

更新时间：2026-08-08

## 1. 项目目标与准确表述

本项目把一次用户操作诱发的 VMA、Referenced、RSS、PSS、Swap 和 pagemap 状态变化，连同其 before/action/post-action 时间窗口或固定维度向量，统一称为该操作的 **workload**。

因此当前实验目标可以直接表述为：

> **通过聚类算法，根据 workload 的 VMA 内存变化推测用户正在执行的应用操作。**

这里的 workload 是本项目定义的“应用内存 workload”，不是 CPU 利用率、I/O trace、系统调用序列，也不是完整的内核 workload trace。这个限定用于保证术语准确，不改变项目现有命名。

采集方向是：

```text
用户操作 → 应用内存 workload 变化 → VMA / RSS / PSS / Referenced / pagemap 特征
```

分析方向可以反过来理解为：

```text
VMA 内存 workload 特征 → 聚类 → 推断可能的应用操作
```

当前仓库实现的是 workload 采集基础设施和操作级持久性分析；WPS/斗鱼 Windows 核心包进一步实现 workload 向量化、PCA/UMAP 和聚类可分性评估。它们还不是完整的实时操作识别系统。采集程序主要读取鸿蒙设备上的 `/proc/<pid>/maps`、`smaps` 和 `pagemap`。

## 2. 代码职责

### 2.1 `memcap.c`：设备侧内存采集

运行在鸿蒙 PC 的 aarch64 设备上，主要工作包括：

- 解析 `/proc/<pid>/maps`，获取 VMA 地址、权限、文件路径和区域类型；
- 解析 `/proc/<pid>/smaps`，获取 RSS、PSS、Referenced、Anonymous、Swap、Shared/Private 和 Locked 等指标；
- 聚合 `/proc/<pid>/pagemap`，统计 present、swapped、file/shared、exclusive 和 soft-dirty 页；
- 以 VMA 为粒度输出 CSV，避免逐页输出造成数据量爆炸；
- 通过 `sample_id`、`operation_id`、`pid` 和时间戳关联操作与快照。

当前程序不直接读取或声称能够完整读取 page fault、LRU、swap/reclaim 决策、ftrace 或内核调度链路。

### 2.2 `scripts/collect.sh`：单次快照采集

负责主机侧的一次完整采集流程：

1. 根据 PID、进程名或包名查找目标进程；
2. 可选编译并推送 `memcap`；
3. 通过 HDC 在设备侧执行采集；
4. 拉回 `memcap_out/` 下的 CSV；
5. 写入应用、操作和快照元数据。

常用命令：

```bash
source scripts/setup_env.sh
hdc list targets
bash scripts/collect.sh douyu --all
bash scripts/collect.sh 9376 斗鱼 -f foreground -o op_open_room
bash scripts/collect.sh douyu --no-push --out memcap_out/
```

`--all` 用于把应用主进程及匹配到的子进程一起采集。涉及 GPU、渲染或网络子进程的应用，建议先比较单进程和 `--all` 的差异。

### 2.3 `scripts/collect_session.sh`：操作序列编排

该脚本不替代 `collect.sh`，只负责把多个操作和时间阶段编排成一个可复现会话。

默认每个操作采集：

```text
before → after_0s → after_1s → after_3s → after_5s
```

其中：

- `before`：操作前稳定基线；
- `after_0s`：用户完成动作后立即采集；
- `after_1s/3s/5s`：观察短期加载、释放和复用变化。

示例：

```bash
bash scripts/collect_session.sh douyu 斗鱼 session_001 \
  -o launch,enter_room,play_video,background

bash scripts/collect_session.sh douyu 斗鱼 session_002 \
  --phases before,after_0s,after_3s --no-push
```

脚本维护：

- `session_index.csv`：会话级元数据；
- `process_snapshot.csv`：sample、phase、PID 和进程名；
- `operation_list.csv`：由设备侧采集程序追加的操作记录。

### 2.4 `scripts/analyze_operations.py`：操作级持久性分析

该脚本目前不是聚类分类器，而是回答以下问题：

- 哪些 VMA 在多个操作中持续驻留；
- 哪些 VMA 只在某个操作中出现；
- 操作 A 到操作 B 时共享了哪些 VMA；
- 哪些区域属于 KEEP、CONDITIONAL 或 NO 的 profiling 候选。

核心处理：

1. 按 `operation_id` 对快照分组；
2. 通过地址、路径、区域类型和权限构造 VMA 语义匹配键；
3. 对 PID 不变场景进行精确匹配，对跨重启/ASLR 场景使用 fuzzy 匹配；
4. 计算每个 VMA 的操作覆盖率、RSS 趋势和 present ratio；
5. 输出操作转换矩阵和可选的 `future_need_label.csv`。

运行：

```bash
python3 scripts/analyze_operations.py -i memcap_out/
python3 scripts/analyze_operations.py -i memcap_out/ --threshold 0.1 --min-rss 50
python3 scripts/analyze_operations.py -i memcap_out/ --export-labels
```

`KEEP/KILL/CONDITIONAL` 只是内存调度 profiling 候选，不代表已经验证了真实内核回收或页面置换收益。

### 2.5 `scripts/validate_dataset.py`：数据质量检查

在分析前运行，检查：

- 必要 CSV 是否存在；
- `sample_id` 是否能在 snapshot、VMA、pagemap 和 operation 表之间 join；
- 成功采样是否有 VMA 和 pagemap 行；
- 时间戳是否基本单调；
- 采集状态、pagemap 状态和会话元数据是否异常。

运行：

```bash
python3 scripts/validate_dataset.py -i memcap_out/
python3 scripts/validate_dataset.py -i memcap_out/ --session session_001
```

## 3. 与 WPS 2048 维聚类代码的边界

WPS/斗鱼 Windows 核心包中的固定 2048 维 workload 向量构造和 spherical k-means 评估，是在这些采集结果之上的操作反推层：

```text
VMA 报告 → Referenced 页面聚合 → workload 固定维度向量 → PCA/UMAP/聚类 → 操作可分性评估
```

当前 `huawei_mem` 仓库中的 `analyze_operations.py` 是 workload 的 VMA 持久性/转换分析，不等同于这套 2048 维聚类代码。后续若要把聚类算法正式纳入本仓库，应单独增加：

- 向量构造脚本；
- 训练/测试 trial 划分；
- 聚类到操作标签的对齐方法；
- 总体准确率、各操作准确率和混淆矩阵；
- PCA/UMAP 可视化脚本；
- 跨会话、跨设备和未见操作的验证。

## 4. 推荐实验流程

### 阶段 A：准备

1. 确定应用和操作目录；
2. 为每个操作写清前置状态、动作、完成判据；
3. 确定主进程、GPU/渲染/网络子进程是否纳入采集；
4. 确保每次 trial 使用独立输出目录或唯一 `session_id`。

### 阶段 B：smoke

```bash
source scripts/setup_env.sh
hdc list targets
bash scripts/collect_session.sh <target> <app_name> smoke_001 -o op_1
python3 scripts/validate_dataset.py -i memcap_out/
```

只有设备连接、操作记录、VMA、pagemap 和 join 检查均通过，才进入重复采集。

### 阶段 C：正式采集

- 每个应用先做 3 轮稳定性试验；
- 通过后建议做 25–50 轮正式 trial；
- 每个 trial 尽量覆盖完整操作目录；
- 失败 trial 必须保留失败原因，但不要把失败样本静默当作有效样本；
- 原始报告和大体量 CSV 不提交 GitHub，只提交脚本、schema、目录说明和必要的小型示例。

### 阶段 D：分析

1. 运行数据质量校验；
2. 先做 VMA/Referenced/RSS/PSS/pagemap 的操作级分析；
3. 再生成固定维度向量和 PCA/UMAP；
4. 用 trial 分组交叉验证 workload 对操作的可分性；
5. 同时报告总体准确率、各操作准确率、混淆矩阵、样本数和失败 trial 数；
6. 将结果表述为“操作在内存工作集特征上的可识别性”，不要直接表述为实时内核操作识别或调度收益。

## 5. 当前已知限制与风险

1. `pagemap` 读取权限可能导致 PFN 相关信息缺失；
2. pagemap 扫描较慢，不适合捕捉极短瞬态动作；
3. VMA 聚合是区域级证据，不是逐页生命周期和完整 page-fault trace；
4. `Referenced` 可能受基线、后台刷新、网络、GPU 和系统服务噪声影响；
5. PID 变化或 ASLR 会增加 fuzzy 匹配误配/漏配风险；
6. 人工按 Enter 定义操作边界会引入时间误差；
7. 共享库和系统组件可能在多个操作中重复出现，不能直接视为某个操作独占资源；
8. 当前没有在线推理、置信度校准、跨设备泛化和真实调度收益验证。

## 6. 接手后的最小检查清单

```bash
bash -n scripts/collect.sh
bash -n scripts/collect_session.sh
python3 -m py_compile scripts/analyze_memory.py scripts/analyze_operations.py scripts/validate_dataset.py
python3 scripts/validate_dataset.py -i memcap_out/
```

设备实验前确认：

- `source scripts/setup_env.sh` 已执行；
- `hdc list targets` 有且只有目标设备；
- 设备已解锁、常亮并授权 USB 调试；
- 应用包名/进程名已确认；
- 采集目录不是其他任务正在写入的目录；
- 没有将原始采集数据、账号、令牌或设备敏感信息提交到 GitHub。

## 7. 交接结论

本仓库当前提供的是：

```text
应用操作标注
  → HDC 编排
  → 鸿蒙 /proc 内存快照
  → 应用内存 workload：VMA/RSS/PSS/Referenced/pagemap 变化
  → workload 向量化与聚类
  → 推测用户应用操作
```

它已经构成“用户操作—workload—操作反推”的完整实验链路；其中聚类准确率、跨会话泛化和实时推理能力仍需通过独立实验验证。
