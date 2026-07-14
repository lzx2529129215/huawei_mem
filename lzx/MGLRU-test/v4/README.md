# MGLRU v4 Bindfix 独立源码包

本目录保存 `6.17.13-mglru-dual-observe-bindfix-20260714_092525` 的可独立构建源码包。

## 内容

- `mglru_kernel_transfer/linux-hwe-6.17-6.17.0/`：内核源码。
- `mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525`：本次内核的构建配置。
- `SHA256SUMS`：源码包文件校验清单。
- `linux-hwe-6.17-dual-observe-bindfix-20260714_092525-src.tar.zst`：同一份源码和配置的压缩包。

本包不包含任何 build 目录、`vmlinux`、模块、对象文件、安装产物或 Git 元数据。源码目录内也不包含对 `v0`、`v3` 或其他 build 输出目录的符号链接。

## 独立构建

在任意具有足够磁盘空间的目录中执行。`OUT` 必须位于本源码包外部，不能放入 `v4`：

```bash
ROOT=/home/lzx/Desktop/huawei/huawei_mem/lzx/MGLRU-test/v4
SRC="$ROOT/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
OUT="$HOME/build/linux-hwe-6.17-dual-observe-bindfix"

mkdir -p "$OUT"
cp "$ROOT/mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525" "$OUT/.config"
make -C "$SRC" O="$OUT" olddefconfig
make -C "$SRC" O="$OUT" -j"$(nproc)"
```

配置中的 `CONFIG_LOCALVERSION` 已固定为 `-mglru-dual-observe-bindfix-20260714_092525`。不要覆盖它，否则构建出的 release 名称会变化。

## 边界

该目录仅是源码归档。本次归档不执行安装、GRUB 更新、重启或任何运行态 debugfs 写入。
