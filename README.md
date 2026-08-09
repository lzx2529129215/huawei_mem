# memcap — 鸿蒙 PC 应用内存页快照采集工具

通过 hdc 连接鸿蒙 PC 设备，对目标进程做单次内存页快照采集，输出 CSV 供后续分析。支持跨快照对比，定位持续驻留物理内存的"热"区域。

## 技术路线

```
主机端 (macOS/Windows)              鸿蒙设备 (MateBook Pro HAD-W32)
┌─────────────────────┐            ┌──────────────────────────────┐
│ collect.sh          │   hdc      │  /proc/[pid]/maps   VMA边界  │
│  · 交叉编译 memcap  │ ──────→    │  /proc/[pid]/smaps  RSS/PSS  │
│  · hdc file send    │  推送      │  /proc/[pid]/pagemap 页状态  │
│  · hdc shell 运行   │ ←──────    │              ↓               │
│  · hdc file recv    │  拉回      │  memcap (C程序, aarch64)     │
│         ↓           │            │  读取 → 解析 → 输出6张CSV    │
│  memcap_out/*.csv   │            └──────────────────────────────┘
│         ↓           │
│  analyze_memory.py  │ → 跨快照匹配 → Hot/Dynamic/Cold 分类
│         ↓           │
│  实验报告 (HTML)     │
└─────────────────────┘
```

**数据链路**：`/proc` 内核接口 → memcap (C) → CSV → analyze_memory.py → 报告

## 环境要求

| 组件 | 用途 | 安装方式 |
|------|------|---------|
| DevEco Studio | 提供 OpenHarmony SDK (clang + sysroot) | [华为开发者官网](https://developer.huawei.com/) |
| hdc 3.x | 主机与鸿蒙设备通信 | DevEco Studio → SDK Manager → Toolchains |
| Python 3 | 运行分析脚本 | 系统自带 |
| 鸿蒙设备 | 采集目标 | USB 连接 + 开启 USB 调试 |

## 快速开始

### 1. 克隆仓库

```bash
git clone git@github.com:zhairui1995/huawei_mem.git
cd huawei_mem
```

### 2. 初始化环境

```bash
source scripts/setup_env.sh
```

验证连接：

```bash
hdc list targets
# 应输出: 3QC0124C11000839  USB  Connected  localhost
```

### 3. 采集第一个快照

以斗鱼应用为例：

```bash
# 查找斗鱼进程
hdc shell "ps -A -o PID,ARGS" | grep -i douyu
# 输出: 9376 com.douyu.ho.app
#      9830 com.douyu.ho.app:gpu

# 一行采集（按进程名搜索）
bash scripts/collect.sh douyu

# 或指定 PID + 应用标签
bash scripts/collect.sh 9376 斗鱼

# 采集所有子进程（主进程 + GPU 进程）
bash scripts/collect.sh douyu --all
```

脚本自动完成：编译 → 推送 → 采集 → 拉回，结果保存在 `memcap_out/`。

### 4. 操作应用后再采集

常规对比场景：不关闭应用，仅进行用户操作后再次采集。

```bash
# 第一次：前台正常状态
bash scripts/collect.sh douyu

# 用户在设备上操作（最小化、切换直播间等）...

# 第二次：后台状态（PID 不变）
bash scripts/collect.sh 9376 斗鱼 -f background -o op_switch_room
```

### 5. 重启后采集（PID 变化场景）

```bash
# 重启斗鱼
# 查找新 PID
hdc shell "ps -A -o PID,ARGS" | grep -i douyu

# 第三次：重启后前台（新 PID）
bash scripts/collect.sh 25797 斗鱼 -f foreground -o op_restart
```

### 6. 对比分析

```bash
# 同 PID 对比（exact 模式）：VMA 按地址精确匹配
python3 scripts/analyze_memory.py -i memcap_out/ --pid 9376

# 跨 PID 对比（fuzzy 模式）：VMA 按路径+类型+权限语义匹配
python3 scripts/analyze_memory.py -i memcap_out/ --mode fuzzy --threshold 0.8

# 指定快照对比
python3 scripts/analyze_memory.py -i memcap_out/ \
    --sample sample_20260525_024423 sample_20260525_024937 sample_20260525_025620
```

**输出三类 VMA**：

| 分类 | 持久化得分 | 含义 |
|------|:--------:|------|
| Hot | ≥ 90% | 几乎所有快照中都驻留在物理内存 |
| Dynamic | 30%–90% | 间歇驻留，受前后台切换影响 |
| Cold | < 30% | 虚拟地址预留，极少实际分配 |

## 斗鱼实验案例

基于 2026-05-25 的三次采集实验（详见 `docs/douyu_experiment_report.html`）：

| 快照 | PID | 状态 | RSS | Swap | 物理驻留 |
|------|-----|------|-----|------|:------:|
| #1 | 9376 | 前台·初始 | 640 MB | 55 MB | 1.48% |
| #2 | 9376 | 后台·最小化 | 560 MB | 101 MB | 1.17% |
| #3 | 25797 | 前台·重启 | 608 MB | 56 MB | 1.40% |

**核心发现**：

- **切后台触发主动 Swap**：RSS -80MB (-12.5%)，Swap +46MB (+83%)
- **跨重启基础足迹 53MB**：Hot 区域（fuzzy 模式）包含 ArkTS 运行时核心 + 系统 .so
- **ArkTS Heap 是最大内存消费者**：占 RSS 52-57%，前后台波动 77MB
- **虚拟地址 47.5GB，物理驻留仅 1.4%**：Chromium partition_alloc 特征，不影响实际内存

### 会话级采集

```bash
# 单次会话多操作、多阶段自动编排
bash scripts/collect_session.sh douyu 斗鱼 session_001

# 指定操作序列
bash scripts/collect_session.sh douyu 斗鱼 session_001 -o op_launch,op_switch,op_minimize

# 自定义采集阶段
bash scripts/collect_session.sh douyu 斗鱼 session_001 --phases before,after_0s,after_3s
```

每个操作默认采集 before、after_0s、after_1s、after_3s、after_5s 五个阶段。
脚本会提示用户在设备上执行操作，自动处理延迟等待，并维护 session_index.csv、process_snapshot.csv。

### 数据质量校验

```bash
# 校验 CSV 数据可 join 性和采集质量
python3 scripts/validate_dataset.py -i memcap_out/

# 按 session 筛选校验
python3 scripts/validate_dataset.py -i memcap_out/ --session session_001
```

检查项：snapshot/VMA/pagemap/operation join 一致性、success sample 数据完整性、
时间戳单调性、collect_status/pagemap scan_status 分布、session 数据一致性。

### collect.sh 高级选项

```bash
# 指定本地输出目录
bash scripts/collect.sh douyu --out my_output/

# 指定设备端输出目录
bash scripts/collect.sh douyu --device-out /data/local/tmp/memcap/custom_out

# 采集前清空设备和本地输出（全新开始）
bash scripts/collect.sh douyu --reset-out

# 组合使用
bash scripts/collect.sh 9376 斗鱼 -o op_test --out session_out/ --reset-out
```

## 文件说明

```
huawei_mem/
├── memcap.c                         # 设备端 C 采集程序（C11, 342行）
├── scripts/
│   ├── setup_env.sh                 # 环境初始化（sourced）
│   ├── collect.sh                   # 一键采集脚本（bash）
│   ├── collect_session.sh           # 会话级编排脚本（bash）
│   ├── analyze_memory.py            # 跨快照对比分析（Python3）
│   ├── analyze_operations.py        # 操作级持久性分析（Python3）
│   └── validate_dataset.py          # 数据集质量校验（Python3）
├── docs/
│   ├── douyu_experiment_report.html # 斗鱼三次采集实验报告（浏览器打开）
│   ├── progress_dashboard.html      # 项目进展可视化看板
│   ├── progress_report.md           # 项目进展文档
│   └── report_001_douyu.md          # 斗鱼首次采集分析报告
└── memcap_out/                      # 采集结果 CSV（gitignore）
    ├── snapshot_index.csv
    ├── vma_memory_snapshot.csv
    ├── pagemap_snapshot.csv
    ├── session_index.csv            # (会话脚本生成)
    └── process_snapshot.csv         # (会话脚本生成)
```

## 注意事项

- **USB 调试**：鸿蒙设备需在 设置→开发者选项 中开启 USB 调试
- **hdc PATH**：每次新终端需 `source scripts/setup_env.sh`，或写入 `~/.zshrc`
- **memcap 一次编译即可**：后续采集加 `--no-push` 跳过编译推送，节省时间
- **不要同时采集同一 out_dir**：snapshot_index 追加可能交叉
- **pagemap 需要 root 权限读取 PFN**：当前不加 CAP_SYS_ADMIN，PFN 字段被置零

## 协作

- 仓库：`github.com/zhairui1995/huawei_mem`（私有）
- 协作者：zhairui1995, yyf123123
- 开发环境：macOS + DevEco Studio SDK / Windows + DevEco Studio SDK
