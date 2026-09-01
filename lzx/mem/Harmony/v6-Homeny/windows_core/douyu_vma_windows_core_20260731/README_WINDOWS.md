# 斗鱼鸿蒙 PC 操作—VMA 核心数据集（Windows）

这是一套可直接复制到 Windows 的独立脚本包。Windows 只负责连接鸿蒙 PC、执行斗鱼操作和生成核心子数据集，不需要在 Windows 上开发代码。

## 当前正式采集的 8 类操作

~~~text
SEARCH_LIVE_ROOM
ENTER_LIVE_ROOM
PLAY_PAUSE_VIDEO
BACK_TO_HOME
BACKGROUND_APP
RESTORE_APP
RESTART_APP
SWITCH_LIVE_ROOM
~~~

每个操作都按 BASELINE → ACTION → POST_ACTION 采集，使用斗鱼主进程和相关子进程的 VMA referenced 页面生成固定 2048 维向量。

`douyu_operation_catalog_all.json` 保留 11 个候选操作，便于审计和后续补采；正式脚本默认只读取 `douyu_operation_catalog.json` 的 8 个 active 操作。

基于 WPS 的先验结果，先排除三类容易出现弱稳定 VMA 信号的操作：`SWITCH_VIDEO_TAB`、`SWITCH_CHAT_TAB`、`SCROLL_LIVE_ROOM`。它们分别更接近页签切换、聊天界面切换和高频滚动，和 WPS 中 `FIND_TEXT`、`PASTE_SELECTION` 一样，可能主要改变短暂 UI 状态，未必形成稳定的进程级 VMA 增量。`PLAY_PAUSE_VIDEO` 暂时保留，因为视频播放/暂停可能触发解码或渲染资源变化，必须通过实测决定。

## Windows 使用步骤

1. 将本目录复制到固定目录，例如 D:\git-code\douyu_vma_windows_core_20260731。
2. 确认鸿蒙 PC 已解锁、保持常亮、USB 调试已授权，PowerShell 进入目录：

~~~powershell
cd D:\git-code\douyu_vma_windows_core_20260731
Set-ExecutionPolicy -Scope Process Bypass
~~~

3. 运行 preflight：

~~~powershell
.\preflight_douyu_dataset.ps1
~~~

4. 先运行一轮 smoke。设备侧已有采集器时使用 NoBuild：

~~~powershell
.\run_douyu_operation_dataset.ps1 -Target <DEVICE_SERIAL> -Trials 1 -NoBuild -Out "D:\douyu_vma_runs\douyu_smoke_<timestamp>"
~~~

只有看到 trial_001: success，才进入正式采集。

5. 正式采集建议先运行 25 轮：

~~~powershell
.\run_douyu_operation_dataset.ps1 -Target <DEVICE_SERIAL> -Trials 25 -NoBuild -Out "D:\douyu_vma_runs\douyu_formal_<timestamp>"
~~~

## 输出结果

脚本完成后，运行目录中直接得到：

~~~text
douyu_vma_dataset_core_<timestamp>\
  README.md
  core_summary.json
  dataset_summary.json
  dataset_manifest.csv
  labels.csv
  trial_selection.csv
  excluded_samples.csv
  trial_failures.csv
  operation_catalog.json
  vma_vectors_raw.csv
  vma_vectors_l2.csv
  vma_features_long.csv

douyu_vma_dataset_core_<timestamp>.zip
run_summary.json
~~~

核心目录和 ZIP 不包含原始 VMA Markdown 报告、设备临时文件、截图和完整日志。默认脚本在成功导出核心子数据集后清理临时采集目录；调试时可增加 --KeepRaw 保留原始报告。

## 重要参数

- Trials 1：smoke。
- Trials 25：第一批正式采集，8 个操作约 200 个有效样本。
- NoBuild：复用包内的 mem_analyze-v6-ohos，适合 Windows 长期采集。
- KeepRaw：仅调试时使用，保留原始 VMA 报告。
- --search-term pubg：设置第一次搜索关键词。
- --second-search-term music：设置切换直播间时的第二个关键词。
- --screen-width 3120 --screen-height 2080：设备分辨率不是默认值时覆盖。

## 失败处理

以下情况不要直接扩大轮数：

- smoke 失败；
- 设备离线或 hdc 输出为空；
- 斗鱼没有启动；
- 搜索结果或直播间点击位置不适配当前 UI；
- 某个 trial 产生空向量或报告 hash 不一致；
- 8 个 active 操作没有全部完成。

脚本会把失败 trial 写入 trial_failures.csv，完整 trial 才会进入核心子数据集。首次在设备上运行时，建议先 Trials 1 观察界面坐标是否与当前斗鱼版本一致。

## 数据说明

- vma_vectors_l2.csv 是后续 PCA、UMAP 和聚类的主输入；
- labels.csv 保存操作标签；
- dataset_manifest.csv 保存 trial、设备和样本质量字段；
- trial_selection.csv 记录完整 trial 筛选；
- excluded_samples.csv 记录未进入核心子数据集的原因；
- vma_vectors_raw.csv 是经 log1p 后的固定向量，不是原始设备快照。

## 操作筛选原则

当前只根据 WPS 的历史经验，在正式采集前剔除三个预判难以稳定识别的操作；不会根据聚类结果自动删除操作。斗鱼完成采集后，所有 8 个 active 操作都保留在数据集和分析中，再根据 PCA、UMAP、混淆矩阵和各操作准确率人工决定是否补采、调整动作或重新设计特征。
