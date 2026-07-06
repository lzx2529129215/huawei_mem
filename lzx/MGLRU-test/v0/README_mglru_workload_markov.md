# MGLRU Pull-Based Workload Markov MVP

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
- reclaim 路径调用、预测、节流、missing hint 计数。

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

## 插入点

当前在两个低侵入位置调用：

- `mglru_page_policy_reheat()`
- `mglru_page_policy_can_isolate()`

调用入口是：

```c
mglru_markov_on_mglru_reclaim(folio, sc);
```

它只做有限次数 hash lookup、100ms 节流、hint 更新和 `pr_debug_ratelimited()`，
不影响原有返回值。

## 锁与分配

- 使用一个内部自旋锁 `mglru_workload_markov_lock` 保护 app state、history、
  transition 和 hint 表。
- debugfs write 可以 `GFP_KERNEL` 分配。
- reclaim 路径不分配内存，只 lookup 已存在的 history、transition 和 hint。
- `workload update` 会为对应 `cgroup_id/app_id` 预创建 history 和 hint slot。
- Markov 查表使用 hash table，热路径只查当前 app 和最多 4 个 predicted app，
  不遍历全部 app 或全部 hint。
- 同一个 history 使用 `last_predict_ns` 做 100ms 节流。

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

随后触发 MGLRU reclaim/aging 路径后，再次 `cat` 应看到 `reclaim_calls`、
`predictions` 和对应 `hint` 更新。

## 当前编译前置条件

该 kernel tree 当前缺少 `.config` / `include/config/auto.conf`，直接执行：

```bash
make -C MGLRU-test/v0/mglru_kernel_transfer/linux-hwe-6.17-6.17.0 mm/vmscan.o
```

会在配置阶段失败。需要先准备内核 `.config` 并运行 `make oldconfig` 或等价配置生成流程。
