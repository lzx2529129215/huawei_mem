#!/bin/bash
# memcap 一键采集脚本 v2
# 用法: ./collect.sh <PID|进程名> [应用标签] [选项]
#
# 示例:
#   ./collect.sh 斗鱼                  # 按名称自动查找 PID 并采集
#   ./collect.sh douyu                 # 模糊匹配
#   ./collect.sh com.douyu.ho.app      # 精确匹配包名
#   ./collect.sh 斗鱼 --all            # 采集该应用的所有子进程
#   ./collect.sh 42820 斗鱼            # 传统方式：直接指定 PID
#   ./collect.sh 斗鱼 -o op_launch     # 指定操作ID
#
# 选项:
#   -o <op_id>      操作ID (默认 auto_YYYYMMDD_HHMMSS)
#   -a <app_id>     应用ID (默认 app_auto)
#   -f <fg_state>   前后台 (默认 foreground)
#   --all           采集所有匹配的进程 (默认只采第一个)
#   --no-push       跳过编译和推送
#   --no-pull       跳过拉回结果
#   --out <dir>     本地输出目录 (默认 memcap_out)
#   --device-out <dir> 设备端输出目录 (默认 /data/local/tmp/memcap/out)
#   --reset-out     采集前清空设备和本地输出目录

set -euo pipefail
export MSYS_NO_PATHCONV=1

# ====== hdc 自动检测 ======
if ! command -v hdc &>/dev/null; then
    if [ -f "$HOME/Library/OpenHarmony/Sdk/23/toolchains/hdc" ]; then
        export PATH="$HOME/Library/OpenHarmony/Sdk/23/toolchains:$PATH"
    elif [ -f "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc" ]; then
        export PATH="/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains:$PATH"
    fi
fi

# ====== 配置：自动检测平台 ======
SDK_BASE=""
if [[ -d "/Applications/DevEco-Studio.app" ]]; then
    # macOS
    SDK_BASE="/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native"
    CLANG="$SDK_BASE/llvm/bin/clang"
    SYSROOT="$SDK_BASE/sysroot"
elif [[ -d "D:/Program Files/Huawei/DevEco Studio" ]]; then
    # Windows
    SDK_BASE="D:/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native"
    CLANG="$SDK_BASE/llvm/bin/clang.exe"
    SYSROOT="$SDK_BASE/sysroot"
else
    echo "警告: 未自动检测到 DevEco Studio SDK，尝试使用 PATH 中的 clang"
    CLANG="$(which clang 2>/dev/null || echo "clang")"
    SYSROOT=""
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MEMCAP_SRC="$PROJECT_DIR/memcap.c"
MEMCAP_BIN="$PROJECT_DIR/memcap"
DEVICE_BIN="/data/local/tmp/memcap/memcap"
DEVICE_OUT="/data/local/tmp/memcap/out"
LOCAL_OUT="$PROJECT_DIR/memcap_out"

# ====== 默认值 ======
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OPERATION_ID="auto_${TIMESTAMP}"
APP_ID="app_auto"
FG_STATE="foreground"
DO_PUSH=true
DO_PULL=true
DO_ALL=false
RESET_OUT=false
SAMPLE_INDEX="1"

# ====== 工具函数 ======
find_pids_by_name() {
    local keyword="$1"
    local result
    result="$(hdc shell "ps -A -o PID,ARGS" 2>/dev/null | grep -i "$keyword" | grep -v grep || true)"
    echo "$result"
}

collect_one_pid() {
    local pid="$1" label="$2" proc_name="$3" sample_idx="$4"

    echo "  [PID $pid] $proc_name 采集中..."

    hdc shell "$DEVICE_BIN $pid $DEVICE_OUT $SAMPLE_ID $OPERATION_ID $APP_ID '$label' '$proc_name' $sample_idx $FG_STATE" 2>&1
    local rc=$?
    echo "  [PID $pid] 完成 (exit=$rc)"
    return $rc
}

# ====== 解析参数 ======
TARGET=""
APP_LABEL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) OPERATION_ID="$2"; shift 2 ;;
        -a) APP_ID="$2"; shift 2 ;;
        -f) FG_STATE="$2"; shift 2 ;;
        --all) DO_ALL=true; shift ;;
        --no-push) DO_PUSH=false; shift ;;
        --no-pull) DO_PULL=false; shift ;;
        --out) LOCAL_OUT="$2"; shift 2 ;;
        --device-out) DEVICE_OUT="$2"; shift 2 ;;
        --reset-out) RESET_OUT=true; shift ;;
        -*)
            echo "未知选项: $1"
            echo "用法: $0 <PID|进程名> [应用标签] [-o op_id] [--all] [--no-push] [--no-pull]"
            exit 1
            ;;
        *)
            if [[ -z "$TARGET" ]]; then
                TARGET="$1"
            elif [[ -z "$APP_LABEL" ]]; then
                APP_LABEL="$1"
            else
                echo "多余参数: $1"
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <PID|进程名> [应用标签]"
    echo ""
    echo "示例:"
    echo "  $0 斗鱼                 # 按名称自动查找 PID"
    echo "  $0 com.douyu.ho.app     # 按包名精确匹配"
    echo "  $0 斗鱼 --all           # 采集该应用所有子进程"
    echo "  $0 42820 斗鱼           # 指定 PID"
    echo "  $0 斗鱼 -o op_launch    # 指定操作ID"
    echo ""
    echo "查看设备上所有进程:"
    echo "  hdc shell \"ps -A -o PID,ARGS\""
    exit 1
fi

# ====== 第 1 步：解析目标 PID ======
PIDS=()
PROCESS_NAMES=()

if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    # 直接给了 PID
    PID="$TARGET"
    PROC_NAME="$(hdc shell "cat /proc/$PID/cmdline 2>/dev/null | tr '\0' ' '" 2>/dev/null || echo "unknown")"
    PIDS+=("$PID")
    PROCESS_NAMES+=("$PROC_NAME")
    [[ -z "$APP_LABEL" ]] && APP_LABEL="$PROC_NAME"
    echo "使用指定 PID: $PID"
else
    # 按名称搜索
    echo "搜索进程: \"$TARGET\" ..."
    MATCHES="$(find_pids_by_name "$TARGET")"

    if [[ -z "$MATCHES" ]]; then
        echo "未找到匹配 \"$TARGET\" 的进程。"
        echo "设备上当前进程列表:"
        hdc shell "ps -A -o PID,ARGS" 2>/dev/null | head -40
        exit 2
    fi

    # 解析搜索结果
    echo "找到匹配进程:"
    echo "$MATCHES" | nl -w2 -s'. '
    echo ""

    # 提取所有匹配的 PID 和进程名
    mapfile -t MATCH_LINES <<< "$MATCHES"
    if [[ "$DO_ALL" == true ]]; then
        for line in "${MATCH_LINES[@]}"; do
            read -r p n <<< "$line"
            PIDS+=("$p")
            PROCESS_NAMES+=("$n")
        done
        echo "将采集全部 ${#PIDS[@]} 个进程。"
    else
        # 只选第一个
        read -r p n <<< "${MATCH_LINES[0]}"
        PIDS+=("$p")
        PROCESS_NAMES+=("$n")
        echo "默认采集第一个进程 (PID $p)。使用 --all 可采集全部。"
    fi
fi

[[ -z "$APP_LABEL" ]] && APP_LABEL="${PROCESS_NAMES[0]}"
SAMPLE_ID="sample_${TIMESTAMP}"

echo ""
echo "============================================"
echo "  memcap 内存快照采集 v2"
echo "============================================"
echo "  平台:           $(uname -s)"
echo "  目标:           $APP_LABEL"
echo "  进程数:         ${#PIDS[@]}"
for i in "${!PIDS[@]}"; do
    echo "    PID ${PIDS[$i]}: ${PROCESS_NAMES[$i]}"
done
echo "  Sample ID:      $SAMPLE_ID"
echo "  Operation ID:   $OPERATION_ID"
echo "  设备输出目录:   $DEVICE_OUT"
echo "============================================"
echo ""

# ====== 第 1.5 步：重置输出目录（可选） ======
if [[ "$RESET_OUT" == true ]]; then
    echo "[重置] 清空设备端输出目录: $DEVICE_OUT"
    hdc shell "rm -rf $DEVICE_OUT" 2>/dev/null || true
    echo "[重置] 清空本地输出目录: $LOCAL_OUT"
    rm -rf "$LOCAL_OUT"
fi

# ====== 第 2 步：编译与推送 ======
if [[ "$DO_PUSH" == true ]]; then
    echo "[编译] 交叉编译 memcap.c ..."
    if [[ ! -f "$CLANG" ]]; then
        echo "错误: 找不到 clang: $CLANG"
        echo "请修改脚本顶部的 SDK_BASE 路径"
        exit 3
    fi
    if [[ -n "$SYSROOT" ]]; then
        "$CLANG" -O2 -std=c11 -Wall -Wextra \
            -target aarch64-linux-ohos \
            --sysroot="$SYSROOT" \
            -o "$MEMCAP_BIN" "$MEMCAP_SRC"
    else
        "$CLANG" -O2 -std=c11 -Wall -Wextra \
            -target aarch64-linux-ohos \
            -o "$MEMCAP_BIN" "$MEMCAP_SRC"
    fi
    echo "  编译成功: $MEMCAP_BIN"

    echo "[推送] 推送 memcap 到 /data/local/tmp/memcap/ ..."
    hdc shell "mkdir -p /data/local/tmp/memcap"
    hdc file send "$MEMCAP_BIN" "$DEVICE_BIN"
    hdc shell "chmod 755 $DEVICE_BIN"
    echo "  推送完成"
else
    echo "[跳过] 编译与推送"
fi

# ====== 第 3 步：运行采集 ======
echo "[采集] 运行内存快照..."

# 获取已有快照数作为起始索引
EXISTING_COUNT="$(hdc shell "wc -l < $DEVICE_OUT/snapshot_index.csv 2>/dev/null" 2>/dev/null || echo "0")"
EXISTING_COUNT="${EXISTING_COUNT//[$'\r\n']/}"
if [[ "$EXISTING_COUNT" =~ ^[0-9]+$ ]] && [[ "$EXISTING_COUNT" -gt 0 ]]; then
    SAMPLE_INDEX="$EXISTING_COUNT"
fi

FAILED=0
for i in "${!PIDS[@]}"; do
    collect_one_pid "${PIDS[$i]}" "$APP_LABEL" "${PROCESS_NAMES[$i]}" "$((SAMPLE_INDEX + i))" || FAILED=1
done

echo "  采集完成 ($FAILED 个失败)"

# ====== 第 4 步：拉回结果 ======
if [[ "$DO_PULL" == true ]]; then
    echo "[拉回] 从设备拉取 CSV 结果..."
    mkdir -p "$LOCAL_OUT"
    hdc file recv "$DEVICE_OUT" "$LOCAL_OUT"
    echo "  结果保存到: $LOCAL_OUT"
    echo ""
    echo "============================================"
    echo "  采集完成"
    echo "============================================"
    echo "  SAMPLE_ID=$SAMPLE_ID"
    echo "  OUTPUT_DIR=$LOCAL_OUT"
    echo "  快照索引:"
    cat "$LOCAL_OUT/snapshot_index.csv" 2>/dev/null | column -t -s',' || true
    echo ""
    echo "  CSV 文件:"
    for f in "$LOCAL_OUT"/*.csv; do
        lines=$(wc -l < "$f" 2>/dev/null || echo "0")
        size=$(du -h "$f" 2>/dev/null | cut -f1 || echo "0")
        printf "    %-35s %6s 行  %s\n" "$(basename "$f")" "$lines" "$size"
    done
    echo ""
    echo "  快速统计 RSS:"
    echo "    awk -F',' '\$19>0 {rss+=\$19; n++} END{printf \"VMA数=%d RSS=%d KB (%.1f MB)\\n\", n, rss, rss/1024}' $LOCAL_OUT/vma_memory_snapshot.csv"
fi
