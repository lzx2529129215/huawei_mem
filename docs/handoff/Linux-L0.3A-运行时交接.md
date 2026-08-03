# Linux L0.3A 运行时交接

## 当前冻结状态

Linux L0.3A 已合并到本地 main，构建并安装为 6.17.0-myks-l03a。
2026-08-03 已人工启动该内核并完成页级生命周期、Shadow Page Table、
L0.2 回归、小容量和 15 分钟 soak 验证。

当前判定：

    L0.3A RUNTIME SMOKE PARTIAL

PARTIAL 的唯一环境级主因是实际内核 CONFIG_LRU_GEN=n，无法取得 MGLRU guard
与开关恢复的真实运行证据。classic-LRU 下核心页状态机、容量和清理证据均已
通过。

## 关键结果

- running kernel：6.17.0-myks-l03a
- page trace：79,710 events，21,176 lifecycles
- page replay：0 parse issue、0 invalid、0 missing isolate、0 truncation
- anon/file：41,074 / 38,636 events
- L0.2：18 complete requests、301 rounds、81,312 snapshots
- max 4096：峰值 4096，关闭后 0
- max 128：峰值 128，capacity drop 增长，错误计数不增长，关闭后 0
- soak：15 分钟，峰值 1025，所有轮次退出后 0，无错误计数增长
- kernel severe warnings：0
- cleanup：PASS

## 证据与复核

- 仓库报告：docs/reports/linux-l03a-runtime-smoke.md
- 外部证据：
  /home/lzx/Desktop/huawei/outputs/linux-l03a-runtime-smoke-20260803
- 安装报告：
  /home/lzx/Desktop/huawei/linux-l03a-installation-report.md
- 安装前备份：
  /home/lzx/Desktop/huawei/linux-l03a-install-backup-20260802-232148

## 后续边界

只有人工接受上述 MGLRU 覆盖缺口后，才进入 L0.3B per-domain 四条 Shadow
LRU 链与一致性校验。不要从本交接自动开始 L0.3B；不要实现 policy 排序、
planner、executor 或内核回收执行器。
