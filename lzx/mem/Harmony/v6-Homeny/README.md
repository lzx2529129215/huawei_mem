# mem_analyze v6：鸿蒙 hdc Referenced 采集流程

v6 只关注一条采集链路：

```text
clear_refs -> 执行目标操作 -> 读取 smaps -> 生成 Referenced 报告
```

`Referenced(KiB)` 来自 `/proc/<pid>/smaps`。它只表示从清空 `/proc/<pid>/clear_refs` 到读取 `smaps` 这段观察窗口内，被访问过的驻留页规模。

注意：v6 不做 pagemap、PFN、page_idle 级别的逐页追踪；这部分仍然属于 v7 的方向。

## 环境要求

- 鸿蒙/OpenHarmony 设备已通过 `hdc` 连接。
- `hdc shell` 需要有权限写 `/proc/<pid>/clear_refs`，并读取 `/proc/<pid>/smaps`。
- 如果不是复用已编译好的 `mem_analyze-v6-ohos`，本机需要安装 OpenHarmony native SDK。

快速检查设备连接和权限：

```powershell
hdc list targets
hdc shell "id; ls -l /proc/self/smaps /proc/self/clear_refs"
```

当前测试设备上，`hdc shell` 默认是 `root`，因此可以直接使用 `clear_refs` 和 `smaps`。

## Windows PowerShell 用法

推荐入口：

```powershell
.\lzx-Test1\v6-Homeny\collect_hdc_v6.ps1 -Target com.example.app -WithVma
```

按 PID 采集：

```powershell
.\lzx-Test1\v6-Homeny\collect_hdc_v6.ps1 -Target 12345
```

首次部署后，如果设备侧二进制没有变化，可以跳过编译和推送：

```powershell
.\lzx-Test1\v6-Homeny\collect_hdc_v6.ps1 -Target com.example.app -NoBuild -NoPush
```

如果希望脚本在 `clear_refs` 之后自动触发某个操作，可以传入本机命令。这个命令也可以继续调用 `hdc`：

```powershell
.\lzx-Test1\v6-Homeny\collect_hdc_v6.ps1 -Target com.example.app `
  -OperationCommand "hdc shell `"aa start -a EntryAbility -b com.example.app`""
```

如果不传 `-OperationCommand`，脚本会在清空 `Referenced` 标记后暂停。你需要在设备上手动执行要观察的操作，然后回到终端按 Enter，脚本会立即读取 `smaps`。

## Bash 用法

Bash 入口与 PowerShell 脚本功能一致：

```bash
bash lzx-Test1/v6-Homeny/collect_hdc_v6.sh com.example.app --with-vma
bash lzx-Test1/v6-Homeny/collect_hdc_v6.sh 12345
bash lzx-Test1/v6-Homeny/collect_hdc_v6.sh com.example.app --no-build --no-push
```

### WPS 鸿蒙 PC 自动化采集

远端 `lzx/automation/app_automation.py` 面向 Linux X11，使用 `xdotool`，不能直接控制当前通过 HDC 连接的鸿蒙 PC。当前设备使用 `aa` + `uitest`，推荐使用新的会话入口：

```bash
bash lzx/mem/Harmony/v6-Homeny/collect_wps_v6.sh \
  --session-id wps_$(date +%Y%m%d_%H%M%S)
```

单命令入口（自动启动 WPS 自动化、编译/推送 `mem_analyze-v6`、逐阶段采集全部 WPS PID、拉回并校验报告）：

```bash
./lzx/mem/Harmony/v6-Homeny/run_wps_v6.sh
```

默认设备为 `3QC0124C03000514`，固定写入 Word 的测试序列号为 `WPS-TEST-0001`；可用 `--test-serial` 覆盖。脚本不依赖人工查看图片，截图仅作为自动失败证据保存。

WPS 报告先写入设备侧 `/data/local/tmp/mem_analyze_v6/wps_reports`，每个阶段完成后立即通过 HDC 拉回主机，避免不同 HarmonyOS 版本的媒体目录权限/挂载差异。

该入口会执行并逐阶段记录：

1. 打开 WPS，启动完成后采集空闲窗口；
2. 通过 WPS 新建菜单创建 Word；
3. 写入固定测试序列号、本次时间、目的、操作链和初步结论；
4. 写入较大文本并执行换行、翻页、滚动和光标移动；
5. 保存到 Desktop，验证真实文件路径/大小/修改时间；
6. Home 切后台，再启动 WPS 切回前台；
7. 关闭、重新打开已保存文档，执行少量编辑/滚动后最终关闭 WPS。

每个可测阶段都执行 `clear_refs -> 操作 -> 等待 -> smaps/Referenced`，输出目录包含 `referenced_<stage>*pid*<pid>.md`、`operations.csv`、`memory_summary.csv`、`experiment_summary.md`、`report_hashes.csv` 和 `session_metadata.json`。`operations.csv` 同时记录操作耗时、稳定等待、采集耗时、报告拉回耗时、阶段总耗时、PID 集合和逐阶段报告数量。WPS 主界面是 XComponent；脚本采用固定坐标和文件系统/进程结果判定，不依赖人工图像识别。

### 重复 workload 向量实验

参考 `wps_workload_vector_package` 的逻辑，项目内新增 `build_workload_feature_vector.py`、`analyze_wps_workload.py` 和 `run_wps_workload.sh`。一行命令即可将完整 WPS 工作流重复执行 3 次，并对每个操作建立 56 维操作级 workload 向量：

```bash
./lzx/mem/Harmony/v6-Homeny/run_wps_workload.sh --repeats 3
```

每一轮保存在 `hdc_out/wps_workload_experiment_<timestamp>/trial_XX/`，不会覆盖原有会话。每个操作内的所有 WPS PID 报告先按 7 个逻辑段聚合，再生成一条 56 维向量。实验根目录额外输出：

- `operation_workload_mapping.json`：操作到每轮 raw/log1p 向量的完整映射；
- `workload_vectors_raw_56d.csv`、`workload_vectors_log1p_56d.csv`：可直接用于后续聚类/分类；
- `operation_workload_summary.csv`、`workload_stability.md`：精确相同、5% 容差内稳定性和最不稳定维度；
- `operation_workload_vectors/`：每个操作、每次重复的可审计 JSON 向量。

稳定性不把连续内存指标强行要求为逐字节不变，而是同时报告 `fixed`（逐维完全相同）和 `stable_within_tolerance`（默认逐维相对范围不超过 5%）。`Size/RSS/PSS/Swap` 仍表示操作后绝对快照，`Referenced` 表示 `clear_refs` 后观察窗口内的访问量。

传入操作命令：

```bash
bash lzx-Test1/v6-Homeny/collect_hdc_v6.sh com.example.app \
  --operation-cmd 'hdc shell "aa start -a EntryAbility -b com.example.app"'
```

### WPS 18 类操作—VMA 带标签数据集

`run_wps_operation_dataset.py` 面向通过 USB 长期连接鸿蒙 PC 的 Windows 主机，严格串行采集 18 类常用 WPS Writer 操作。首版覆盖文档生命周期、编辑、导航、版式和格式化：

```text
NEW_DOCUMENT -> WRITE_TEXT -> SELECT_ALL -> COPY_SELECTION
-> PASTE_SELECTION -> CUT_SELECTION -> UNDO_EDIT -> REDO_EDIT
-> FIND_TEXT -> REPLACE_TEXT -> INSERT_PAGE_BREAK -> INSERT_TABLE
-> FORMAT_BOLD -> FORMAT_ITALIC -> FORMAT_UNDERLINE -> ALIGN_CENTER
-> SAVE_DOCUMENT -> CLOSE_DOCUMENT
```

操作目录来源于 WPS 官方 Writer 快捷键、查找替换和插入表格说明：

- https://www.wps.cn/learning/room/d/329304
- https://www.wps.cn/learning/room/d/273066
- https://help.wps.com/articles/how-to-insert-tables-in-writer/

每个正式操作保留 2 个 baseline、1 个 ACTION 和 1 个 POST_ACTION 窗口；默认 6 个 trial，即 108 个带标签样本，已超过 100 组目标。使用 `-Trials 25` 可得到 450 个正式样本。第一轮 Save As 只为建立普通保存路径，不计入 `SAVE_DOCUMENT` 样本。原始 VMA Markdown 报告留在 `trial_XXX/`，派生数据集写入同一实验根目录。这个目录是首版稳定自动化子集，不声称覆盖 WPS 的全部菜单、云服务和第三方插件功能；新增操作只需扩展 JSON 目录、Session 动作和 runner 计划。

Windows PowerShell（推荐先用 `-Trials 1` 做 smoke）：

```powershell
cd lzx\mem\Harmony\v6-Homeny
python -m py_compile wps_v6_session.py run_wps_operation_dataset.py build_wps_vma_dataset.py
.\run_wps_operation_dataset.ps1 -Trials 1 -NoBuild
.\run_wps_operation_dataset.ps1 -Trials 6 -NoBuild
```

如果设备侧还没有 `mem_analyze-v6-ohos`，先在有 OpenHarmony native SDK 的环境编译并推送一次；Windows 长时间采集使用 `-NoBuild` 复用已存在的设备端二进制。也可以直接运行：

```powershell
python run_wps_operation_dataset.py --trials 6 --no-build --target <hdc-target>
```

输出包括 `dataset_manifest.csv`、`labels.csv`、`vma_features_long.csv`、`vma_vectors_raw.csv`、`vma_vectors_l2.csv`、`pairwise_similarity.csv`、`dataset_summary.json` 和 `dataset_analysis.md`。2048 维向量使用确定性 SHA-256 feature hashing：FILE 占 `0–1023`，ANON 占 `1024–2047`；PID、绝对 VMA 地址、时间戳和 trial 身份只保存在元数据中。

## hdc 脚本执行流程

1. 使用 OpenHarmony native clang 将 `mem_analyze-v6.c` 交叉编译为 `mem_analyze-v6-ohos`。
2. 将二进制推送到设备：`/data/local/tmp/mem_analyze_v6/mem_analyze-v6`。
3. 在设备侧执行 `mem_analyze-v6 --clear-refs <pid>` 或 `mem_analyze-v6 --clear-refs --app <keyword>`。
4. 等待你手动操作设备，或执行 `--operation-cmd` 指定的命令。
5. 在设备侧执行 `mem_analyze-v6 <target> -o /storage/media/100/local/files/Docs/Desktop/output-lzx/referenced_<timestamp>.md`。
6. 将 `/storage/media/100/local/files/Docs/Desktop/output-lzx` 拉回本地 `lzx-Test1/v6-Homeny/hdc_out`。

## 参数说明

- `-Target` / 位置参数：目标 PID 或应用/包名关键字。纯数字按 PID 处理，其他内容按 `--app` 关键字处理。
- `-Out` / `--out`：本地输出目录，默认是 `lzx-Test1/v6-Homeny/hdc_out`。
- `-DeviceDir` / `--device-dir`：设备侧二进制/工作目录，默认是 `/data/local/tmp/mem_analyze_v6`。
- `-DeviceOut` / `--device-out`：设备侧报告输出目录，默认是 `/storage/media/100/local/files/Docs/Desktop/output-lzx`。
- `-WithVma` / `--with-vma`：额外输出 VMA 级别的 Referenced 明细。
- `-NoBuild` / `--no-build`：跳过交叉编译。
- `-NoPush` / `--no-push`：跳过推送设备侧二进制。
- `-OperationCommand` / `--operation-cmd`：在 `clear_refs` 和 `smaps` 采样之间执行的本机命令。

## 设备侧手动用法

部署完成后，也可以直接通过 `hdc shell` 手动运行设备侧二进制：

```bash
hdc shell "/data/local/tmp/mem_analyze_v6/mem_analyze-v6 --clear-refs 12345"
hdc shell "/data/local/tmp/mem_analyze_v6/mem_analyze-v6 12345 -o /storage/media/100/local/files/Docs/Desktop/output-lzx/referenced.md --with-vma"
```

按应用关键字匹配：

```bash
hdc shell "/data/local/tmp/mem_analyze_v6/mem_analyze-v6 --clear-refs --app com.example.app"
hdc shell "/data/local/tmp/mem_analyze_v6/mem_analyze-v6 --app com.example.app -o /storage/media/100/local/files/Docs/Desktop/output-lzx/referenced.md"
```

如果 `--app` 匹配到多个进程，v6 会为每个 PID 分别生成报告，并在文件名中追加 `_pid_<pid>`。

## 输出内容

默认报告包含：

- 进程基本信息
- 分段级别的 `Size`、`Rss`、`Pss`、`Referenced`、`Swap`

启用 `--with-vma` 后，报告会额外包含按 `Referenced(KiB)` 排序的 VMA 明细表。

## 常见问题

- `hdc list targets` 为空：重新连接设备，确认 USB 调试已开启，然后尝试 `hdc kill` 和 `hdc start`。
- `clear_refs` 失败：当前 `hdc shell` 对目标进程权限不足。
- `smaps` 读取失败：目标进程已退出、PID 已变化，或 `/proc` 权限受限。
- `--app` 找不到进程：先启动应用，再用 `hdc shell "ps -A -o PID,ARGS"` 确认关键字。
- 本地没有拉回报告：检查设备目录 `hdc shell "ls -l /storage/media/100/local/files/Docs/Desktop/output-lzx"`。
