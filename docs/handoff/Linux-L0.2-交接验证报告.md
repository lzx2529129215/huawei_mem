# Linux L0.2 交接验证报告

状态：`LINUX L0.2 CROSS-DEVICE HANDOFF COMPLETE`。本报告区分本次执行证据与历史证据；安装、GRUB 修改和重启均未执行。

## 固定来源

- 固定 URL：`https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.17.tar.xz`
- Linux：`6.17` / `v6.17` / `e5f0a698b34ed76002dc5cff3804a61c80233a7a`
- Archive SHA256：`9b607166a1c999d8326098121222feb080a20a3253975fcdfa2de96ba7f757a7`
- Pristine manifest：90,506 canonical paths，SHA256 `5291fc5e8fe33cbe00b491947bc79316baf3eb812d77b4e9f863ee884308dd09`
- 0002：`ecc0e4f473ea4a657578568b2a57658ed37590c1a89e366ede7c2c81814d2711`
- 0003：`35bacaea2de3aae1552f24564d853b0ffb352f7d9929091da3d6026d2cd70b89`

## 本次执行结果（2026-07-31）

| 项目 | 状态 | 证据 |
|---|---|---|
| 环境门禁 | PASS | 编译工具、依赖头文件、91 GiB 磁盘可用；内存不足 4 GiB 时明确使用 `--jobs 2`。 |
| 现有 Python 用户态测试 | PASS | `python3 -m unittest discover ...`：19 tests。 |
| 现有 CTest | PASS | `reclaim_tests`：1/1。 |
| handoff CLI、hash、manifest、目录 guard、文档路径测试 | PASS | `tests/handoff/` 全部通过。 |
| 首轮独立构建 | PASS | `bzImage + modules`，410 s，kernelrelease `6.17.0-myks-l02`。 |
| clean local clone | PASS | `/home/lzx/Desktop/huawei/linux-l02-handoff-clean-clone-20260731`，从 public URL 重新下载、manifest、严格 0002/0003、完整构建和 verifier 均通过；构建 411 s。 |
| actual remote clone | PASS | `/home/lzx/Desktop/huawei/linux-l02-handoff-remote-shallow-20260731` 直接 clone remote `main` 后，重新下载、SHA256、manifest、patch、configure，`mm/myself_kswapd/built-in.a`、`heartbeat.o`、`trace.o` 和 trace ABI gate 均通过。 |
| 补丁重复执行 | PASS | 完整 0002+0003 树中均报告 `ALREADY_APPLIED`；0002 通过 final-0003 state 加锚点验证。 |
| runtime smoke（只读） | PASS / READ-ONLY PREFLIGHT | 运行内核 `6.17.0-myks-l02-dirty`、`myself_kswapd` trace events 存在、MGLRU=`0x0007`。 |
| runtime trace/parser capture | NOT RUN / ENVIRONMENT BLOCKED | 当前会话没有 tracefs 写/trace 读权限；必须在直接监督下以 `--bounded-reclaim --output-dir DIR -- COMMAND` 运行。 |
| TSan | HISTORICAL_EVIDENCE / NOT RUN | 既有环境记录 `unexpected memory mapping`，本次未将其伪报为通过。 |

## 构建信息

- clean clone tested commit：`28fb7c3ef76e87265390b76e801d7204ee2c206c`
- remote clone tested/final code commit：`4ba84bb9d27650c9839d57c829154fc7ffdaa7c5`
- clean build：`/home/lzx/Desktop/huawei/linux-l02-handoff-clean-clone-20260731/builds/linux-6.17-l02`
- `bzImage`：`2566fb907ee4459c627bc78fe6776a129090a0562ce94d9b40b8e44f94c8dc5a`
- `vmlinux`：`458d55a46a3b82e49cb51e1333096f89351a053679e24d10ca22c4acfbf81304`
- `System.map`：`ccf5312f25c0e2d2ca27e7aad5e6626bbf624ea4d172783fe5a102a9f7d06f7d`
- `Module.symvers`：`6e559ac9df621cdfa4d4f6b3741395049dc6a0f822b8804fb8e39618220deb8a`

`bzImage`/`vmlinux` 会受构建时间、工具链等影响，参考值在 `checksums/reference-build.sha256`；每次复现都必须以本机 `SHA256SUMS` 的自校验结果为准，不能强求跨构建哈希相同。

## Git 结果与限制

- 本次续作起点本地 HEAD：`2ced4d1fd`；远端起点：`1863e2723`。
- 已安全快进推送 handoff 与修复提交；不使用 force push。
- `origin/main` 在写入本报告前为 `4ba84bb9d`；报告提交后应以最终外部完成报告记录的 HEAD 为准。
- 完整历史 remote clone 路径 `/home/lzx/Desktop/huawei/linux-l02-handoff-remote-clone-20260731` 因低速 SSH pack 传输在验证完成后停止，部分目录保留且未删除；其不影响上述已完成的直接 remote main shallow clone 验证。
