# eBPF App Memory & File I/O Tracer
**(eBPF 应用内存与文件 I/O 追踪与分析工具)**

本项目是一套基于 eBPF (BCC) 的应用层操作与内核层内存/文件系统行为的追踪工具。它可以监控特定应用（通过 Cgroup 隔离）在执行特定业务场景（如：打开文档、复制粘贴、放映等）时，底层的 Page Cache 变化（页面访问、插入、驱逐）以及 VFS 读写操作，并将内核事件与应用层操作时间戳进行精准对齐。

##  核心组件

项目包含四个核心 Python 脚本：

1. **`bpf_tracer.py`**: 核心追踪器。使用 eBPF 在内核挂载 kprobe/kretprobe，监听指定 Cgroup 内的 `folio` 操作及 `vfs_read/vfs_write` 事件，将收集到的二进制数据高效输出到 `raw_trace.bin`。
2. **`cgroup_watcher.py`**: 进程守卫程序。监控指定的应用进程名（如 `wps`），一旦发现新进程启动，立刻将其 PID 移动到指定的 Cgroup 中，以便 `bpf_tracer.py` 进行追踪。
3. **`app_logger.py`**: 应用场景时间戳记录器。提供简单的交互界面，用于记录具体业务操作（如“新建保存”）的精准起止时间，并保存为 `app_operations.json`。
4. **`trace_parser.py`**: 数据解析与对齐工具。将 `bpf_tracer.py` 产生的高效二进制数据 (`raw_trace.bin`) 解析并与 `app_logger.py` 记录的时间戳对齐，最终生成易于分析的 CSV 文件 (`aligned_trace.csv`)。

##  环境依赖

- **Linux 内核**: 支持 eBPF 的较新内核版本。
- **BCC (BPF Compiler Collection)**: 需要安装 `python3-bpfcc`（例如在 Ubuntu 上：`sudo apt-get install bpfcc-tools linux-headers-$(uname -r) python3-bpfcc`）。
- **Python 3**: 需要具备 root 权限来执行 eBPF 脚本。

##  快速开始 / 使用指南

为了保证测试的连贯性，建议准备 **4 个终端窗口 (A, B, C, D)**。所有操作均在同一个文件夹下进行（例如当前目录）。

### 1. 准备工作 (准备词表)

在项目目录下，根据你的自动化测试脚本，生成操作词表文件 `op_vocab.json`。以 WPS 测试为例：

```bash
cat << 'EOF' > op_vocab.json
{
  "WPS": {
    "场景 0010_模板预览": 10,
    "场景 0020_新建保存": 20,
    "场景 0030_十文档切换": 30,
    "场景 0040_Word 复制粘贴": 40,
    "场景 0050_PPT 放映": 50,
    "场景 0060_Excel 过滤": 60,
    "场景 0070_PDF 翻页": 70
  }
}
EOF
```

### 2. 启动追踪 (终端 B)

在终端 B 中，创建测试用的 Cgroup 并启动 BPF 追踪器：

```bash
sudo mkdir -p /sys/fs/cgroup/mglru_test
sudo python3 bpf_tracer.py /sys/fs/cgroup/mglru_test
```
*此时追踪器开始运行，并等待抓取目标 Cgroup 内的事件。*

### 3. 配置场景记录器 (终端 C)

在终端 C 中运行 Logger：

```bash
python3 app_logger.py
```
根据提示，输入应用序号和操作序号（例如：输入 `0` 选择 WPS，再输入你要测试的场景序号）。
**注意：停留在提示符 `>>> 请在 A 终端启动应用后，回到此处按回车结束 <<<` 处，先不要按回车。**

### 4. 启动进程守卫 (终端 D)

在终端 D 启动 Watcher，准备捕获即将启动的应用（以 `wps` 为例）：

```bash
sudo python3 cgroup_watcher.py wps /sys/fs/cgroup/mglru_test
```
屏幕会提示：`--- 守卫就绪 --- 请确保 B 追踪已开。在这里【按回车】后立刻去 A 启动应用！`
**此时，在终端 D 敲击回车，然后立刻切换到终端 A 执行下一步。**

### 5. 执行应用自动化脚本 (终端 A)

在终端 A 中运行你的应用自动化测试脚本（例如借助 xdotool 或其他自动化框架）：

```bash
# 示例：运行 WPS 的某个自动化测试场景
bash automation/run_wps_case.sh 0010
```
*等待自动化脚本执行完毕（应用窗口关闭，终端 A 恢复到输入状态）。*

### 6. 结束记录与追踪

1. 切回 **终端 C**，按下 `Enter`（回车键）结束时间戳记录。
2. 切回 **终端 B**，按下 `Ctrl + C` 结束 BPF 追踪。此时会生成 `raw_trace.bin`。

### 7. 数据解析 (终端 B)

在终端 B 中运行解析脚本，将二进制数据转化为 CSV 并与时间戳对齐：

```bash
python3 trace_parser.py
```
解析成功后，当前目录下会生成 `aligned_trace.csv` 文件。

##  输出数据说明 (`aligned_trace.csv`)

生成的 CSV 文件包含以下字段，方便后续进行数据可视化与分析：

| 字段名 | 说明 |
| :--- | :--- |
| `timestamp` | 事件发生的纳秒级时间戳 |
| `op_id` | 操作上下文 ID（关联特定的 VFS 读写周期） |
| `app_op` | **对齐的应用操作名**（如 `WPS_场景 0010_模板预览`），非记录时段显示为 `NONE` |
| `pid` / `tid` | 进程 ID 与 线程 ID |
| `comm` | 触发事件的进程名 (Comm) |
| `event_type` | 内核事件大类 (`ACCESS`, `INSERT`, `EVICT`, `OP_DONE`) |
| `op_type` | 具象化操作 (`VFS_READ`, `VFS_WRITE`, `MEM_HIT`, `MMAP_LOAD`, `RECLAIM` 等) |
| `ino` | 发生操作的文件 Inode 号 |
| `offset` | 文件内的页偏移量 |
| `major` / `minor` | 设备的主/次设备号 |
| `op_duration_us`| VFS 读写操作的耗时（微秒） |
