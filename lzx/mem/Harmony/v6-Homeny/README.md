# mem_analyze v6：鸿蒙 hdc Referenced 采集流程

v6 保留原 Referenced 链路，并为 WPS 自动化增加操作前 idle baseline：

```text
baseline clear_refs -> idle wait -> Markdown/JSONL
-> operation clear_refs -> 执行目标操作 -> Markdown/JSONL
-> VMA 配对 -> TIME_NORMALIZED_REFERENCED_HEURISTIC
```

`Referenced(KiB)` 来自 `/proc/<pid>/smaps`。它只表示从清空 `/proc/<pid>/clear_refs` 到读取 `smaps` 这段观察窗口内，被访问过的驻留页规模。

注意：v6 不做 pagemap、PFN、page_idle 级别的逐页追踪，也不执行保护、预取或回收策略。文件映射粒度只到真实 VMA 的 mapped file-offset interval；不把活跃 VMA 伪装成 256 KiB bucket。

`mem_analyze-v6` 的 `--jsonl-output <path>` 输出全量 `homeny.vma.v1` JSONL，包括 `Referenced=0` 的 VMA。多 PID 时 Markdown 和 JSONL 都使用 `_pid_<pid>` 后缀，并输出稳定状态行 `REPORT_MD=` 与 `REPORT_JSONL=`。

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

普通可测阶段执行 `idle baseline -> operation` 两个独立 clear_refs 窗口；`01_open_wps` 使用 `POST_LAUNCH` 语义，`08_reopen_saved_document` 的 baseline 是 WPS 已启动但尚未打开目标文档的空闲状态。输出目录新增 `baseline_reports/`、`operation_reports/`、`post_launch_reports/` 和 `vma_mapping/`。原 `operations.csv.report` 仍只供 operation/POST_LAUNCH Markdown 与 56 维流程使用。

可配置参数：

```bash
./run_wps_v6.sh --baseline-window-s 5.0
./run_wps_v6.sh --no-idle-baseline
./run_wps_v6.sh --vma-mapping-config ./vma_mapping_config.json
./run_wps_v6.sh --disable-vma-mapping
```

匿名 VMA 仅输出 `OPERATION_RECOGNITION_AUXILIARY` 特征，固定 `long_term_page_mapping=false`、`protection_eligible=false`、`prefetch_eligible=false`。本项目固定保持 `ready_for_operation_recognition=false` 和 `ready_for_apply=false`。

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
- `operation_file_vma_mapping.json`、`operation_file_vma_support.csv`：文件 VMA exact/semantic identity 和跨 trial support；
- `operation_anon_vma_features.json`、`operation_anon_vma_support.csv`：匿名辅助特征及独立 support；
- `operation_vma_analysis.json`、`operation_vma_analysis.md`：baseline、质量、支持率与 readiness。

稳定性不把连续内存指标强行要求为逐字节不变，而是同时报告 `fixed`（逐维完全相同）和 `stable_within_tolerance`（默认逐维相对范围不超过 5%）。`Size/RSS/PSS/Swap` 仍表示操作后绝对快照，`Referenced` 表示 `clear_refs` 后观察窗口内的访问量。

传入操作命令：

```bash
bash lzx-Test1/v6-Homeny/collect_hdc_v6.sh com.example.app \
  --operation-cmd 'hdc shell "aa start -a EntryAbility -b com.example.app"'
```

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
hdc shell "/data/local/tmp/mem_analyze_v6/mem_analyze-v6 12345 -o /storage/media/100/local/files/Docs/Desktop/output-lzx/referenced.md --jsonl-output /storage/media/100/local/files/Docs/Desktop/output-lzx/referenced.jsonl --with-vma"
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
