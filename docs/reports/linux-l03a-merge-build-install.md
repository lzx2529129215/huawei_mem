# Linux L0.3A 合并、构建与安装阶段报告

日期：2026-08-02

## 达成目标

L0.3A 页级生命周期 observer 已通过合并前审查和完整回归，以 `--no-ff` 合并
到本地 main；merged main 已在全新 Linux 6.17 源码树中按 0002、0003、0004
补丁链完成全量构建，并安装为 `6.17.0-myks-l03a`。安装过程保留旧内核，
没有自动重启，也没有修改默认 GRUB 启动项。

## 证据摘要

- 合并提交：`4f96db11dd193e5f7a44e52640c180eb31d4beef`
- Python parser：29/29 通过。
- 默认与 sanitizer CTest：42/42 通过。
- 100 轮回归：4,200/4,200 通过。
- 配置矩阵、KUnit 对象、shell/handoff、严格补丁链：通过。
- 完整内核构建：退出码 0，内核版本 `6.17.0-myks-l03a`。
- 完整模块：6,755 个。
- 构建错误：0；7 条栈帧告警均已分类，无新增阻塞项。
- 安装镜像与构建镜像 SHA256 一致。
- initramfs、depmod、update-grub、GRUB 语法检查：通过。
- GRUB 项：`Ubuntu, with Linux 6.17.0-myks-l03a`。
- 安装前备份：
  `/home/lzx/Desktop/huawei/linux-l03a-install-backup-20260802-232148`。

## 当前边界

系统仍运行 `6.17.0-myks-l02-dirty`。L0.3A 真实运行时验证尚未执行，状态为：

```text
NOT RUN — HUMAN REBOOT CHECKPOINT
```

只有人工从 GRUB 选择新内核，并用 `uname -r` 确认
`6.17.0-myks-l03a` 后，才继续 observer、debugfs/tracefs、页生命周期事件、
容量边界和 soak 验证。main 在此之前不会推送。

完整外部报告：
`/home/lzx/Desktop/huawei/linux-l03a-installation-report.md`。
