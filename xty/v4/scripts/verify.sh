#!/bin/bash
# ================================================================
# MGLRU v4 内核验证脚本
#
# 功能：验证复现后的 v4 内核源码与预期一致
#
# 用法：
#   ./verify.sh [v4目录]
#
# 默认值：
#   v4 目录: ./v4_reproduced/v4/v4
# ================================================================

set -euo pipefail

V4_DIR="${1:-v4_reproduced/v4/v4}"

# --- 颜色定义 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass_cnt=0
fail_cnt=0
warn_cnt=0

pass() {
    echo -e "  ${GREEN}[PASS]${NC} $1"
    ((pass_cnt++))
}

fail() {
    echo -e "  ${RED}[FAIL]${NC} $1"
    ((fail_cnt++))
}

warn() {
    echo -e "  ${YELLOW}[WARN]${NC} $1"
    ((warn_cnt++))
}

echo "================================================================"
echo " MGLRU v4 Kernel 验证脚本"
echo "================================================================"
echo "  目标目录: ${V4_DIR}"
echo "================================================================"
echo ""

# --- 检查 1: 目录结构 ---
echo "[检查 1]: 目录结构完整性"

KERNEL_SRC="${V4_DIR}/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
CONFIG="${V4_DIR}/mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525"
TARBALL="${V4_DIR}/linux-hwe-6.17-dual-observe-bindfix-20260714_092525-src.tar.zst"

if [ -d "${V4_DIR}" ]; then
    pass "v4 顶层目录存在"
else
    fail "v4 顶层目录不存在: ${V4_DIR}"
fi

if [ -d "${KERNEL_SRC}" ]; then
    pass "内核源码目录存在"
else
    fail "内核源码目录不存在: ${KERNEL_SRC}"
fi

if [ -f "${CONFIG}" ]; then
    pass "内核配置文件存在"
else
    fail "内核配置文件不存在: ${CONFIG}"
fi

if [ -f "${V4_DIR}/README.md" ]; then
    pass "README.md 存在"
else
    warn "README.md 不存在（可选文件）"
fi

if [ -f "${V4_DIR}/SHA256SUMS" ]; then
    pass "SHA256SUMS 存在"
else
    warn "SHA256SUMS 不存在（可选文件）"
fi

echo ""

# --- 检查 2: SHA256 校验 ---
echo "[检查 2]: SHA256 文件校验"

if [ -f "${V4_DIR}/SHA256SUMS" ]; then
    (
        cd "${V4_DIR}"
        if command -v sha256sum &> /dev/null; then
            RESULT=$(sha256sum -c SHA256SUMS 2>&1 | grep -v "OK$" || true)
            if [ -z "${RESULT}" ]; then
                pass "所有文件校验通过"
            else
                # 忽略 README.md 和 SHA256SUMS 本身的变化
                FILTERED=$(echo "${RESULT}" | grep -v "README.md\|SHA256SUMS" || true)
                if [ -z "${FILTERED}" ]; then
                    warn "仅 README.md/SHA256SUMS 有变化（正常）"
                else
                    fail "部分文件校验失败: ${FILTERED}"
                fi
            fi
        else
            warn "sha256sum 命令不可用，跳过校验"
        fi
    )
else
    warn "SHA256SUMS 不存在，跳过校验"
fi

echo ""

# --- 检查 3: 核心文件存在 ---
echo "[检查 3]: 核心修改文件存在性"

REQUIRED_FILES=(
    "mm/tier2_watermark.c"
    "mm/page_alloc.c"
    "include/linux/tier2_watermark.h"
    "mm/Kconfig"
    "mm/Makefile"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "${KERNEL_SRC}/${f}" ]; then
        pass "文件存在: ${f}"
    else
        fail "文件缺失: ${f}"
    fi
done

echo ""

# --- 检查 4: 关键代码特征验证 ---
echo "[检查 4]: 关键代码特征验证"

# 检查 tier2_watermark.h 是否包含 per-memcg 结构
if grep -q "struct tier2_wmark_memcg" "${KERNEL_SRC}/include/linux/tier2_watermark.h" 2>/dev/null; then
    pass "tier2_watermark.h: 包含 per-memcg 结构定义"
else
    fail "tier2_watermark.h: 缺少 per-memcg 结构定义"
fi

# 检查 tier2_watermark.h 是否包含 Markov 数据结构
if grep -q "struct tier2_markov_entry" "${KERNEL_SRC}/include/linux/tier2_watermark.h" 2>/dev/null; then
    pass "tier2_watermark.h: 包含 Markov 预测结构"
else
    fail "tier2_watermark.h: 缺少 Markov 预测结构"
fi

# 检查 tier2_watermark.c 是否包含预测函数
if grep -q "tier2_wmark_predict_time_to_wmark" "${KERNEL_SRC}/mm/tier2_watermark.c" 2>/dev/null; then
    pass "tier2_watermark.c: 包含预测函数"
else
    fail "tier2_watermark.c: 缺少预测函数"
fi

# 检查 tier2_watermark.c 是否包含 EWMA 函数
if grep -q "tier2_wmark_update_ewma_memcg" "${KERNEL_SRC}/mm/tier2_watermark.c" 2>/dev/null; then
    pass "tier2_watermark.c: 包含 EWMA 跟踪函数"
else
    fail "tier2_watermark.c: 缺少 EWMA 跟踪函数"
fi

# 检查 page_alloc.c 是否包含预测 sysctl
if grep -q "tier2_predict_enabled" "${KERNEL_SRC}/mm/page_alloc.c" 2>/dev/null; then
    pass "page_alloc.c: 包含预测 sysctl 条目"
else
    fail "page_alloc.c: 缺少预测 sysctl 条目"
fi

# 检查是否有 CONFIG_TIER2_WATERMARK_MEMCG 使用
if grep -q "CONFIG_TIER2_WATERMARK_MEMCG" "${KERNEL_SRC}/mm/tier2_watermark.c" 2>/dev/null; then
    pass "tier2_watermark.c: 包含 CONFIG_TIER2_WATERMARK_MEMCG 条件编译"
else
    fail "tier2_watermark.c: 缺少 CONFIG_TIER2_WATERMARK_MEMCG 条件编译"
fi

echo ""

# --- 检查 5: extraneous 文件检查 ---
echo "[检查 5]: extraneous 文件检查"

EXTRANEOUS=(
    "include/linux/tier2_watermark.h.bak"
    "mm/tier2_watermark.c.bak"
    "mm/tier2_watermark.c.bak2"
    "folios"
)

for f in "${EXTRANEOUS[@]}"; do
    if [ -f "${KERNEL_SRC}/${f}" ]; then
        warn "extraneous 文件存在: ${f} (建议删除)"
    else
        pass "extraneous 文件已清理: ${f}"
    fi
done

echo ""

# --- 总结 ---
echo "================================================================"
echo " 验证结果总结"
echo "================================================================"
echo -e "  通过: ${GREEN}${pass_cnt}${NC}"
echo -e "  失败: ${RED}${fail_cnt}${NC}"
echo -e "  警告: ${YELLOW}${warn_cnt}${NC}"
echo "================================================================"
echo ""

if [ "${fail_cnt}" -gt 0 ]; then
    echo -e "${RED}验证发现 ${fail_cnt} 个问题，请检查上述输出。${NC}"
    exit 1
else
    echo -e "${GREEN}所有验证项目通过！v4 内核复现成功。${NC}"
    exit 0
fi
