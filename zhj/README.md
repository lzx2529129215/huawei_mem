这是您要求的中文版 `README.md`，已保留原始 Markdown 格式、代码块和文档链接：

```markdown
# Linux 6.17 内存调度实验

本仓库实现了一套以测量为先的复现框架，与以下工作对齐：

- Acclaim：页面重故障、直接回收、0/3/8/15 个后台应用场景、五分钟前台使用。
- AppFlow：GB 级冷启动、5/15/15+2 个后台工作负载、I/O 吞吐量、直接回收和进程终止事件。
- Fleet：缓存应用容量、512/2048 字节的托管对象、每个合成应用 180 MB、热启动、GC/对象代理、FPS 和卡顿。

目标是一台专用的 Linux 6.17 测试机器。本仓库不会假装原生 Linux QQ/WPS 具备 Android 专用指标：除非有 Android/JVM 专用探针提供数据，否则 LMKD、ART Java 堆和 ART 对象再访问等指标将报告为 `N/A`。

## Linux 6.17 测试主机上的快速入门

```bash
cd /path/to/linux6.17_test
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

bash scripts/install_qq_wps_ubuntu.sh
bash scripts/preflight.sh
bash scripts/run_qq_wps_round.sh
```

`configs/qq_wps.json` 控制应用程序命令、进程名、窗口模式、持续时间、间隔和重复次数。已签入的配置执行所请求的 QQ 和 WPS 单次冷启动轮次；可使用 `COLD_REPETITIONS=N` 来扩展重复次数。

当厂商页面由 JavaScript 渲染时，安装脚本接受当前官方直链包：

```bash
QQ_DEB_URL='https://official.example/linuxqq_amd64.deb' \
WPS_DEB_URL='https://official.example/wps_x86_64.deb' \
bash scripts/install_qq_wps_ubuntu.sh
```

请勿在共享机器上启用 `DROP_CACHES=1`。在隔离的实验主机上，严格冷缓存运行的命令为：

```bash
DROP_CACHES=1 DURATION_SECONDS=60 bash scripts/run_qq_wps_round.sh
```

## 与论文对齐的工作负载

场景运行脚本会拒绝超过其论文对齐上限的有效内存预算（Acclaim/Fleet：4 GiB，AppFlow：8 GiB）。该保护机制会检测启动限制以及最内层 cgroup-v2 的 `memory.max`。`ALLOW_UNCONSTRAINED_MEMORY=1` 仅用于明确标记的冒烟测试。

```bash
# Acclaim：分别运行每种后台数量，每种重复十次。
bash scripts/scenarios/run_acclaim.sh 0
bash scripts/scenarios/run_acclaim.sh 3
bash scripts/scenarios/run_acclaim.sh 8
bash scripts/scenarios/run_acclaim.sh 15

# AppFlow：在三种压力水平下完整写入 1.2 GiB 目标并读取。
bash scripts/scenarios/run_appflow.sh low
bash scripts/scenarios/run_appflow.sh medium
bash scripts/scenarios/run_appflow.sh high

# Fleet：托管对象代理工作负载。
bash scripts/scenarios/run_fleet.sh 512 18
bash scripts/scenarios/run_fleet.sh 2048 18
```

若为特定应用创建 cgroup，可将其作为临时用户服务启动，并将打印出的 cgroup 路径传递给采集器：

```bash
CGROUP_PATH="$(bash scripts/create_user_cgroup_scope.sh memexp-qq qq)"
python3 -m memsched_exp.cli collect \
  --name qq --duration 60 --cgroup "$CGROUP_PATH" --output results/qq-cgroup
```

## 输出

每次运行都包含不可变的原始输入（`before.json`、`after.json`、`samples.jsonl`）、元数据以及 `summary.json`。当启用 eBPF 时，还会包含 `reclaim-events.jsonl` 和 `reclaim-events-summary.json`。启动和帧分析分别存储，以便审计其测量来源。

元数据包括内核配置哈希、swap/zram、VM sysctl、THP、CPU 调节器、会话和结果文件系统。QQ/WPS 还会额外记录可执行文件的 SHA-256 和 Debian 软件包版本。无效的 cgroup 端点、未配对/丢失的 eBPF 事件以及启动超时会被报告为无效，而不是转换为零。

聚合已完成运行而不丢弃原始计数器：

```bash
python3 -m memsched_exp.report --root results --output results/summary.csv
```

参见 [详细的实验设计](docs/EXPERIMENT_DESIGN.md) 和 [指标词典](docs/METRICS.md)。

对于 Windows 宿主机开发和 Linux 虚拟机操作，请遵循 [VS Code + Linux 6.17 虚拟机操作指南](docs/VSCODE_VM_OPERATION_GUIDE.md)。
```
