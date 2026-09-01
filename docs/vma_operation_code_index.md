# VMA 反推操作代码索引

本文是给接手代码的同事看的索引。当前同步的是采集、向量构造和导出代码，不包含原始 VMA 报告、日志、截图、PPT 或大体量数据。

## 仓库和分支

- 仓库：`lzx2529129215/huawei_mem`
- 当前同步分支：`feature/wps-operation-vma-dataset`
- 设备侧和 WPS 流程说明：`lzx/mem/Harmony/v6-Homeny/WORKLOAD_OPERATION_HANDOFF.md`

## WPS Writer

已有的主流程代码在 `lzx/mem/Harmony/v6-Homeny/`：

- `mem_analyze-v6.c` / `mem_analyze-v6-ohos`：设备侧读取 `/proc/<pid>/maps`、`smaps`，在 `clear_refs` 后输出 VMA 的 Size、RSS、PSS、Referenced、Swap 等字段。
- `wps_v6_session.py`：通过 HDC 找 WPS 进程、执行 UI 操作、采集 baseline/action/post-action 报告。
- `run_wps_operation_dataset.py`、`run_wps_operation_dataset.ps1`：按操作目录串行采集带标签样本。
- `build_wps_vma_dataset.py`：把 VMA 报告聚合为固定 2048 维 workload 向量；0–1023 为 FILE 特征，1024–2047 为 ANON 特征，使用确定性 SHA-256 hashing 和 L2 归一化。
- `wps_operation_catalog.json`：当前 WPS 操作标签目录。

从 Windows 整理过的可直接运行包放在：

`lzx/mem/Harmony/v6-Homeny/windows_core/wps_vma_windows_core_20260723/`

其中的 `export_wps_vma_dataset_core.py` 用于导出核心数据文件，PowerShell 文件用于 Windows/HDC 编排。

## 斗鱼

Windows 侧 VMA 采集和数据构造包放在：

`lzx/mem/Harmony/v6-Homeny/windows_core/douyu_vma_windows_core_20260731/`

关键文件与 WPS 对应：`douyu_v6_session.py`（采集编排）、`run_douyu_operation_dataset.py`（带标签采集）、`build_douyu_vma_dataset.py`（向量构造）、`export_douyu_vma_dataset_core.py`（核心数据导出）、`douyu_operation_catalog*.json`（操作目录）。历史 HYPium 自动化入口仍在 `hypium/testcases/DouyuUserJourney.py` 和 `scripts/run_douyu_hypium.sh`。

## 从采集到反推

```text
用户操作
  → clear_refs
  → baseline / action / post-action VMA 报告
  → Referenced 增量和 VMA 语义键聚合
  → 2048 维 workload 向量
  → PCA / UMAP 可视化、聚类和操作标签对照
```

代码会产生的核心数据文件通常是：`dataset_manifest.csv`、`labels.csv`、`vma_features_long.csv`、`vma_vectors_raw.csv`、`vma_vectors_l2.csv`、`pairwise_similarity.csv` 和 `dataset_analysis.md`。这些文件应留在 Windows 采集目录或单独的数据存储中，不要提交到 Git。

## 聚类代码的边界

当前仓库里没有找到独立的 spherical k-means、PCA/UMAP 训练和 5 折 trial 评估脚本；`build_*_vma_dataset.py` 负责生成聚类输入，`scripts/analyze_operations.py` 主要做持久性/转移分析，并不是 2048 维聚类实现。此前的聚类图和准确率结果来自 Windows 侧分析流程，后续如果要复现实验，建议补一个单独的 `analysis/` 目录，把数据切分、聚类标签对齐、Accuracy/Macro-F1、混淆矩阵和 PCA/UMAP 脚本一并纳入版本管理。

## 数据位置说明

设备采集输出一般在各运行目录的 `hdc_out/` 下，正式数据的核心是上面列出的 CSV/JSON 摘要；`referenced_*.md`、`operation_window_*_vma_samples.jsonl`、HDC 日志和截图属于原始证据，体积很大，不是训练时的最小输入。当前没有一个统一的 `.db` 文件，主要是 CSV、JSONL 和 Markdown 文件。
