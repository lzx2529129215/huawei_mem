# MGLRU Kernel

# ——二级水位线Per-Cgroup改进

#3 初始node-level二级水位线。

#5 本次改进将node-level tier2保留，实现向后兼容，并且实现per-cgroup二级水位线。

#6 本次改进实现cgroup v2，与项目对齐。

#7 本次改进实现自动reclaim触发。

#8（现版本） 本次改进实现workqueue异步回收、MGLRU代际感知、全局vmstat计数器、pressure-count压力感知。

## 环境信息

| 项目         | 值                                                           |
| ------------ | ------------------------------------------------------------ |
| 源码目录     | `/mglru_kernel_transfer_0705/linux-hwe-6.17-6.17.0`          |
| 构建目录     | `/mglru_kernel_transfer_0705/linux-hwe-6.17-mglru-build`     |
| 内核镜像     | `/boot/vmlinuz-6.17.13`                                      |
| initrd       | `/boot/initrd.img-6.17.13`                                   |
| 模块目录     | `/lib/modules/6.17.13/`                                      |
| Grub 菜单 ID | `gnulinux-6.17.13-advanced-59c1cd55-f3b5-41da-8e40-3e0c0b959a90` |
| 原始内核备选 | `6.17.13-mglru` (grub 默认)                                  |

## 编译

```bash
# 进入源码目录
cd .../mglru_kernel_transfer_0705/linux-hwe-6.17-6.17.0

# 进入构建目录，用 4 核编译
cd ../linux-hwe-6.17-mglru-build
sudo make -j4

# 编译成功后输出:
# Kernel: arch/x86/boot/bzImage is ready  (#N)
```

## 安装

```bash
# 仍在构建目录中
cd .../mglru_kernel_transfer_0705/linux-hwe-6.17-mglru-build

# 安装模块到 /lib/modules/6.17.13/
sudo make modules_install

# 安装内核到 /boot/
sudo make install

# 更新 grub 菜单
sudo update-grub
```

## 启动新内核

```bash
# 方式1: 切换到新内核并立即重启
sudo sed -i 's|/boot/vmlinuz-6.17.13-mglru |/boot/vmlinuz-6.17.13 |g' /boot/grub/grub.cfg
sudo sed -i 's|/boot/initrd.img-6.17.13-mglru|/boot/initrd.img-6.17.13|g' /boot/grub/grub.cfg
sudo reboot

# 方式2: 使用 grub-reboot 一次性启动
sudo grub-reboot 'gnulinux-advanced-59c1cd55-f3b5-41da-8e40-3e0c0b959a90>gnulinux-6.17.13-advanced-59c1cd55-f3b5-41da-8e40-3e0c0b959a90'
sudo reboot

# 方式3: 开机时在 grub 菜单选择 "Ubuntu, Linux 6.17.13"
```

## 验证新内核

```bash
# 确认内核版本
uname -r
# 应输出: 6.17.13

# 确认 tier2 初始化
sudo dmesg | grep tier2
# 应输出:
# tier2_watermark: per-memcg cgroup files registered
# tier2_watermark: initialized (enabled=0, alloc_scale=1.00%, demote_scale=3.00%)
```

## 快速功能验证

```bash
# 创建测试 cgroup
CG=/sys/fs/cgroup/memory/test_tier2
sudo mkdir -p $CG

# 配置 per-memcg tier2
echo 128M | sudo tee $CG/memory.limit_in_bytes
echo 1    | sudo tee $CG/memory.tier2_enabled
echo 500  | sudo tee $CG/memory.tier2_alloc_scale
echo 1000 | sudo tee $CG/memory.tier2_demote_scale

# 查看水位线
sudo cat $CG/memory.tier2_alloc_wmark   # ~6.7MB
sudo cat $CG/memory.tier2_demote_wmark  # ~13.4MB
sudo cat $CG/memory.tier2_stats         # 完整统计

# 清理
sudo rmdir $CG
```


