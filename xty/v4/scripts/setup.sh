#!/bin/bash
# ================================================================
# MGLRU v4 内核复现脚本
#
# 功能：基于原始 v4.zip 内核源码，自动应用所有补丁，
#       生成与当前 v4 内核一致的源码目录。
#
# 用法：
#   ./setup.sh [v4.zip路径] [输出目录]
#
# 默认值：
#   v4.zip 路径: 当前目录下的 v4.zip
#   输出目录:    当前目录下的 v4_reproduced
# ================================================================

set -euo pipefail

# --- 参数解析 ---
V4_ZIP="${1:-v4.zip}"
OUT_DIR="${2:-v4_reproduced}"

echo "================================================================"
echo " MGLRU v4 Kernel 复现脚本"
echo "================================================================"
echo "  原始 v4.zip: ${V4_ZIP}"
echo "  输出目录:    ${OUT_DIR}"
echo "================================================================"
echo ""

# --- 颜色定义 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

step() {
    echo -e "${GREEN}[STEP]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# --- 步骤 1: 检查前置条件 ---
step "1/6: 检查前置条件..."

if [ ! -f "${V4_ZIP}" ]; then
    error "找不到 v4.zip: ${V4_ZIP}"
fi

# 获取脚本所在目录（复现包根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

PATCH_FILE="${SCRIPT_DIR}/patches/0001-tier2-predict-per-memcg-markov-prediction.patch"
if [ ! -f "${PATCH_FILE}" ]; then
    error "找不到补丁文件: ${PATCH_FILE}"
fi

echo "  - v4.zip 存在: ${V4_ZIP}"
echo "  - 补丁文件存在: ${PATCH_FILE}"

# 检查 patch 命令
if ! command -v patch &> /dev/null; then
    error "需要 patch 命令，请安装 patch 包"
fi

echo ""

# --- 步骤 2: 解压原始 v4.zip ---
step "2/6: 解压原始 v4.zip..."

if [ -d "${OUT_DIR}" ]; then
    warn "输出目录已存在，将删除: ${OUT_DIR}"
    rm -rf "${OUT_DIR}"
fi

mkdir -p "${OUT_DIR}"

echo "  正在解压 ${V4_ZIP} ... (可能需要几分钟)"
unzip -q -o "${V4_ZIP}" -d "${OUT_DIR}"

# 检查解压结果
KERNEL_SRC="${OUT_DIR}/v4/v4/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
if [ ! -d "${KERNEL_SRC}" ]; then
    # 尝试不同的路径结构（v4.zip 可能直接包含 v4/ 或不包含）
    KERNEL_SRC="${OUT_DIR}/v4/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
    if [ ! -d "${KERNEL_SRC}" ]; then
        # 如果 v4.zip 的根就是内核目录
        KERNEL_SRC=""
        for d in "${OUT_DIR}"/*/mglru_kernel_transfer/linux-hwe-6.17-6.17.0; do
            if [ -d "$d" ]; then
                KERNEL_SRC="$d"
                break
            fi
        done
    fi
fi

if [ -z "${KERNEL_SRC}" ] || [ ! -d "${KERNEL_SRC}" ]; then
    error "解压后找不到内核源码目录: mglru_kernel_transfer/linux-hwe-6.17-6.17.0"
fi

echo "  内核源码目录: ${KERNEL_SRC}"
echo ""

# --- 步骤 3: 备份原始文件 ---
step "3/6: 备份将被修改的原始文件..."

BACKUP_DIR="${OUT_DIR}/.v4_original_backup"
mkdir -p "${BACKUP_DIR}/mm"
mkdir -p "${BACKUP_DIR}/include/linux"

for f in \
    "mm/tier2_watermark.c" \
    "mm/page_alloc.c" \
    "include/linux/tier2_watermark.h"; do
    if [ -f "${KERNEL_SRC}/${f}" ]; then
        cp -v "${KERNEL_SRC}/${f}" "${BACKUP_DIR}/${f}"
    fi
done

echo ""

# --- 步骤 4: 清理 extraneous 文件 ---
step "4/6: 清理 extraneous 文件..."

# 清理可能在原始包中残留的备份文件
for f in \
    "include/linux/tier2_watermark.h.bak" \
    "mm/tier2_watermark.c.bak" \
    "mm/tier2_watermark.c.bak2" \
    "folios"; do
    if [ -f "${KERNEL_SRC}/${f}" ]; then
        echo "  删除: ${f}"
        rm -f "${KERNEL_SRC}/${f}"
    fi
done

echo ""

# --- 步骤 5: 应用补丁 ---
step "5/6: 应用内核补丁..."

cd "${KERNEL_SRC}"

echo "  应用: $(basename "${PATCH_FILE}")"
if patch -p1 -N --dry-run < "${PATCH_FILE}" 2>&1; then
    patch -p1 -N < "${PATCH_FILE}"
    echo ""
    echo -e "  ${GREEN}补丁应用成功！${NC}"
else
    # 检查是否已经打过补丁（全部被跳过）
    if patch -p1 -N --dry-run < "${PATCH_FILE}" 2>&1 | grep -q "Reversed\|already applied"; then
        warn "补丁可能已经应用过，跳过"
    else
        error "补丁应用失败！请查看上方错误信息"
    fi
fi

cd - > /dev/null
echo ""

# --- 步骤 6: 写入 README.md 和 SHA256SUMS ---
step "6/6: 写入顶层文件..."

V4_TOP="$(dirname "$(dirname "${KERNEL_SRC}")")"

# 写入 README.md
cp "${SCRIPT_DIR}/README.md" "${V4_TOP}/README.md"
echo "  写入: ${V4_TOP}/README.md"

# 生成 SHA256SUMS
echo "  生成 SHA256SUMS..."
(
    cd "${V4_TOP}"
    find . -type f -not -path './.v4_original_backup/*' -not -name 'SHA256SUMS' \
        | sort \
        | xargs sha256sum > SHA256SUMS
)
echo "  写入: ${V4_TOP}/SHA256SUMS"

echo ""

# --- 完成 ---
echo "================================================================"
echo -e " ${GREEN}复现完成！${NC}"
echo "================================================================"
echo ""
echo "  内核源码目录: ${KERNEL_SRC}"
echo "  原始备份目录: ${BACKUP_DIR}"
echo ""
echo "  构建命令："
echo "    ROOT=${V4_TOP}"
echo '    SRC="$ROOT/mglru_kernel_transfer/linux-hwe-6.17-6.17.0"'
echo '    OUT="$HOME/build/linux-hwe-6.17-dual-observe-bindfix"'
echo '    mkdir -p "$OUT"'
echo '    cp "$ROOT/mglru_kernel_transfer/config-6.17.13-mglru-dual-observe-bindfix-20260714_092525" "$OUT/.config"'
echo '    make -C "$SRC" O="$OUT" olddefconfig'
echo '    make -C "$SRC" O="$OUT" -j"$(nproc)"'
echo ""
echo "  验证命令："
echo "    ${SCRIPT_DIR}/scripts/verify.sh ${V4_TOP}"
echo ""
exit 0
