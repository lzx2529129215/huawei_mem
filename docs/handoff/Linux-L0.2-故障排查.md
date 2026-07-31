# Linux L0.2 故障排查

先保留命令输出和脚本日志；不要跳过固定 SHA、pristine manifest 或 exact patch gate。

| 现象 | 诊断 | 安全处理 | 禁止做法 |
|---|---|---|---|
| URL 下载失败 | `curl -fIL https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.17.tar.xz` | 脚本会重试；若代理 TLS 失败，会对同一 URL 直连重试，仍失败则人工确认网络 | 改用 latest、个人镜像或不明压缩包 |
| SHA256 不一致 | `sha256sum linux-6.17.tar.xz` | 删除损坏缓存后重新下载 | 修改清单接受近似源码 |
| pristine 清单不一致 | `verify_source_manifest` 输出前 80 行 diff | 使用空目标重新 fetch | 在补丁后运行 pristine 校验 |
| patch does not apply | `git apply --check -p1/-p2` | 确认源码未被修改且补丁顺序正确 | `--3way`、`--reject`、手工猜测上下文 |
| 重复应用 | 脚本输出 `ALREADY_APPLIED` | 继续后续阶段 | 再次强行 apply |
| 缺依赖 | `check_environment.sh` | 按输出建议人工安装后重跑 | 脚本自动 apt install |
| 证书错误 | 查看 build.log 中 `system_keyring`/certificate | 检查 trusted/revocation keys 是否为空 | 直接改内核证书逻辑 |
| `pahole`/BTF 错误 | `grep CONFIG_DEBUG_INFO_BTF .config; command -v pahole` | 安装依赖或显式 `--disable-btf` | 静默关闭 BTF |
| 磁盘不足 | `df -h` | 清理明确的 generated `work/`/`builds/` 或换盘 | 删除当前内核、备份或源码证据 |
| OOM/编译过慢 | `free -h` | 使用 `--jobs 1`/`--jobs 2`，保持 swap | 修改补丁语义或强开高并发 |
| `heartbeat.o` 缺失 | `find builds -name heartbeat.o` | 先跑 configure/prepare，再重跑 build | 宣称完整构建通过 |
| `mm_inline.h` 依赖错误 | 查看 observer 编译的第一条错误 | 使用 exact v6.17 基线并保留完整日志 | 从当前 ignored 源码拷贝文件 |
| trace producer 参数超限 | `test_trace_event_arg_limits.py include/trace/events/myself_kswapd.h` | 修正 ABI 或停止交接 | 把超限接口当作可接受 |
| Secure Boot 阻止启动 | `mokutil --sb-state` | 在直接监督下处理签名或选择旧内核 | 自动改 GRUB 默认项或无人值守重启 |
| GRUB 不显示新内核 | 检查 `/boot`、`update-grub` 输出 | 使用旧内核启动并人工检查安装 | 重启或 force push |
| 启动失败 | 在 GRUB 选择旧内核并保存 dmesg | 回退到原内核，保留新内核日志 | 删除可用旧内核 |
| debugfs/tracefs 缺失 | `mount | rg 'debugfs|tracefs'`、检查目录 | 只读报告 `NOT RUN / ENVIRONMENT BLOCKED` | 永久修改挂载/sysfs |
| MGLRU guard 不允许 classic snapshot | `cat /sys/kernel/mm/lru_gen/enabled` | 保持 guard，改做 read-only 检查 | 伪装 MGLRU 为 classic LRU |
| 没有 trace 事件 | `find "$TRACEFS/events/myself_kswapd"` | 记录环境阻塞并检查运行 kernelrelease | 猜测事件已经产生 |
| parser 失败 | 保存 raw trace 和 parser stderr | 先验证 ABI/字段版本，再修 parser | 丢弃 raw 数据或改写历史报告 |

所有失败状态都应在交接验证报告中保留为 `FAILED` 或 `NOT RUN / ENVIRONMENT BLOCKED`。
