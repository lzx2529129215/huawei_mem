# Linux 6.17 `myself_kswapd` L0.1

本目录提供一个只观察原生 Linux 6.17 `kswapd` 的适配层。它只在
`balance_pgdat()` 的请求、完成的优先级回收轮和请求结束位置读取已有局部
状态并发出 tracepoint；不替换、暂停、改变或重新实现原生回收控制流。

## 编译配置

在 Linux 6.17 源码树中启用 `CONFIG_MYSELF_KSWAPD=y`。该选项依赖 `MMU`、
`MEMCG`、`TRACING`，默认关闭且不是模块。仅测试纯函数时可额外启用
`CONFIG_MYSELF_KSWAPD_KUNIT_TEST=y`。本实现不启用 MGLRU；若目标内核使用
MGLRU，应在采集报告中明确记录 `lru_gen_enabled` 的运行时状态。

```text
CONFIG_MYSELF_KSWAPD=y
CONFIG_MYSELF_KSWAPD_KUNIT_TEST=y
```

## 事件和捕获

事件组为 `myself_kswapd`，包含 `request_begin`、`priority_round` 和
`request_end`。捕获期间脚本一次性启用三个事件，压力命令结束后保存 trace，
不会在压力过程中动态切换事件。

```bash
tools/myself_kswapd/capture_kswapd_trace.sh output/trace-run stress-ng --vm 1 --vm-bytes 75% --timeout 10s
python3 tools/myself_kswapd/parse_kswapd_trace.py \
    output/trace-run/trace.txt --output-dir output/trace-run/csv
```

脚本同时保存可用的 tracefs 统计项前后值。若 tracefs 不可写、事件不存在或
没有管理员权限，脚本会直接失败，不会伪造采集结果。

## CSV 和完整性

解析器生成 `kswapd_requests.csv`、`kswapd_rounds.csv` 和
`kswapd_efficiency.csv`。请求表保留缺失 begin/end、round 序列错误、总量不符
和内核 validation flag；不完整请求的效率为空，也不会进入效率汇总。
分母为零时效率为空。`round_seq` 从每个请求的 0 开始持续递增，`pass_seq`
只在真实的 boost/cache-trim `goto restart` 后递增，因此相同 priority 可以出现
在连续的不同 round 中。

## 限制

这是 L0.1 Observe-Only 版本：没有预测策略、用户态回收动作、Linux 行为替换、
异步指针、内核分配、锁、睡眠或 I/O。未重启到带此适配层的内核前，不能声称
已完成真实运行时 trace 验证；构建和离线解析测试不等价于运行时验证。

## L0.3A 页生命周期离线重放

L0.3A 的页级事件使用独立 parser 和状态机 oracle，不复用内核转换代码：

```bash
python3 tools/myself_kswapd/parse_page_lifecycle_trace.py \
    output/page-lifecycle.trace --json \
    --csv output/page-lifecycle-transitions.csv
```

summary 区分 `LATE_DISCOVERY`、`TRACE_TRUNCATION` 和真正的
`INVALID_TRANSITION`。CSV 按 `(page_id,lifecycle_gen)` 保留每次转换及其
request/priority/scan 关联。parser 只精确匹配事件字段，不从 payload 内搜索
相似文本。
