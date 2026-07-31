# Linux L0.2 快速复现

适用于一台没有项目上下文、没有本机 Linux 源码树的新机器。需要 x86_64 Ubuntu/Debian、至少 30 GiB 可用磁盘；本机低内存时使用 `--jobs 2`。

```sh
git clone https://github.com/lzx2529129215/huawei_mem.git
cd huawei_mem
git checkout main
git pull --ff-only
scripts/handoff/check_environment.sh
scripts/handoff/reproduce_all.sh --jobs 2
```

`reproduce_all.sh` 只执行下载、SHA256/pristine 校验、补丁、配置、out-of-tree 编译和验证，不安装、不修改 GRUB、不重启。默认配置继承 `/boot/config-$(uname -r)`；没有可用配置时可使用：

```sh
scripts/handoff/reproduce_all.sh --defconfig --disable-btf --jobs 2
```

产物位于 `work/linux-6.17` 和 `builds/linux-6.17-l02`，均被 `.gitignore` 排除。安装前先执行 dry-run：

```sh
scripts/handoff/install_linux_l02.sh
```

首次启动必须人工选择 GRUB 项，不能远程无人值守重启。运行时先做只读检查：

```sh
scripts/handoff/runtime_smoke_linux_l02.sh --read-only
```

具备 tracefs 写权限且需要真实、受控的 trace/parser 验证时，必须显式提供一个短时压力命令；脚本的 trap 会关闭它启用的 L0.2 trace events：

```sh
scripts/handoff/runtime_smoke_linux_l02.sh --bounded-reclaim \
  --output-dir /tmp/linux-l02-smoke -- sh -c 'your-bounded-pressure-command'
```

完整步骤也可以分段执行：`fetch_linux617_source.sh`、`apply_linux_l02_patches.sh`、`configure_linux_l02.sh`、`build_linux_l02.sh`、`verify_linux_l02_build.sh`。公开归档固定为 Linux 6.17 `v6.17`，URL、归档 SHA256、pristine 文件清单和补丁 SHA256 均在 `docs/handoff/checksums/`。
