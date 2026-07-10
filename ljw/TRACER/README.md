# Linux Page Cache eBPF Tracer (页面缓存特征采集器)

基于 eBPF 的 Linux 内核页面缓存（Page Cache）事件与 VFS 读写操作追踪工具。精准追踪文件在内存中的生命周期（载入、访问、驱逐），并将每一次宏观的读写系统调用（`vfs_read`/`vfs_write`）与微观的物理页状态变化建立精确的时间轴映射。

## 核心特性

- **多维事件捕获**：使用 eBPF 在内核底层捕获 `ACCESS` (页面访问)、`INSERT` (页面插入)、`EVICT` (页面驱逐) 和 `OP_DONE` (操作结束)。
- **操作-页面精准映射**：自动剥离网络、终端等无页缓存操作的杂音，将真实的物理页事件精确挂载到对应的系统调用时间区间内。
- **离线特征对齐**：使用高性能 Python 解析器，自动计算用于机器学习的页面特征（如 `page_time_delta`, `seq_distance`, `inode_hotness_ema` 等）。

## 文件结构

- **`tracer.py`**: 核心 eBPF 追踪器。通过挂载 Kprobe 收集底层页面事件，并以极高吞吐量将原始数据输出到 `raw_trace.bin`。
- **`parser.py`**: 离线解析工具。将二进制追踪文件转化为特征对齐的 CSV 文件，并生成 JSON 格式的操作映射表。

## 环境依赖

- **操作系统**：Linux Kernel 6.17.13
- **工具链**：
  - Python 3.x
  - `bcc` (BPF Compiler Collection)
  - `filebench` (用于生成文件系统负载)

---

## 快速开始

需要两个终端窗口来分别运行追踪器和施加内存压力的负载。

### 1. 准备测试负载
在任意终端中执行以下命令，生成 Filebench 测试文件：

```bash
mkdir -p /home/wency/test_dir
cat << 'EOF' > my_test.f
set $dir=/home/wency/test_dir
set $nfiles=1000
set $meandirwidth=20
set $filesize=1048576
set $nthreads=2
set iosize=4096

define fileset name=testF,path=dir,entries=nfiles,dirwidth=meandirwidth,size=filesize,prealloc=80
define process name=filereader,instances=1
{
  thread name=filereaderthread,memsize=10m,instances=nthreads { 
    flowop readwholefile name=read-file,filesetname=testF 
  } 
} 
run 60
EOF
```
> **注**：为保证触发 `EVICT`，建议保持总数据量略大于限制的内存量，如 1000 个 1MB 文件 = 1GB 总数据量。

### 2. 启动 eBPF 追踪器 (终端 A)
确保具备 Root 权限，启动追踪器，它会开始在后台录制数据：

```bash
sudo python3 tracer.py
```
*(看到“开始追踪页面缓存状态”后，放置后台运行)*

### 3. 施加内存压力并执行负载 (终端 B)
通过 `systemd-run` 强行将进程的可用物理内存限制为 500MB，以迫使 1GB 的文件集在读取时触发 Page Cache 驱逐：

```bash
sudo systemd-run --scope -p MemoryMax=500M filebench -f my_test.f
```

### 4. 停止追踪与数据解析 (终端 A)
切回终端 A，按下 `Ctrl + C` 停止追踪器，然后执行解析：

```bash
python3 parser.py
```

---

## 📊 输出数据说明

解析完成后，当前目录下会生成两份关键数据文件：

### 1. `aligned_trace_features.csv`
用于机器学习模型训练的特征宽表。每一行代表内核中真实发生的一次事件：

- **`timestamp`**: 绝对时间戳。
- **`op_id` / `op_type`**: 所属的读/写系统调用 ID 与类型。
- **`ino` / `offset`**: 被操作的 File Inode 和页面偏移。
- **ML 特征字段**：
  - `page_time_delta` / `inode_time_delta`: 时间局部性特征（距上次访问的时间差）。
  - `seq_distance`: 空间局部性特征（跨度）。
  - `frequency` / `inode_hotness_ema`: 基于指数移动平均（EMA）计算的页面级和文件级热度。

### 2. `operation_to_pages.json`
提供宏观系统调用与微观物理页面的树状映射结构，方便分析一次 Read/Write 具体触及了哪些物理内存：

```json
{
  "996166599871": {
    "start_ts": 996166599871,
    "end_ts": 996166600714,
    "duration_ns": 843,
    "op_type": "READ",
    "pages": [
      {
        "ino": 786522,
        "offset": 0,
        "event": "INSERT",
        "ts": 996166599900
      },
      {
        "ino": 786522,
        "offset": 0,
        "event": "ACCESS",
        "ts": 996166600100
      }
    ]
  }
}
```
