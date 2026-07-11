# MGLRU 内核修改与增量编译安装说明

本文档记录本次为 MGLRU 页级验证新增 `query`、`promote`、`depromote` 接口时的内核修改位置、修改思路，以及修改后如何增量编译、安装、重启和验证。

## 1. 目录约定

当前实验使用的内核源码目录：

```bash
/home/lzx/Desktop/huawei/huawei_mem/lzx/MGLRU-test/mglru_kernel_transfer/linux-hwe-6.17-6.17.0
```

当前实验使用的 out-of-tree 构建目录：

```bash
/home/lzx/Desktop/huawei/huawei_mem/lzx/MGLRU-test/mglru_kernel_transfer/linux-hwe-6.17-mglru-build
```

后续命令建议先进入工程目录：

```bash
cd /home/lzx/Desktop/huawei/huawei_mem/lzx/MGLRU-test/mglru_kernel_transfer
```

下文用变量简化命令：

```bash
SRC=$PWD/linux-hwe-6.17-6.17.0
BUILD=$PWD/linux-hwe-6.17-mglru-build
```

## 2. 本次修改目标

目标是在 debugfs 接口中增加页级 MGLRU 调试能力：

```text
/sys/kernel/debug/lru_gen_pages
```

新增或完善的命令：

```text
query <pfn>
promote <pfn> <nr_pages>
depromote <pfn> <nr_pages>
```

含义：

- `query <pfn>`：查询指定 PFN 所在 folio 当前属于哪个 memcg、哪个 NUMA node、anon/file 类型、当前 generation、对应 seq、当前最新 `max_seq`、当前最老 `min_seq`。
- `promote <pfn> <nr_pages>`：把指定 PFN 范围内的 folio 移动到当前 lruvec 的最新 generation，即 `lru_gen_from_seq(lruvec->lrugen.max_seq)`。
- `depromote <pfn> <nr_pages>`：把指定 PFN 范围内的 folio 移动到当前 lruvec 中该类型页对应的最老 generation，即 `lru_gen_from_seq(lruvec->lrugen.min_seq[type])`。

## 3. 内核代码修改位置

主要修改文件：

```bash
$SRC/mm/vmscan.c
```

可用下面命令快速定位本次新增逻辑：

```bash
rg -n "mglru_page_query|mglru_move_folio|mglru_promote|mglru_depromote|query <pfn>|depromote <pfn>" \
  "$SRC/mm/vmscan.c"
```

当前关键函数位置大致如下：

```text
mglru_page_query_pending
mglru_page_query_pfn
mglru_move_folio_locked()
mglru_promote_folio_locked()
mglru_depromote_folio_locked()
mglru_move_pfn()
mglru_promote_pfn()
mglru_depromote_pfn()
mglru_page_query_show()
mglru_page_query_set()
mglru_promote_policy_pfn()
mglru_depromote_policy_pfn()
mglru_page_policy_parse_line()
mglru_page_policy_show()
```

## 4. query 接口修改说明

新增全局查询状态：

```c
static bool mglru_page_query_pending;
static unsigned long mglru_page_query_pfn;
```

写入命令：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
```

写入后，`mglru_page_query_set()` 保存待查询 PFN：

```c
static void mglru_page_query_set(unsigned long pfn)
{
	unsigned long flags;

	spin_lock_irqsave(&mglru_page_policy_lock, flags);
	mglru_page_query_pfn = pfn;
	mglru_page_query_pending = true;
	spin_unlock_irqrestore(&mglru_page_policy_lock, flags);
}
```

读取接口时，`mglru_page_policy_show()` 检查是否有 query 请求；如果有，就调用 `mglru_page_query_show()` 输出结果：

```bash
sudo cat /sys/kernel/debug/lru_gen_pages
```

输出字段：

```text
# input_pfn head_pfn nr_pages memcg_id nid type zone lru active gen seq max_seq min_seq_anon min_seq_file latest oldest
```

关键字段解释：

- `input_pfn`：用户输入的 PFN。
- `head_pfn`：该 PFN 所在 folio 的 head PFN。
- `nr_pages`：folio 覆盖的 4 KiB 页数。
- `memcg_id`：`mem_cgroup_id(memcg)`，用于和 `/sys/kernel/debug/lru_gen` 中的 memcg id 对齐。
- `nid`：NUMA node id。
- `type`：`anon` 或 `file`。
- `lru`：folio 是否在 LRU 上。
- `active`：当前 generation 是否属于 active generation。
- `gen`：folio flags 中记录的 MGLRU 环形 generation 下标。
- `seq`：根据 `gen` 和当前 `max_seq` 反推得到的 generation seq。
- `max_seq`：当前 lruvec 最新 generation seq。
- `min_seq_anon`：当前 lruvec anon 类型最老 generation seq。
- `min_seq_file`：当前 lruvec file 类型最老 generation seq。
- `latest`：`seq == max_seq` 时为 `1`。
- `oldest`：`seq == min_seq[type]` 时为 `1`。

## 5. promote/depromote 修改说明

本次把移动 folio 的公共逻辑抽成：

```c
static int mglru_move_folio_locked(struct lruvec *lruvec, struct folio *folio,
				   int new_gen)
```

该函数要求调用方已经持有：

```c
lruvec->lru_lock
```

核心逻辑：

```c
old_gen = folio_lru_gen(folio);
flags = ((new_gen + 1UL) << LRU_GEN_PGOFF) | BIT(PG_workingset);
set_mask_bits(&folio->flags, LRU_GEN_MASK | LRU_REFS_FLAGS, flags);
lru_gen_update_size(lruvec, folio, old_gen, new_gen);
```

这里做了三件事：

1. 修改 folio flags 中的 MGLRU generation。
2. 设置 `PG_workingset`，保持和 MGLRU 热化路径一致。
3. 调用 `lru_gen_update_size()` 更新 MGLRU 各 generation 的页数统计。

`promote` 目标 generation：

```c
static int mglru_promote_folio_locked(struct lruvec *lruvec, struct folio *folio)
{
	return mglru_move_folio_locked(lruvec, folio,
				       lru_gen_from_seq(lruvec->lrugen.max_seq));
}
```

`depromote` 目标 generation：

```c
static int mglru_depromote_folio_locked(struct lruvec *lruvec, struct folio *folio)
{
	int type = folio_is_file_lru(folio);

	return mglru_move_folio_locked(lruvec, folio,
				       lru_gen_from_seq(lruvec->lrugen.min_seq[type]));
}
```

PFN 到 folio 的公共移动逻辑：

```c
static int mglru_move_pfn(unsigned long pfn,
			  int (*move_folio)(struct lruvec *lruvec, struct folio *folio))
```

该函数负责：

1. 通过 `pfn_to_online_page()` 和 `page_folio()` 获取 folio。
2. `folio_try_get()` 增加引用，避免 folio 在操作期间被释放。
3. 获取 `folio_lruvec(folio)`。
4. 持有 `lruvec->lru_lock`。
5. 检查 folio 是否仍在 LRU 上。
6. 调用传入的 `move_folio()`。
7. 调用 `list_move()` 把 folio 链表节点移动到目标 generation 的链表。
8. 解锁并 `folio_put()`。

需要注意：`mglru_move_pfn()` 必须调用传入的函数指针：

```c
gen = move_folio(lruvec, folio);
```

不能固定调用 `mglru_promote_folio_locked()`，否则 `depromote` 命令会实际执行 promote。

## 6. 命令解析修改说明

命令解析函数：

```c
static int mglru_page_policy_parse_line(char *line)
```

新增 `query` 分支：

```c
if (argc == 2 && !strcmp(argv[0], "query")) {
	if (mglru_parse_ulong(argv[1], &pfn))
		return -EINVAL;

	mglru_page_query_set(pfn);
	return 0;
}
```

新增 `promote` 分支：

```c
if (argc == 3 && !strcmp(argv[0], "promote")) {
	if (mglru_parse_ulong(argv[1], &pfn) ||
	    mglru_parse_ulong(argv[2], &nr_pages))
		return -EINVAL;

	return mglru_apply_pfn_range(pfn, nr_pages, mglru_promote_policy_pfn,
				     NULL);
}
```

新增 `depromote` 分支：

```c
if (argc == 3 && !strcmp(argv[0], "depromote")) {
	if (mglru_parse_ulong(argv[1], &pfn) ||
	    mglru_parse_ulong(argv[2], &nr_pages))
		return -EINVAL;

	return mglru_apply_pfn_range(pfn, nr_pages, mglru_depromote_policy_pfn,
				     NULL);
}
```

命令帮助输出函数：

```c
static int mglru_page_policy_show(struct seq_file *m, void *v)
```

需要包含：

```text
#   query <pfn>
#   promote <pfn> <nr_pages>
#   depromote <pfn> <nr_pages>
```

## 7. 修改后的最小编译检查

只想快速检查 `mm/vmscan.c` 是否能编译，可以先编译单个对象：

```bash
make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru -j"$(nproc)" mm/vmscan.o
```

这个命令只验证 `vmscan.c` 到 `vmscan.o` 的编译阶段，能快速发现语法错误、函数签名错误、未声明变量等问题。

但是它不会生成可启动内核镜像，也不会把修改安装到 `/boot`。

## 8. 为什么还需要重新生成 bzImage

`mm/vmscan.c` 是 built-in 内核代码，不是独立 `.ko` 模块。

因此修改后不能通过 `insmod`、`rmmod`、`modprobe` 单独替换，也不需要 `modules_install`。

正确的最小路径是：

```text
mm/vmscan.o
vmlinux
arch/x86/boot/bzImage
make install
update-grub
reboot
```

也就是说：

- 不需要重新完整清理构建目录。
- 不需要重新编译全部模块。
- 需要重新链接内核镜像。
- 需要安装新内核并重启后才能运行新代码。

## 9. 增量生成 bzImage

执行：

```bash
make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru -j"$(nproc)" bzImage
```

成功时应看到类似输出：

```text
Kernel: arch/x86/boot/bzImage is ready
```

本次实际构建成功输出为：

```text
Kernel: arch/x86/boot/bzImage is ready  (#3)
```

如果中途出现 warning，不一定表示失败。判断是否失败主要看最后退出码，以及是否出现 `Error`、`make: ***`。

## 10. 安装新内核

`bzImage` 生成成功后，执行：

```bash
sudo make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru install
```

该命令通常会把以下文件安装到 `/boot`：

```text
vmlinuz-<kernel-version>
System.map-<kernel-version>
config-<kernel-version>
initrd.img-<kernel-version>
```

具体版本号以当前构建结果为准。

如果 sudo 提示：

```text
[sudo] password for lzx:
```

需要在终端输入当前用户密码。没有 sudo 权限时无法写入 `/boot`，安装会停止。

## 11. 更新 grub

安装完成后执行：

```bash
sudo update-grub
```

确认输出中能看到新内核条目。重点关注类似：

```text
Found linux image: /boot/vmlinuz-...
Found initrd image: /boot/initrd.img-...
```

如果没有发现新内核，需要先检查 `make install` 是否成功。

## 12. 重启进入新内核

确认安装和 grub 更新完成后重启：

```bash
sudo reboot
```

重启后先确认当前运行内核：

```bash
uname -r
```

期望版本包含本次构建使用的本地版本后缀：

```text
-mglru
```

例如：

```text
6.17.13-mglru
```

实际版本以本机构建出的版本为准。

## 13. 重启后的接口验证

确认 debugfs 已挂载：

```bash
mount | grep debugfs || sudo mount -t debugfs debugfs /sys/kernel/debug
```

确认接口存在：

```bash
sudo ls -l /sys/kernel/debug/lru_gen_pages
```

查看帮助：

```bash
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望能看到：

```text
#   query <pfn>
#   promote <pfn> <nr_pages>
#   depromote <pfn> <nr_pages>
```

## 14. promote 验证流程

以 PFN `2150528` 为例：

```bash
pfn=2150528
```

先查询原始状态：

```bash
echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

执行 promote：

```bash
echo "promote $pfn 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

再次查询：

```bash
echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

判断成功条件：

```text
latest == 1
```

或者：

```text
seq == max_seq
```

## 15. depromote 验证流程

以 PFN `2150528` 为例：

```bash
pfn=2150528
```

执行 depromote：

```bash
echo "depromote $pfn 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

再次查询：

```bash
echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

判断成功条件：

```text
oldest == 1
```

或者：

```text
anon 页: seq == min_seq_anon
file 页: seq == min_seq_file
```

具体看 query 输出里的 `type` 字段。

## 16. 常见问题

### 16.1 只编译 vmscan.o 后为什么接口没变化

因为 `mm/vmscan.c` 是 built-in 代码。只生成 `mm/vmscan.o` 不会改变当前正在运行的内核。

必须继续生成 `bzImage`、安装到 `/boot`、更新 grub 并重启。

### 16.2 是否需要 modules_install

本次不需要。

原因是本次修改的是 built-in 内核代码，不是内核模块。除非同时修改了 `.ko` 模块或模块 ABI，否则不需要：

```bash
sudo make modules_install
```

### 16.3 sudo install 卡住

如果看到：

```text
[sudo] password for lzx:
```

说明正在等待输入用户密码。需要在终端输入密码并回车。

如果没有输入密码，`make install` 不会继续，也不会写入 `/boot`。

### 16.4 query 输出 error=ENOENT

表示该 PFN 当前无法通过 `pfn_to_online_page()` 找到 online page，常见原因：

- PFN 输入错误。
- 输入了裸十六进制字符串，例如 `20d080`，应写成 `0x20d080`。
- 该页已经不 present。
- 目标进程或映射已经变化。

### 16.5 query 输出 lru 为 0

表示 folio 当前不在 LRU 上。此时 `promote`/`depromote` 会失败或无实际效果。

建议换一个 present 且稳定的 PFN，或者重新从 `page_data.tsv` 获取当前 PFN。

## 17. 推荐的完整操作顺序

修改 `mm/vmscan.c` 后，推荐按以下顺序执行：

```bash
cd /home/lzx/Desktop/huawei/huawei_mem/lzx/MGLRU-test/mglru_kernel_transfer

SRC=$PWD/linux-hwe-6.17-6.17.0
BUILD=$PWD/linux-hwe-6.17-mglru-build

make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru -j"$(nproc)" mm/vmscan.o
make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru -j"$(nproc)" bzImage
sudo make -C "$SRC" O="$BUILD" LOCALVERSION=-mglru install
sudo update-grub
sudo reboot
```

重启后：

```bash
uname -r
sudo cat /sys/kernel/debug/lru_gen_pages
```

再执行：

```bash
pfn=2150528

echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages

echo "promote $pfn 1" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages

echo "depromote $pfn 1" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "query $pfn" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

