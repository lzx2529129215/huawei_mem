# Linux L0.2 文件与提交清单

## 交接新增文件

- `scripts/handoff/common.sh`：仓库根解析、日志、SHA256、目录 guard、资源检查和 manifest。
- `scripts/handoff/check_environment.sh`：依赖、平台、磁盘、内存检查，不自动安装。
- `scripts/handoff/fetch_linux617_source.sh`：固定 kernel.org URL 下载、归档校验、安全解压和 pristine 校验。
- `scripts/handoff/apply_linux_l02_patches.sh`：0002/0003 checksum、exact apply、重复状态和 ABI gate。
- `scripts/handoff/configure_linux_l02.sh`、`build_linux_l02.sh`、`verify_linux_l02_build.sh`：配置、out-of-tree 构建和产物门禁。
- `scripts/handoff/install_linux_l02.sh`：默认 dry-run，`--execute` 才安装，永不 reboot。
- `scripts/handoff/runtime_smoke_linux_l02.sh`：read-only runtime preflight；显式 bounded-reclaim 时调用现有 capture helper 并解析 raw trace。
- `scripts/handoff/reproduce_all.sh`、`clean_generated.sh`：无特权复现入口和受保护清理入口。
- `tests/handoff/`：CLI、错误 SHA、manifest、目录 guard、补丁 hash、文档引用和绝对本机路径测试。
- `docs/handoff/`：工作交接、快速复现、故障排查、验证报告和清单。

## 固定校验材料

- `checksums/linux617-source-archive.sha256`：kernel.org 归档 SHA256。
- `checksums/linux617-pristine-files.sha256`：Linux v6.17 canonical 文件的 mode/path/SHA256，共 90,506 条。
- `checksums/patches.sha256`：0002/0003 SHA256。
- `checksums/reference-build.sha256`：本次完整构建的产物参考 SHA256；不同工具链或配置的结果不应强行等同，交接脚本会对本机产物另行生成并校验 `SHA256SUMS`。

## 关键提交

- 交接开始时本地/远端 `main`：`1863e2723800a929c28d7326941a45d37f2c4ca2`。
- L0.2 observer merge：`ae6f6a2`（历史提交，最终报告以实际 `git log` 为准）。
- Linux pristine：tag `v6.17`，commit `e5f0a698b34ed76002dc5cff3804a61c80233a7a`。

## 不提交的内容

完整 Linux 源码、`work/`、`builds/`、下载 cache、`.config` 之外的构建产物、密码、token、私钥和运行时原始日志均不进入普通 Git。
