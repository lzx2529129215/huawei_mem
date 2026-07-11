# MGLRU lru_gen_pages 验证说明

本文档说明如何使用 `mem_analyze-v3` 已导出的 PFN，验证实验内核中的页级 MGLRU 控制接口：

```text
/sys/kernel/debug/lru_gen_pages
```

当前实验目标不是再次编译内核，而是确认这些接口对指定 PFN/head PFN 的行为是否符合预期：

- `query`：查询指定 PFN 当前所属 folio 的 MGLRU 状态。
- `promote`：手动把指定 folio 提升到最新 MGLRU generation。
- `depromote`：手动把指定 folio 降到其类型对应的最老 MGLRU generation。
- `protect`：让指定 folio 在 MGLRU eviction 路径中被跳过并重新热化。
- `scan skip`：在指定 reclaim priority 范围内跳过指定 folio。
- `scan only`：在指定 reclaim priority 范围内只允许指定 folio 继续进入 isolate/reclaim。
- `clear all`：清空所有实验策略。

## 1. 环境前提

确认当前运行的是实验内核：

```bash
uname -r
```

期望输出包含：

```text
6.17.13-mglru
```

确认 MGLRU 已启用：

```bash
zgrep CONFIG_LRU_GEN /proc/config.gz 2>/dev/null || grep CONFIG_LRU_GEN /boot/config-$(uname -r)
```

期望至少看到：

```text
CONFIG_LRU_GEN=y
CONFIG_LRU_GEN_ENABLED=y
```

确认 debugfs 已挂载：

```bash
mount | grep debugfs || sudo mount -t debugfs debugfs /sys/kernel/debug
```

确认接口存在。`/sys/kernel/debug` 通常需要 root 权限：

```bash
sudo ls -l /sys/kernel/debug/lru_gen /sys/kernel/debug/lru_gen_full /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

## 2. PFN 来源和格式

当前 PFN 数据来自：

```text
/home/lzx/Desktop/huawei/huawei_mem/lzx/mem/Linux/v3/mem_analyze_run_20260621_173459/details/pid_123669_firefox_details/page_data.tsv
```

`page_data.tsv` 字段为：

```text
addr    segment    section    status    code    pfn
```

只选择满足以下条件的页：

- `status` 为 `P`，表示 present。
- `pfn` 不为 `0`，表示 PFN 可见。
- 优先选择匿名页、堆页、数据页；文件只读页也能用于命令解析测试，但在压力验证中更容易被文件页回收、重读或共享行为干扰。

示例：你在 `part_008.md` 中选中的 PFN：

```text
PFN min=2150528, max=2150528
```

对应 `page_data.tsv` 中这一行：

```text
79429829d000    file/文件映射    libmozsandbox.so:.rodata    P    51    20d080
```

这里有一个格式差异：

- Markdown 摘要里的 `2150528` 是十进制。
- `page_data.tsv` 里的 `20d080` 是十六进制。
- 二者是同一个 PFN：`2150528 == 0x20d080`。

内核解析使用 `base=0`，所以推荐写入以下两种格式之一：

```text
2150528
0x20d080
```

不要写裸十六进制：

```text
20d080
```

裸 `20d080` 会被当作十进制解析，包含字母时会失败。

## 3. 从 page_data.tsv 挑选 PFN

查看 present 且 PFN 可见的页：

```bash
awk -F '\t' 'NR==1{print; next} $4=="P" && $6!="0" {print; c++; if(c==20) exit}' \
  /home/lzx/Desktop/huawei/huawei_mem/lzx/mem/Linux/v3/mem_analyze_run_20260621_173459/details/pid_123669_firefox_details/page_data.tsv
```

按地址查某个页，例如你当前选中的地址：

```bash
awk -F '\t' '$1=="79429829d000" {print}' \
  /home/lzx/Desktop/huawei/huawei_mem/lzx/mem/Linux/v3/mem_analyze_run_20260621_173459/details/pid_123669_firefox_details/page_data.tsv
```

十六进制 PFN 转十进制：

```bash
printf "%d\n" 0x20d080
```

十进制 PFN 转十六进制：

```bash
printf "0x%x\n" 2150528
```

## 4. lru_gen_pages 输出含义

读取接口：

```bash
sudo cat /sys/kernel/debug/lru_gen_pages
```

输出头部类似：

```text
# commands:
#   query <pfn>
#   promote <pfn> <nr_pages>
#   depromote <pfn> <nr_pages>
#   protect add|del <pfn> <nr_pages>
#   scan skip add|del <prio_min> <prio_max> <pfn> <nr_pages>
#   scan only add|del <prio_min> <prio_max> <pfn> <nr_pages>
#   clear all
# pfn flags skip_prio_min skip_prio_max only_prio_min only_prio_max hits
```

执行过 `query <pfn>` 后，再读取接口会额外输出查询结果：

```text
# query:
# input_pfn head_pfn nr_pages memcg_id nid type zone lru active gen seq max_seq min_seq_anon min_seq_file latest oldest
2150528 2150528 1 101 0 file 0 1 1 3 431 431 428 428 1 0
```

查询字段含义：

- `input_pfn`：用户输入的 PFN。
- `head_pfn`：该 PFN 所在 folio 的 head PFN。后续策略内部按 head PFN 管理。
- `nr_pages`：folio 覆盖的 4 KiB 页数。普通页通常为 1，大页会大于 1。
- `memcg_id`：内核 `mem_cgroup_id(memcg)`，对应 `/sys/kernel/debug/lru_gen` 中 `memcg` 后面的数字。
- `nid`：NUMA node id。
- `type`：`anon` 或 `file`。
- `zone`：内存 zone 编号。
- `lru`：folio 当前是否在 LRU 上，`1` 表示在，`0` 表示不在。
- `active`：该 folio 当前 generation 是否属于 MGLRU active generations。
- `gen`：folio flags 中的 MGLRU 环形 generation 下标。
- `seq`：根据 `gen` 和当前 `max_seq` 反推出来的全局 generation 序号。
- `max_seq`：该 memcg/node lruvec 当前最新 generation 序号。
- `min_seq_anon/min_seq_file`：该 lruvec 当前 anon/file 最老可回收 generation 序号。
- `latest`：`seq == max_seq` 时为 `1`，表示当前 folio 在最新 generation。
- `oldest`：`seq == min_seq[type]` 时为 `1`，表示当前 folio 在其类型对应的最老 generation。

策略行含义：

```text
pfn flags skip_prio_min skip_prio_max only_prio_min only_prio_max hits
```

- `pfn`：内核归一化后的 folio head PFN。
- `flags`：三位策略标记。
- `P`：protect 生效。
- `S`：scan skip 生效。
- `O`：scan only 生效。
- `-`：对应策略未设置。
- `skip_prio_min/skip_prio_max`：skip 策略作用的 reclaim priority 范围。
- `only_prio_min/only_prio_max`：only 策略作用的 reclaim priority 范围。
- `hits`：该 PFN 在 MGLRU reclaim 路径中被策略命中的次数。

示例：

```text
2150528 PS- 0 12 0 12 3
```

含义：

- PFN/head PFN 为 `2150528`。
- 设置了 protect 和 scan skip。
- skip priority 范围是 `[0, 12]`。
- only priority 范围字段虽然显示为 `0 12`，但因为 flags 中没有 `O`，only 不生效。
- reclaim 路径命中过 3 次。

## 5. 指令说明

### 5.0 query

格式：

```text
query <pfn>
```

示例：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

作用：

- 根据 PFN 找到 online folio。
- 输出该 folio 的 `head_pfn`、`memcg_id`、`nid`、`type`、`gen`、`seq`、`max_seq` 等状态。
- 用于验证 `promote` 是否把目标 folio 移动到了最新 generation。

判断标准：

```text
latest == 1
```

或：

```text
seq == max_seq
```

如果输出 `error=ENOENT`，表示当前 PFN 找不到 online page/folio，可能 PFN 已释放、离线或输入错误。

### 5.1 clear all

```bash
echo "clear all" | sudo tee /sys/kernel/debug/lru_gen_pages
```

作用：

- 删除所有 `protect`、`scan skip`、`scan only` 策略项。
- 不回滚已经发生的 `promote`，因为 `promote` 是一次性修改 folio generation。

验证：

```bash
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望：

- 只剩注释头。
- 没有策略行。

### 5.2 promote

格式：

```text
promote <pfn> <nr_pages>
```

示例：

```bash
echo "promote 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "promote 0x20d080 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

参数：

- `pfn`：目标 PFN。可以是普通 PFN，也可以是 folio head PFN。
- `nr_pages`：从 `pfn` 开始覆盖多少个 4 KiB 页。单页验证先用 `1`。

作用：

- 找到 PFN 所属 online folio。
- 归一化到 folio head PFN。
- 尝试将该 folio 移到当前 MGLRU 最新 generation。

注意：

- `promote` 不会在 `lru_gen_pages` 中留下持久策略项。
- 如果 PFN 无效、离线、不是 LRU folio、目标页已经不在原进程中，可能没有可观察效果或返回错误。

建议观察：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

`promote` 成功的直接判断：

- promote 前：`latest` 可能是 `0`。
- promote 后：`latest` 应为 `1`。
- promote 后：`seq` 应等于 `max_seq`。

### 5.3 depromote

格式：

```text
depromote <pfn> <nr_pages>
```

示例：

```bash
echo "depromote 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "depromote 0x20d080 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

参数：

- `pfn`：目标 PFN。可以是普通 PFN，也可以是 folio head PFN。
- `nr_pages`：从 `pfn` 开始覆盖多少个 4 KiB 页。单页验证先用 `1`。

作用：

- 找到 PFN 所属 online folio。
- 归一化到 folio head PFN。
- 根据 folio 类型选择最老 generation：
  - `type=anon` 时，目标为 `min_seq_anon` 对应的 generation。
  - `type=file` 时，目标为 `min_seq_file` 对应的 generation。
- 将该 folio 移到当前 MGLRU 最老 generation。

建议观察：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

`depromote` 成功的直接判断：

- depromote 后：`oldest` 应为 `1`。
- depromote 后：
  - 若 `type=anon`，`seq == min_seq_anon`。
  - 若 `type=file`，`seq == min_seq_file`。

注意：

- `depromote` 会让目标 folio 更接近 reclaim 候选，实验时建议先选择可恢复、可重新采样的页。
- 如果目标 folio 当前不在 LRU 上，或者 PFN 已释放/迁移，命令可能失败。

### 5.4 protect add / protect del

格式：

```text
protect add <pfn> <nr_pages>
protect del <pfn> <nr_pages>
```

示例：

```bash
echo "protect add 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages

echo "protect del 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

作用：

- `protect add`：添加硬保护策略。
- `protect del`：删除硬保护策略。

命中时的内核行为：

- 在 MGLRU eviction/isolate 路径中跳过该 folio。
- 将该 folio 重新热化到最新 generation。
- `hits` 加 1。

边界：

- 这不是 `mlock()`。
- 这不是 pin page。
- 它只影响我们插桩覆盖的 MGLRU reclaim 路径。
- 如果页已经被释放、映射变化、PFN 被复用，策略可能作用到后来的同 PFN folio。因此压力验证前后应重新采样确认目标页仍然对应同一 PFN。

### 5.5 scan skip add / scan skip del

格式：

```text
scan skip add <prio_min> <prio_max> <pfn> <nr_pages>
scan skip del <prio_min> <prio_max> <pfn> <nr_pages>
```

示例：

```bash
echo "scan skip add 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages

echo "scan skip del 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

参数：

- `prio_min/prio_max`：`scan_control.priority` 的闭区间。
- `0 12` 是较宽范围，适合初始验证。
- 内核会拒绝小于 0、大于 `DEF_PRIORITY` 或 `prio_min > prio_max` 的值。

作用：

- 当 reclaim priority 落入指定范围时，匹配 folio 不进入 isolate/reclaim。
- 命中后 folio 被重新热化。
- `hits` 增加。

适合验证：

- 目标页在压力下是否被跳过。
- `hits` 是否随 reclaim 增加。

### 5.6 scan only add / scan only del

格式：

```text
scan only add <prio_min> <prio_max> <pfn> <nr_pages>
scan only del <prio_min> <prio_max> <pfn> <nr_pages>
```

示例：

```bash
echo "scan only add 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages

echo "scan only del 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

作用：

- 在指定 priority 范围内启用 only 模式。
- 命中 only 集合的 folio 允许继续进入 isolate/reclaim。
- 未命中 only 集合的 folio 会被跳过。

风险：

- `scan only` 影响面比 `protect` 和 `scan skip` 大。
- 如果 only 集合太小，可能显著改变 reclaim 行为，导致回收效率下降。

建议：

- 先验证 `protect` 和 `scan skip`。
- `scan only` 放在最后测。
- 测试后立即 `clear all`。

## 6. 推荐验证流程

### 步骤 1：清空旧策略

```bash
echo "clear all" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

### 步骤 2：选一个 PFN

优先选堆页或匿名页：

```bash
awk -F '\t' 'NR>1 && $4=="P" && $6!="0" && ($2 ~ /heap|anon|data/) {print; c++; if(c==20) exit}' \
  /home/lzx/Desktop/huawei/huawei_mem/lzx/mem/Linux/v3/mem_analyze_run_20260621_173459/details/pid_123669_firefox_details/page_data.tsv
```

如果暂时只用你当前选中的页，则使用：

```text
pfn=2150528
```

或：

```text
pfn=0x20d080
```

### 步骤 3：验证 promote 是否进入最新 generation

先查询 promote 前状态：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

记录：

- `head_pfn`
- `memcg_id`
- `nid`
- `type`
- `gen`
- `seq`
- `max_seq`
- `latest`

执行 promote：

```bash
echo "promote 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
```

再查询 promote 后状态：

```bash
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望：

- `head_pfn` 与 promote 前一致。
- `memcg_id/nid/type` 与 promote 前一致，除非该页同时发生迁移或释放重分配。
- `latest=1`。
- `seq == max_seq`。

### 步骤 4：验证策略写入

如果要反向验证 depromote，执行：

```bash
echo "depromote 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "query 2150528" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望：

- `oldest=1`。
- 如果 `type=anon`，`seq == min_seq_anon`。
- 如果 `type=file`，`seq == min_seq_file`。

然后可以再次执行 `promote 2150528 1`，确认 `latest=1`，形成 promote/depromote 双向验证。

### 步骤 5：验证策略写入

```bash
echo "protect add 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望：

- 出现一行策略。
- `flags` 至少包含 `P`。
- `hits` 初始通常为 `0`。

### 步骤 6：制造 reclaim 压力

如果系统有 `stress-ng`：

```bash
stress-ng --vm 1 --vm-bytes 80% --timeout 30s
```

如果没有：

```bash
python3 - <<'PY'
import time
chunks = []
try:
    for _ in range(80):
        chunks.append(bytearray(64 * 1024 * 1024))
        time.sleep(0.05)
    time.sleep(20)
except MemoryError:
    time.sleep(10)
PY
```

压力结束后查看命中：

```bash
sudo cat /sys/kernel/debug/lru_gen_pages
```

期望：

- `hits` 增加，说明该 PFN 在 MGLRU reclaim 路径中被策略命中。

### 步骤 7：重新采样确认页状态

对同一 Firefox PID 再运行一次 `mem_analyze-v3`：

```bash
cd /home/lzx/Desktop/huawei/huawei_mem/lzx/mem/Linux/v3
sudo ./mem_analyze-v3 123669 -o firefox_after_protect.md
```

然后查目标地址或目标 PFN：

```bash
find . -path '*firefox_after_protect*' -name page_data.tsv -print
```

根据新生成的 `page_data.tsv` 检查：

- 目标虚拟地址是否仍 present。
- 目标地址对应 PFN 是否仍是原 PFN。
- 如果 PFN 改变，说明原物理页关系已经变化，不能继续用旧 PFN 证明同一页被保护。

### 步骤 8：测试 scan skip

清空后单独测试：

```bash
echo "clear all" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "scan skip add 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

再次施加内存压力，然后观察 `hits`。

### 步骤 9：测试 scan only

最后再测 only：

```bash
echo "clear all" | sudo tee /sys/kernel/debug/lru_gen_pages
echo "scan only add 0 12 2150528 1" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

再次施加内存压力，然后观察：

- only 策略行存在，flags 包含 `O`。
- `hits` 有变化。
- 系统 reclaim 行为是否明显异常。

测试结束必须清理：

```bash
echo "clear all" | sudo tee /sys/kernel/debug/lru_gen_pages
sudo cat /sys/kernel/debug/lru_gen_pages
```

## 7. 下一步要做什么

建议按下面顺序执行：

1. 先用 `sudo cat /sys/kernel/debug/lru_gen_pages` 确认接口可读。
2. 用 `query 2150528` 记录 promote 前状态。
3. 执行 `promote 2150528 1`。
4. 再用 `query 2150528` 记录 promote 后状态。
5. 判断 `latest=1` 或 `seq == max_seq`。
6. 执行 `depromote 2150528 1`。
7. 再用 `query 2150528` 记录 depromote 后状态。
8. 判断 `oldest=1`，或按 `type` 判断 `seq == min_seq_anon/min_seq_file`。
9. 可再次执行 `promote 2150528 1`，确认能回到 `latest=1`。
10. 用你当前选中的 PFN `2150528` 做一次 `protect add` 写入测试。
11. 读取 `lru_gen_pages`，确认策略行出现。
12. 施加一次 30 秒内存压力。
13. 再读 `lru_gen_pages`，看 `hits` 是否增加。
14. 对 Firefox PID 重新跑一次 `mem_analyze-v3`，确认目标虚拟地址 `79429829d000` 是否仍 present，以及 PFN 是否仍为 `2150528/0x20d080`。
15. 如果 `protect` 验证成立，再分别测试 `scan skip` 和 `scan only`。
16. 每轮实验后执行 `clear all`，避免旧策略污染下一轮。

如果第 5 步 `hits` 一直不增加，不要直接判定功能失败。常见原因是：

- 目标页太热，没有进入 MGLRU eviction 扫描候选。
- 内存压力不足，没有触发对应 memcg/node 的 reclaim。
- 目标 PFN 对应的是共享文件页，行为受 page cache 和共享映射影响。
- Firefox 已经释放或替换了该虚拟页。

这种情况下应换成堆页或匿名页，并提高内存压力后重测。
