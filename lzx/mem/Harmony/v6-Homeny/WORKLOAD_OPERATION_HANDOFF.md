# WPS VMA Workload → 应用操作交接文档

更新时间：2026-08-08

## 1. 项目定义

本项目把一次 WPS 用户操作诱发的 VMA `Referenced` 内存访问变化，以及对应的时间窗口和固定维度向量，称为该操作的 **workload**。

当前实验目标是：

```text
WPS 用户操作
  → clear_refs 后的 VMA Referenced 变化
  → baseline-relative workload 向量
  → PCA / UMAP / spherical k-means
  → 推测用户执行的 WPS 操作
```

因此“workload 反推应用操作”是准确的项目术语。这里的 workload 特指应用内存 workload，不等同于 CPU 利用率、I/O trace、系统调用序列或完整内核 workload trace。

## 2. 代码链路

### 2.1 设备侧：`mem_analyze-v6.c`

v6 采用：

```text
clear_refs → 执行操作 → 读取 smaps → 输出 Referenced/VMA 报告
```

主要读取：

- `/proc/<pid>/clear_refs`：清除之前的 Referenced 标记；
- `/proc/<pid>/smaps`：获取 Size、RSS、PSS、Referenced、Swap；
- `/proc/<pid>/maps`：获取 VMA 地址、权限和路径；
- 可选 `--with-vma`：输出按 VMA 排序的 Referenced 明细。

v6 不读取 pagemap/PFN，也不直接观测 page fault、LRU、swap/reclaim 决策或内核调度 trace。

### 2.2 设备编排：`wps_v6_session.py`

该文件负责：

- 通过 HDC 查找 WPS 主进程及子进程；
- 启动、停止和恢复 WPS；
- 通过 `aa` 和 `uitest` 执行固定 UI 操作；
- 执行 `clear_refs`、等待操作完成并拉回报告；
- 保存每个阶段的操作耗时、稳定等待、采集耗时、PID 和报告哈希；
- 将文档保存到带时间戳的统一实验目录：

```text
/storage/media/100/local/files/Docs/WPS_VMA_Experiments/WPS_VMA_Experiment_<session>/WPS_VMA_<session>.docx
```

Windows 侧 `HDC` 输出按 UTF-8 解码并使用 `errors="replace"`，避免中文环境默认 GBK 导致 `UnicodeDecodeError`。

### 2.3 标签采集：`run_wps_operation_dataset.py`

每个操作严格执行：

```text
BASELINE_01 → BASELINE_02 → ACTION → POST_ACTION
```

其中：

- baseline：操作前稳定状态，调用 `clear_refs` 后采集；
- action：执行目标用户操作后的观察窗口；
- post-action：短暂稳定等待后的观察窗口。

每个 trial 串行覆盖 `wps_operation_catalog.json` 中的 18 类 WPS Writer 操作，成功样本写入 `operation_window_sequences.jsonl`，失败 trial 写入失败记录。

数据集 runner 默认使用 `formal` 采集；显式传入 `--mode fast` 时，只替换 VMA 报告传输路径：设备侧通过 `mem_analyze-v6 --compact-vma` 将保留 FILE/ANON、pathname、segment、perms 和 Referenced pages 的 TSV 直接写到 stdout，主机侧直接聚合，不生成 Markdown、不做逐报告 `sha256sum`、`recv` 或 Markdown 解析。5s/15s/5s 窗口、baseline/action/post-action 结构和 2048 维特征定义不变。fast 窗口同时记录各阶段耗时，便于比较扫描本身与文件传输开销。

运行示例：

```powershell
cd lzx\mem\Harmony\v6-Homeny
python -m py_compile wps_v6_session.py run_wps_operation_dataset.py build_wps_vma_dataset.py
.\run_wps_operation_dataset.ps1 -Target <HDC_SERIAL> -Trials 1 -NoBuild
.\run_wps_operation_dataset.ps1 -Target <HDC_SERIAL> -Trials 25 -NoBuild
```

正式采集前必须先确认 `trial_001: success`，并检查输出目录中存在完整的 18 个操作样本。

### 2.4 向量构造：`build_wps_vma_dataset.py`

该文件把 VMA 报告转换为 workload 向量：

1. 按 FILE/ANON namespace 和语义键聚合 Referenced pages；
2. 对 baseline 多窗口取中位数；
3. 计算 ACTION/POST_ACTION 相对 baseline 的非负增量；
4. 取两个操作窗口的最大增量作为操作 workload 特征；
5. 通过确定性 SHA-256 feature hashing 生成 2048 维向量：

```text
0–1023：FILE VMA 特征
1024–2047：ANON VMA 特征
```

PID、绝对 VMA 地址、时间戳、trial/session/sample 标识和操作标签不进入 2048 维特征，保留在元数据中。

主要输出：

- `dataset_manifest.csv`：样本质量和元数据；
- `labels.csv`：操作标签；
- `vma_features_long.csv`：长表特征；
- `vma_vectors_raw.csv`：log1p 后的原始向量；
- `vma_vectors_l2.csv`：L2 归一化向量，作为聚类主输入；
- `pairwise_similarity.csv`：样本相似度和同类/异类对照；
- `dataset_analysis.md`：数据集统计和质量摘要。

### 2.5 PCA/UMAP/聚类评估

Windows 侧使用 `vma_vectors_l2.csv` 和 `labels.csv` 做：

- PCA 二维投影；
- UMAP 二维投影；
- spherical k-means 等聚类；
- trial 分组交叉验证；
- 总体准确率、各操作准确率、混淆矩阵和可视化。

聚类阶段的反推方向是：

```text
未知 workload 向量 → 所属聚类 → 对应的 WPS 操作
```

采集阶段的真实操作标签只用于建立训练/评估对照，不能在推理时作为输入泄漏给模型。

## 3. 当前 18 类操作

```text
NEW_DOCUMENT, WRITE_TEXT, SELECT_ALL, COPY_SELECTION,
PASTE_SELECTION, CUT_SELECTION, UNDO_EDIT, REDO_EDIT,
FIND_TEXT, REPLACE_TEXT, INSERT_PAGE_BREAK, INSERT_TABLE,
FORMAT_BOLD, FORMAT_ITALIC, FORMAT_UNDERLINE, ALIGN_CENTER,
SAVE_DOCUMENT, CLOSE_DOCUMENT
```

这是当前稳定自动化子集，不声称覆盖 WPS 全部菜单、云服务和第三方插件功能。

## 4. 运行和验收流程

### Smoke

```powershell
Set-ExecutionPolicy -Scope Process Bypass
hdc list targets
.\preflight_wps_dataset.ps1
.\run_wps_operation_dataset.ps1 -Target <HDC_SERIAL> -Trials 1 -NoBuild
```

验收条件：

- HDC 只看到目标设备；
- 设备已解锁、常亮并授权 USB 调试；
- 每个操作的 baseline/action/post-action 报告齐全；
- 没有重复文件覆盖；
- `dataset_manifest.csv` 质量字段通过；
- `trial_001` 为 `success`。

### 正式采集

```powershell
.\run_wps_operation_dataset.ps1 -Target <HDC_SERIAL> -Trials 25 -NoBuild
```

默认保留核心数据集，不保留原始 VMA 报告；调试失败时才使用 `-KeepRaw`。原始数据、PPT、聚类结果和大体量输出不应提交 GitHub。

## 5. 术语和结论边界

可以说：

> VMA 内存 workload 对部分 WPS 操作具有可识别性，聚类结果可以用于评估操作间的内存特征差异。

暂时不能说：

- 已经实现实时用户操作识别；
- 已经观测完整内核 workload；
- 已经证明 page replacement、reclaim、prefetch 或调度收益；
- 聚类准确率可以跨设备、跨版本直接复用。

后续要成为实时反推系统，还需要在线滑动窗口、推理延迟、置信度校准、未见 session/设备验证和真实操作流测试。

## 6. 接手检查清单

```powershell
python -m py_compile wps_v6_session.py run_wps_operation_dataset.py build_wps_vma_dataset.py
python run_wps_operation_dataset.py --help
hdc list targets
```

接手者首先阅读本文件、`README.md`、`wps_operation_catalog.json`，然后只做 1 轮 smoke；不要直接运行长期采集，也不要把原始 40GB 级目录复制进 Git。
