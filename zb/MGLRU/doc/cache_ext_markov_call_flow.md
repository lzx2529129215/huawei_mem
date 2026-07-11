# cache_ext_markov + mglru_page_control 调用流程分析

## 问题

```text
MGLRU 一轮 scan / reclaim 开始前
    ↓
调用一次 Markov
    ↓
生成本轮 reclaim-cycle hint
    ↓
后续扫描 folio 时不再调用 Markov
    ↓
仍按原始 MGLRU generation 逻辑扫描、隔离、淘汰
```

这个是否是 `merged_cache_ext.patch` 加上 `zb/MGLRU/ebpf/` 当前 eBPF 代码后的逻辑？

## 回答

**是。当前 eBPF 模式已经是 reclaim-cycle 级别预测，而不是 per-folio BPF/Markov 判断。**

依据：

```text
zb/MGLRU/merged_cache_ext.patch
zb/MGLRU/ebpf/cache_ext_policy.bpf.c
zb/MGLRU/ebpf/cache_ext_libbpf_loader.c
zb/MGLRU/ebpf/cache_ext_bpf_common.h
```

---

### 1. 第一阶段：一轮 reclaim scan 开始

`merged_cache_ext.patch` 在 `mm/vmscan.c` 的 `isolate_folios()` 开始处加入：

```c
#ifdef CONFIG_CACHE_EXT
	cache_ext_begin_reclaim_cycle(sc);
#endif
```

这个位置表示：MGLRU 已经进入本轮 reclaim scan，cache_ext 在 folio isolation 循环前刷新本轮预测 hint。

该 hook 不改变 reclaim 的触发条件，也不改变 MGLRU 原有 scan 框架。

---

### 2. 第二阶段：调用一次 eBPF Markov 预测

`mm/cache_ext.c` 中 `cache_ext_begin_reclaim_cycle()` 构造 cycle 级别上下文：

```c
struct cache_ext_bpf_cycle_ctx ctx = {};

ctx.app_id = app_id;
ctx.cycle_seq = cycle_seq;
ret = cache_ext_bpf_predict(&ctx);
```

eBPF 程序挂载点是：

```c
SEC("fmod_ret/cache_ext_bpf_predict")
int BPF_PROG(cache_ext_predict_policy,
	     struct cache_ext_bpf_cycle_ctx *cycle_ctx)
```

eBPF 只读取：

```text
history_map
markov_map
```

查表逻辑：

```text
app_id
    ↓
history_map 得到最近 4 个 op_id
    ↓
markov_map 用 app_id + ctx[4] 查 top-1 next_op
    ↓
返回 next_op
```

`prob` 不参与运行时计算，loader 已按 `count` 选择 top-1 转移。

---

### 3. 第三阶段：生成本轮 reclaim-cycle hint

如果 `cache_ext_bpf_predict()` 返回有效操作编号：

```c
cache_ext_state.predicted_next_op = (u16)ret;
atomic64_inc(&cache_ext_state.predicted_updates);
atomic64_inc(&cache_ext_state.active_hint_updates);
atomic64_inc(&cache_ext_state.bpf_predict_hits);
```

这表示本轮 cycle 的 active hint 已经更新。

对应统计语义：

```text
cycle_refreshes       +1
bpf_predict_calls     +1
bpf_predict_hits      +1
predicted_updates     +1
active_hint_updates   +1
```

如果 eBPF 未命中 Markov，`predicted_next_op` 置 0，并增加 miss 或 error 统计。

---

### 4. 第四阶段：后续扫描 folio 时不再调用 Markov

当前 active eBPF 程序只接收：

```c
struct cache_ext_bpf_cycle_ctx
```

它不接收 `struct folio`，不读取 folio 字段，不比较文件页范围。

`cache_ext_policy.bpf.c` 中仍保留：

```c
SEC("fmod_ret/cache_ext_bpf_decide")
int BPF_PROG(cache_ext_policy_compat,
	     struct cache_ext_bpf_ctx *bpf_ctx)
{
	(void)bpf_ctx;

	return 0;
}
```

这是兼容 stub，不参与当前 folio keep 决策。

因此后续 folio 路径不会重新调用 Markov，也不会从 folio 循环进入 eBPF 查 profile。

---

### 5. 第五阶段：folio 热路径只做内核侧 profile 匹配

MGLRU aging 路径：

```text
cache_ext_aging_should_promote(folio)
    ↓
cache_ext_match_folio(folio, true)
    ↓
命中则 promote 到较新的 generation
```

MGLRU reclaim isolation 路径：

```text
cache_ext_can_isolate(folio)
    ↓
cache_ext_match_folio(folio, true)
    ↓
命中则返回 false，阻止 isolate/reclaim
```

匹配条件：

```text
cache_ext enabled
app_id 匹配
current_predicted_next_op 匹配 profile.op_id
folio 是 file-backed
dev_major/dev_minor 匹配 inode superblock dev
ino 匹配 inode->i_ino
folio index range 与 profile index range 有交集
```

folio 范围：

```text
folio_start = folio->index
folio_end   = folio->index + folio_nr_pages(folio) - 1
```

交集判断：

```text
folio_start <= profile.index_end &&
folio_end >= profile.index_start
```

---

### 6. 完整调用链

```text
MGLRU reclaim 触发
  ↓
isolate_folios()
  ↓
cache_ext_begin_reclaim_cycle(sc)
  ↓
cache_ext_bpf_predict(cycle_ctx)
  ↓
eBPF: history_map + markov_map
  ↓
返回 next_op
  ↓
kernel 更新 current_predicted_next_op
  ↓
进入原始 MGLRU folio scan / isolation 循环
  ↓
每个 folio 调用 cache_ext_can_isolate(folio)
  ↓
kernel-side profile 匹配
  ↓
命中：阻止 isolate/reclaim
未命中：继续原始 MGLRU reclaim 逻辑
```

aging 路径：

```text
MGLRU aging / look-around
  ↓
cache_ext_aging_should_promote(folio)
  ↓
kernel-side profile 匹配
  ↓
命中：promote，并在实际提升后记录 aging_promoted
未命中：继续原始 MGLRU generation 逻辑
```

---

### 7. 统计语义

aging 阶段命中：

```text
aging_calls        +1
profile_hits       +1
protected_folios   +1
aging_hits         +1
aging_promoted     +1（实际完成提升后）
```

reclaim 阶段命中：

```text
profile_hits       +1
protected_folios   +1
skipped_reclaim    +1
```

BPF reclaim-cycle 预测成功：

```text
cycle_refreshes       +1
bpf_predict_calls     +1
bpf_predict_hits      +1
predicted_updates     +1
active_hint_updates   +1
```

debugfs 手动设置 predicted_op：

```text
predicted_updates     +1
active_hint_updates   +1
```

---

### 8. 验证标准

触发 reclaim 后，下面关系应成立：

```text
bpf_predict_calls 随 reclaim cycle 增长
aging_calls 可明显大于 bpf_predict_calls
bpf_predict_calls 不应接近 folio 扫描数量
profile_hits/protected_folios/skipped_reclaim 只在 profile 命中时增长
```

代码级检查：

```bash
grep -R "cache_ext_bpf_predict" -n mm/cache_ext.c mm/vmscan.c
grep -R "cache_ext_bpf_decide" -n mm/cache_ext.c
grep -R "cache_ext_bpf_should_keep" -n mm include || true
```

期望：

```text
cache_ext_bpf_predict 只由 cache_ext_begin_reclaim_cycle 调用
cache_ext_bpf_decide 只作为兼容 stub 存在
cache_ext_bpf_should_keep 不存在
```

---

### 9. 总结

当前最终逻辑可以概括为：

```text
cycle-level BPF Markov prediction
    +
per-folio kernel profile match
    +
原始 MGLRU generation scan/isolate/reclaim 流程
```

也就是说，eBPF 模式已经变成：

```text
一轮 reclaim scan 调一次 Markov，生成本轮 hint；
后续每个 folio 不再调用 Markov，只按 hint 做内核侧 profile 匹配。
```
