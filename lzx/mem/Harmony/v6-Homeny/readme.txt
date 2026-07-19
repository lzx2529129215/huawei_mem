README.md
中文说明文档。介绍 v6 的用途、hdc 采集流程、PowerShell/Bash 用法、参数和常见问题。

mem_analyze-v6.c
核心 C 源码。写 /proc/<pid>/clear_refs，读取 /proc/<pid>/smaps，保留 Markdown 段汇总，并输出包含全部 VMA 的 homeny.vma.v1 JSONL。

process_role_resolver.py / operation_vma_mapping.py / analyze_operation_vma_mapping.py
分别负责 WPS/CEF 进程角色、纯 baseline/VMA 配对与活动估计、跨 trial support；不修改内核、保护、预取或回收行为。

mem_analyze-v6-ohos
用 OpenHarmony native clang 交叉编译出来的鸿蒙设备侧可执行文件。collect_hdc_v6.ps1/sh 会把它推到设备上运行。

collect_hdc_v6.ps1
Windows PowerShell 主入口。负责：编译 mem_analyze-v6.c、通过 hdc 推送到鸿蒙设备、执行 clear_refs、等待操作、采样 smaps、拉回报告。你现在主要用这个。

collect_hdc_v6.sh
Bash 版本入口。功能和 collect_hdc_v6.ps1 对齐，适合 Git Bash、WSL 或类 Unix 环境。
