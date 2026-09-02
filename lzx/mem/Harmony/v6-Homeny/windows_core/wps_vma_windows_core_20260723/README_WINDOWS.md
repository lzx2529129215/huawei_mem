# 鸿蒙 WPS VMA 采集离线包

这个目录是给长期连接鸿蒙 PC 的 Windows 主机使用的精简运行包。Windows 端不需要 Git、不需要仓库、不需要编译代码，只负责通过 USB/HDC 运行采集。

## 包含内容

- `run_wps_operation_dataset.py`：串行执行 WPS 操作并采集 VMA；
- `run_wps_operation_dataset.ps1`：Windows PowerShell 入口；
- `wps_v6_session.py`：鸿蒙设备启动、UI 操作、VMA 报告拉回与校验；
- `build_wps_vma_dataset.py`：将原始报告汇总为带标签 CSV 和 2048 维向量；
- `wps_operation_catalog.json`：18 类 WPS Writer 操作目录；
- `mem_analyze-v6.c`：设备侧采集器源码，支持 formal Markdown 和 fast compact TSV 两种输出；
- `mem_analyze-v6-ohos`：已编译的鸿蒙 ARM64 设备侧采集器，Windows 只需推送，不执行它。

## Windows 端一次性准备

1. 安装 Python 3.10 或更高版本，并确认 `python --version` 可用。
2. 安装 OpenHarmony/DevEco Studio 对应的 `hdc.exe`，将其所在目录加入 PATH；或者在 PowerShell 中设置 `HDC` 为 `hdc.exe` 完整路径（也兼容设置为其所在目录）：

   ```powershell
   $env:HDC = "C:\路径\到\hdc.exe"
   ```

3. 保持鸿蒙 PC 解锁、屏幕常亮、USB 调试开启，然后检查：

   ```powershell
   hdc list targets
   hdc shell "id"
   ```

   需要能看到设备序列号，并建议确认 `id` 具有 root 权限；否则无法写入 `/proc/<pid>/clear_refs`。

## 运行方式

在本目录打开 PowerShell：

```powershell
Set-Location "C:\你的路径\wps_vma_windows_core_20260723"

# 先做 1 个 trial 烟测：18 组操作—VMA 样本
.\run_wps_operation_dataset.ps1 -Target <hdc设备序列号> -Trials 1 -NoBuild

# 正式采集：6 个 trial，共 108 组带标签样本
.\run_wps_operation_dataset.ps1 -Target <hdc设备序列号> -Trials 6 -NoBuild

# fast 采集：仅替换 VMA 报告传输格式，观察窗口和 2048 维特征不变
.\run_wps_operation_dataset.ps1 -Mode fast -Target <hdc设备序列号> -Trials 1 -NoBuild
```

每个 trial 依次执行 18 类 WPS Writer 操作；每个操作采集 2 个 baseline、1 个 ACTION 和 1 个 POST_ACTION 窗口。默认输出目录为本目录下的 `hdc_out\wps_operation_dataset_<时间戳>`，也可以显式指定：

首次保存的 Word 文档会使用当前 trial 的时间戳唯一文件名，并统一归档到鸿蒙 PC 的用户文档目录 `/storage/media/100/local/files/Docs/WPS_VMA_Experiments/<session_timestamp>/`，不占用 Desktop，避免与历史 WPS 文件重名。

```powershell
.\run_wps_operation_dataset.ps1 `
  -Target <hdc设备序列号> `
  -Trials 6 `
  -NoBuild `
  -Out "D:\wps_vma_data\run_001"
```

`-NoBuild` 是 Windows 长期采集必选项：包内已经带有设备侧 ARM64 采集器，不在 Windows 上交叉编译。

## 输出与检查

重点文件：

- `dataset_manifest.csv`：样本、标签、窗口和质量字段；
- `labels.csv`：操作标签映射；
- `vma_features_long.csv`：FILE/ANON 语义特征；
- `vma_vectors_raw.csv`、`vma_vectors_l2.csv`：2048 维向量；
- `dataset_summary.json`：样本数、类别数、哈希不一致和零向量统计；
- `dataset_analysis.md`：数据质量与类别分析；
- `trial_XXX\`：每轮原始 VMA Markdown 报告和试验元数据。

formal 模式会保留 Markdown、逐报告 SHA-256 和 HDC `recv`。fast 模式调用 `mem_analyze-v6 --compact-vma`，通过一次 HDC shell 返回 TSV，主机侧直接聚合 FILE/ANON、pathname、segment、perms 和 Referenced pages；默认不落盘原始流，需要调试时增加 `-FastKeepRaw`。

## 注意事项

- 18 类是当前鸿蒙设备/WPS Writer 版本下的稳定自动化子集，不宣称覆盖云文档、打印、插件以及 WPS 表格/演示的全部功能。
- 不要把 `hdc_out` 原始数据复制回代码包或提交 Git；单个 trial 可能占用约 1 GB，正式 6 trial 建议预留至少 10 GB 磁盘空间。
- 如果 WPS 版本、窗口缩放或屏幕分辨率改变，固定坐标操作可能需要在 Mac 端重新校准后再生成新包。
