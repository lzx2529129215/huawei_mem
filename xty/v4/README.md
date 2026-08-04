# MGLRU v4 Kernel 复现包

本包用于在任意设备上基于原始的 `v4.zip` 内核源码，复现当前的 v4 内核修改版本。

## 版本信息

- **内核版本**: 6.17.13-mglru-dual-observe-bindfix-20260714_092525
- **源码目录**: `mglru_kernel_transfer/linux-hwe-6.17-6.17.0/`
- **配置文件**: `mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525`
- **当前版本**: v4.2 (添加 per-memcg tier2 watermark 预测功能)

## 修改概述

相对于原始 v4.zip，当前版本新增了以下功能：

### 核心功能：Per-Memcg Tier2 Watermark 预测 (CONFIG_TIER2_WATERMARK_MEMCG)

1. **Markov 预测框架** (`include/linux/tier2_watermark.h`, `mm/tier2_watermark.c`)
   - eBPF 兼容的 Markov 链预测数据结构
   - 1-4 阶 Markov 预测，高阶到低阶回退
   - 基于操作历史的页面预取/淘汰预测

2. **Per-Memcg 水位线** (`include/linux/tier2_watermark.h`, `mm/tier2_watermark.c`)
   - 每个 memory cgroup 独立的 tier2 水位线配置
   - 基于 memcg limit 而非节点 managed_pages 计算水位线
   - 异步回收工作队列，避免阻塞 charge 路径

3. **主动预测与页面调整** (`mm/tier2_watermark.c`)
   - EWMA 平滑头空间追踪
   - 预测到达 demote 水位线的时间
   - 基于预测主动调整 MGLRU 代际页面优先级
   - 延迟调度预测工作

4. **Sysctl 控制接口** (`mm/page_alloc.c`)
   - `vm.tier2_predict_enabled` — 启用/禁用预测 (默认 0)
   - `vm.tier2_predict_latency_ms` — 预测延迟 (默认 100ms)
   - `vm.tier2_predict_horizon_ratio` — 预测时间范围倍数 (默认 3)

5. **eBPF 数据加载** (`mm/tier2_watermark.c`)
   - 通过 debugfs `/sys/kernel/debug/tier2_watermark/predict_data` 加载 CSV 数据
   - 支持 Markov 转移表、Profile 映射表、History 操作历史
   - 兼容 huawei_mem/lzx 的 CSV 导出格式

### 修改的文件

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `include/linux/tier2_watermark.h` | 重写 | 添加 per-memcg 和预测数据结构 |
| `mm/tier2_watermark.c` | 大幅修改 | 添加预测引擎、EWMA、CSV 解析器 |
| `mm/page_alloc.c` | 小幅修改 | 添加 3 个 sysctl 条目 |
| `README.md` | 新增 | 本说明文档 |
| `SHA256SUMS` | 新增 | 文件校验清单 |

## 复现步骤

### 前置条件

- 原始 `v4.zip` 内核源码包
- 编译器: gcc 或 clang (支持内核构建)
- 磁盘空间: ~5GB (用于源码和构建输出)
- Linux 构建环境

### 方法一：使用自动化脚本

```bash
# 1. 准备原始 v4.zip
cp /path/to/original/v4.zip ./

# 2. 运行复现脚本
chmod +x scripts/setup.sh
./scripts/setup.sh

# 3. 验证复现结果
chmod +x scripts/verify.sh
./scripts/verify.sh
```

### 方法二：手动复现

```bash
# 1. 解压原始 v4.zip
unzip v4.zip
cd v4/v4

# 2. 应用补丁
cp /path/to/this/package/patches/0001-tier2-predict-per-memcg-markov-prediction.patch .
cd mglru_kernel_transfer/linux-hwe-6.17-6.17.0
patch -p1 < ../../0001-tier2-predict-per-memcg-markov-prediction.patch

# 3. 清理 extraneous 文件（如果存在）
rm -f folios include/linux/tier2_watermark.h.bak mm/tier2_watermark.c.bak mm/tier2_watermark.c.bak2

# 4. 编译验证
ROOT=$(pwd)/../..
SRC="$ROOT/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
OUT="$HOME/build/linux-hwe-6.17-dual-observe-bindfix"
mkdir -p "$OUT"
cp "$ROOT/mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525" "$OUT/.config"
make -C "$SRC" O="$OUT" olddefconfig
make -C "$SRC" O="$OUT" -j"$(nproc)"
```

## 包内容

```
v4/
├── README.md                          # 本说明文档
├── patches/
│   └── 0001-tier2-predict-per-memcg-markov-prediction.patch  # 统一补丁
├── scripts/
│   ├── setup.sh                       # 自动复现脚本
│   └── verify.sh                      # 验证脚本
└── docs/
    └── changes.md                     # 详细修改说明
```

## 边界说明

- 本包仅包含从原始 v4.zip 到当前 v4 的**增量修改**
- 不包含构建产物、模块、vmlinux 或任何安装文件
- 不包含 Git 元数据
- 补丁仅影响 3 个内核源文件

## 相关配置

构建配置中的 `CONFIG_LOCALVERSION` 已固定为 `-mglru-dual-observe-bindfix-20260714_092525`。
不要覆盖它，否则构建出的 release 名称会变化。
