# Linux 6.17 内存调度实验测量系统

本目录是测试与指标组维护的 Linux 6.17 实验测量代码。它负责：

- 在确定的实验窗口内采集系统和应用 cgroup 指标；
- 用 eBPF tracepoint 统计 Direct Reclaim、kswapd 和 OOM 事件；
- 验证冷缓存、进程身份、cgroup 端点和事件完整性；
- 保存不可变原始数据；
- 对 Baseline/Candidate 进行严格配对统计。

本目录不负责 QQ/WPS 的点击、滚动、窗口切换等 GUI 自动化。自动化程序只需要遵守
`collector_ready -> workload_start -> workload_stop -> collector_done` 标记协议。

## 快速开始

在 Linux 6.17 测试机执行：

```bash
cd /path/to/huawei_mem/zhj
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python3 -m unittest discover -s tests -v
bash scripts/preflight.sh
```

QQ/WPS 首轮链路验证：

```bash
bash scripts/install_qq_wps_ubuntu.sh
bash scripts/run_qq_wps_round.sh
```

合成压力场景：

```bash
bash scripts/scenarios/run_acclaim.sh 0
bash scripts/scenarios/run_acclaim.sh 3
bash scripts/scenarios/run_acclaim.sh 8
bash scripts/scenarios/run_acclaim.sh 15

bash scripts/scenarios/run_appflow.sh low
bash scripts/scenarios/run_appflow.sh medium
bash scripts/scenarios/run_appflow.sh high

bash scripts/scenarios/run_fleet.sh 512 18
bash scripts/scenarios/run_fleet.sh 2048 18
```

AppFlow 会对 1.2 GiB 目标文件执行 `POSIX_FADV_DONTNEED`，再用 `mincore` 验证驻留率。
驻留率高于 `MAX_COLD_RESIDENT_RATIO`（默认 1%）时该轮直接失败，不会把缓存读取写成冷启动数据。

## 正式 Baseline/Candidate 实验

正式轮次必须设置 variant 和固定 seed：

```bash
EXPERIMENT_VARIANT=baseline \
EXPERIMENT_SEED=20260814 \
EXPERIMENT_REPETITION=1 \
KERNEL_COMMIT='<baseline commit>' \
POLICY_MODE=off \
APPLY_COMPILED=false \
OUTPUT_DIR=results/paired/acclaim-bg8/baseline-r01 \
bash scripts/scenarios/run_acclaim.sh 8

EXPERIMENT_VARIANT=candidate \
EXPERIMENT_SEED=20260814 \
EXPERIMENT_REPETITION=1 \
KERNEL_COMMIT='<candidate commit>' \
POLICY_MODE=apply \
APPLY_COMPILED=true \
MODEL_PROVENANCE='<model id or hash>' \
OUTPUT_DIR=results/paired/acclaim-bg8/candidate-r01 \
bash scripts/scenarios/run_acclaim.sh 8
```

生成逐轮 CSV 和配对报告：

```bash
python3 -m memsched_exp.report \
  --root results/paired \
  --output results/paired/runs.csv

python3 -m memsched_exp.compare \
  --root results/paired \
  --output results/paired/comparison.json \
  --markdown results/paired/comparison.md
```

比较器按 `场景 + seed + repetition + cache state + workload hash` 配对，环境指纹不一致、
轮次无效、manifest 缺失或一侧缺失时不会计算改善率。输出 mean、median、sample standard
deviation、p90/p95、配对差和 bootstrap 95% CI。

## Linux 6.17 集成检查

单元测试不能替代真实内核测试。在目标机中用独立 systemd scope 运行：

```bash
systemd-run --user --scope --wait \
  python3 tests/integration/linux617_pipeline.py \
    --output results/integration-$(date +%Y%m%d-%H%M%S) \
    --current-cgroup
```

该检查验证 before 快照早于 workload start，after 快照早于 collector done，并验证 cgroup
在首尾端点均可读且未被重新创建。

## 文档

- [测量系统实施与接口手册](docs/MEASUREMENT_SYSTEM_GUIDE.md)
- [指标定义](docs/METRICS.md)
- [完整实验设计](docs/EXPERIMENT_DESIGN.md)
- [VS Code 与 Linux 6.17 虚拟机操作](docs/VSCODE_VM_OPERATION_GUIDE.md)

## 明确限制

- X11 首个 mapped window 是启动就绪代理，不等于首个可交互帧。
- `frames.py` 负责帧 CSV 统计，帧事件必须由图形栈采集器或自动化侧提供。
- Linux OOM 不是 Android LMKD；报告不会伪造 LMK 值。
- QQ/WPS 不是 ART 应用，Java 堆、ART GC 工作集和 ART 对象重访问为 `N/A`。
- Java 合成 workload 的对象指标是可重复代理，不是 JVM/ART GC 内部指标。
