# MGLRU 拉取式 Workload Markov 机制

本文档说明 `MGLRU-test/v0/mglru_kernel_transfer/linux-hwe-6.17-6.17.0/mm/vmscan.c`
中的 workload Markov observe-only MVP。

## 目标

该版本不让 workload monitor 主动触发 Markov，而是在 MGLRU 进入 reclaim
相关路径时，由 MGLRU 主动读取已经维护好的 app/workload 历史和 Markov 转移表，
生成 reclaim hint。第一版只观察和展示 hint，不改变 reclaim 行为。

本版本明确不做以下动作：

- 不使用 eBPF；
- 不新增 BPF kfunc；
- 不把 promote/depromote/protect 暴露给 eBPF；
- 不调用 `lru_gen_pages` 背后的 promote/depromote/protect 函数；
- 不改变 `mglru_page_policy_reheat()` 和 `mglru_page_policy_can_isolate()` 的返回值；
- 不改变 generation、folio 所在 LRU、scan skip/only/protect 策略；
- 不引入预取、主动驱逐、swap 修改或新的 MGLRU 策略动作。

## 新增 debugfs

```text
/sys/kernel/debug/lru_gen_workload_markov
```

支持 `cat` 展示：

- current app state；
- predicted app 列表；
- workload histories；
- Markov transition entries；
- reclaim hints；
- reclaim cycle prepare、预测、节流、missing hint 计数。

## 支持的写命令

```bash
echo "app current <app_id> <cgroup_id> <ttl_ms>" > /sys/kernel/debug/lru_gen_workload_markov
echo "app predict <ttl_ms> <app_id1> <conf1> [<app_id2> <conf2> ...]" > /sys/kernel/debug/lru_gen_workload_markov
echo "workload update <cgroup_id> <app_id> <workload_id>" > /sys/kernel/debug/lru_gen_workload_markov
echo "markov set <app_id> <prev_workload> <current_workload> <next1> <conf1> <boost1> [<next2> <conf2> <boost2> ...]" > /sys/kernel/debug/lru_gen_workload_markov
echo "clear all" > /sys/kernel/debug/lru_gen_workload_markov
echo "clear histories" > /sys/kernel/debug/lru_gen_workload_markov
echo "clear markov" > /sys/kernel/debug/lru_gen_workload_markov
echo "clear hints" > /sys/kernel/debug/lru_gen_workload_markov
```

`confidence` 使用 `0..10000` 整数定点值。

## 调用语义与插入点

旧版本在 `sort_folio()` 的 reheat 检查后以及 `isolate_folio()` 的
can-isolate 检查后调用 Markov。这两个位置均处于 folio 级扫描路径，会随着
扫描 folio 数量重复执行。

新版本已移除上述两个 folio 级调用，改为在：

```c
evict_folios()
  -> mglru_markov_prepare_reclaim(lruvec, sc, __func__)
  -> spin_lock_irq(&lruvec->lru_lock)
  -> isolate_folios(...)
```

中执行。`evict_folios()` 每次 eviction batch 只 prepare 一次，然后仍按原有
MGLRU generation 逻辑扫描、隔离和回收 folio。prepare 位于 `lruvec->lru_lock`
加锁前，不增加 folio 扫描锁的持有时间。

同一 `lruvec/cgroup/app` 在 50ms 内的重复 prepare 会被 observe-only 节流。
节流只跳过 Markov 查询，不跳过或改变原始 reclaim。

## Generation adjustment 预留点

`mglru_markov_prepare_reclaim()` 在完成查询后调用：

```c
mglru_markov_apply_generation_adjustment(...)
```

该函数当前严格为 no-op，只输出受限的 `pr_debug` 信息。它不接收或遍历 folio，
不修改 generation，不调用 promote/depromote/protect，也不改变 scan、
isolate、aging 或 reclaim 结果。该位置仅为后续
`predicted_workload -> page hint -> generation adjustment` 预留。

## 锁与分配

- 使用一个内部自旋锁 `mglru_workload_markov_lock` 保护 app state、history、
  transition 和 hint 表。
- debugfs write 可以 `GFP_KERNEL` 分配。
- reclaim cycle prepare 不分配内存，只查找已存在的 app、transition 和 hint。
- `workload update` 会为对应 `cgroup_id/app_id` 预创建 history 和 hint slot。
- 当前固定容量表采用线性查找；由于 prepare 已从 folio 级路径迁移到 batch 级，
  不会按扫描 folio 数量重复查表。
- 每个 app 条目记录最近的 `lruvec` 和 prepare 时间，对同一
  `lruvec/cgroup/app` 执行 50ms 节流。

## Debugfs 统计语义

```text
stat reclaim_calls       <n>
stat prepare_calls       <n>
stat per_folio_calls     <n>
stat predictions         <n>
stat throttled_prepare   <n>
stat missing_hint        <n>
stat missing_app         <n>
```

- `reclaim_calls`：兼容旧字段，当前与 `prepare_calls` 同步递增，表示进入
  cycle-level prepare 的次数；
- `prepare_calls`：`evict_folios()` 批次开始前的 Markov prepare 次数；
- `per_folio_calls`：folio 级 Markov 调用次数，新版本应始终为 0；
- `predictions`：找到匹配 Markov transition 并刷新 hint 的次数；
- `throttled_prepare`：同一 reclaim 目标在 50ms 内被跳过的 prepare 次数；
- `missing_hint`、`missing_app`：prepare 查找失败计数。

## 测试示例

```bash
cat /sys/kernel/debug/lru_gen_workload_markov

echo "app current 1 12345 300000" > /sys/kernel/debug/lru_gen_workload_markov
echo "app predict 180000 1 8000 2 5000" > /sys/kernel/debug/lru_gen_workload_markov
echo "workload update 12345 1 0" > /sys/kernel/debug/lru_gen_workload_markov
echo "workload update 12345 1 2" > /sys/kernel/debug/lru_gen_workload_markov
echo "markov set 1 0 2 3 9000 2" > /sys/kernel/debug/lru_gen_workload_markov
cat /sys/kernel/debug/lru_gen_workload_markov
```

随后触发 MGLRU reclaim 路径，再次 `cat` 应看到 `prepare_calls` 增长、
`per_folio_calls` 保持 0，并根据 transition 匹配情况更新 `predictions` 和
对应 `hint`。

## 编译验证

沿用独立构建目录：

```bash
cd MGLRU-test/v0/mglru_kernel_transfer/linux-hwe-6.17-6.17.0
make O=../linux-hwe-6.17-mglru-build LOCALVERSION=-mglru mm/vmscan.o
```
