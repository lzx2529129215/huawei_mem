#!/bin/bash
# memcap 会话级采集编排脚本 v1
# 负责 session / operation / phase / delay 编排，
# 单次采集仍调用 collect.sh。
#
# 用法:
#   bash scripts/collect_session.sh <PID|进程名> <应用标签> <会话名> [选项]
#
# 示例:
#   bash scripts/collect_session.sh douyu 斗鱼 session_001
#   bash scripts/collect_session.sh 9376 斗鱼 session_001 -o op_launch,op_switch,op_minimize
#   bash scripts/collect_session.sh douyu 斗鱼 session_001 --phases before,after_0s,after_3s
#
# 选项:
#   -o <op1,op2,...>   逗号分隔的操作ID列表 (默认: op_main)
#   --phases <p1,p2,...> 逗号分隔的采集阶段 (默认: before,after_0s,after_1s,after_3s,after_5s)
#   --out <dir>         本地输出目录 (默认: memcap_out)
#   --device-out <dir>  设备端输出目录
#   --no-push           跳过编译推送 (非首次)

set -euo pipefail
export MSYS_NO_PATHCONV=1

# ====== 路径 ======
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COLLECT_SH="$PROJECT_DIR/scripts/collect.sh"
LOCAL_OUT="$PROJECT_DIR/memcap_out"
DEVICE_OUT=""
NO_PUSH=false

# ====== 默认值 ======
PHASES_DEFAULT=("before" "after_0s" "after_1s" "after_3s" "after_5s")
PHASES=()
OPERATIONS=()
SESSION_NAME=""
TARGET=""
APP_LABEL=""

# ====== 解析参数 ======
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) IFS=',' read -ra OPERATIONS <<< "$2"; shift 2 ;;
        --phases) IFS=',' read -ra PHASES <<< "$2"; shift 2 ;;
        --out) LOCAL_OUT="$2"; shift 2 ;;
        --device-out) DEVICE_OUT="$2"; shift 2 ;;
        --no-push) NO_PUSH=true; shift ;;
        -*)
            echo "未知选项: $1"
            echo "用法: $0 <PID|进程名> <应用标签> <会话名> [-o op1,op2,...] [--phases p1,p2,...]"
            exit 1
            ;;
        *)
            if [[ -z "$TARGET" ]]; then
                TARGET="$1"
            elif [[ -z "$APP_LABEL" ]]; then
                APP_LABEL="$1"
            elif [[ -z "$SESSION_NAME" ]]; then
                SESSION_NAME="$1"
            else
                echo "多余参数: $1"
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TARGET" ]] || [[ -z "$SESSION_NAME" ]]; then
    echo "用法: $0 <PID|进程名> <应用标签> <会话名> [-o op1,op2,...]"
    echo ""
    echo "示例:"
    echo "  $0 douyu 斗鱼 session_001"
    echo "  $0 douyu 斗鱼 session_001 -o op_launch,op_switch,op_minimize"
    echo "  $0 9376 斗鱼 session_001 --phases before,after_0s,after_3s"
    exit 1
fi

# 默认值填充
if [[ ${#OPERATIONS[@]} -eq 0 ]]; then
    OPERATIONS=("op_main")
fi
if [[ ${#PHASES[@]} -eq 0 ]]; then
    PHASES=("${PHASES_DEFAULT[@]}")
fi
[[ -z "$APP_LABEL" ]] && APP_LABEL="$TARGET"

SESSION_ID="session_$(date +%Y%m%d_%H%M%S)"
SESSION_START_MS="$(date +%s%3N 2>/dev/null || echo $(($(date +%s) * 1000)))"

echo "============================================"
echo "  memcap 会话级采集编排 v1"
echo "============================================"
echo "  会话:           $SESSION_NAME"
echo "  会话ID:         $SESSION_ID"
echo "  目标:           $APP_LABEL (查询: $TARGET)"
echo "  操作序列:       ${OPERATIONS[*]}"
echo "  采集阶段:       ${PHASES[*]}"
echo "  输出目录:       $LOCAL_OUT"
echo "============================================"
echo ""

# ====== 确保输出目录 ======
mkdir -p "$LOCAL_OUT"

# ====== 初始化 session_index.csv ======
SESSION_INDEX="$LOCAL_OUT/session_index.csv"
if [[ ! -f "$SESSION_INDEX" ]]; then
    echo "session_id,session_name,app_id,app_name,process_name,pid,start_timestamp_ms,end_timestamp_ms,operation_count,sample_count,foreground_state,note" > "$SESSION_INDEX"
fi

# ====== 初始化 process_snapshot.csv ======
PROCESS_SNAPSHOT="$LOCAL_OUT/process_snapshot.csv"
if [[ ! -f "$PROCESS_SNAPSHOT" ]]; then
    echo "session_id,sample_id,operation_id,phase,delay_seconds,pid,process_name,timestamp_ms,note" > "$PROCESS_SNAPSHOT"
fi

# ====== 延迟映射 ======
declare -A PHASE_DELAY
PHASE_DELAY["before"]=0
PHASE_DELAY["after_0s"]=0
PHASE_DELAY["after_1s"]=1
PHASE_DELAY["after_3s"]=3
PHASE_DELAY["after_5s"]=5

# ====== 构建 collect.sh 公共选项 ======
COLLECT_OPTS=""
if [[ "$NO_PUSH" == true ]]; then
    COLLECT_OPTS="$COLLECT_OPTS --no-push"
fi
if [[ -n "$DEVICE_OUT" ]]; then
    COLLECT_OPTS="$COLLECT_OPTS --device-out $DEVICE_OUT"
fi

# ====== 查找 PID ======
TARGET_PID=""
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    TARGET_PID="$TARGET"
else
    # 按名称查找，取第一个
    TARGET_PID=$(hdc shell "ps -A -o PID,ARGS" 2>/dev/null | grep -i "$TARGET" | grep -v grep | head -1 | awk '{print $1}' || true)
    if [[ -z "$TARGET_PID" ]]; then
        echo "[错误] 未找到匹配 '$TARGET' 的进程"
        hdc shell "ps -A -o PID,ARGS" 2>/dev/null | head -20
        exit 2
    fi
    echo "[查找] 找到 PID: $TARGET_PID"
fi

# ====== 提炼操作 ======
TOTAL_SAMPLES=0
OPERATION_INDEX=1
COLLECTED_SAMPLES=()

for op in "${OPERATIONS[@]}"; do
    echo ""
    echo "--- 操作 [$OPERATION_INDEX/${#OPERATIONS[@]}] : $op ---"

    PHASE_INDEX=0
    for phase in "${PHASES[@]}"; do
        delay_s="${PHASE_DELAY[$phase]:-0}"

        # before 阶段：提示用户准备
        if [[ "$phase" == "before" ]]; then
            echo ""
            echo "  >>> 准备采集操作 '$op' 的 before 基线 <<<"
            echo "  >>> 请确保应用处于稳定状态，按 Enter 继续 <<<"
            read -r
        fi

        # after_0s 阶段：提示用户执行操作
        if [[ "$phase" == "after_0s" ]]; then
            echo ""
            echo "  >>> 请在设备上执行操作: '$op' <<<"
            echo "  >>> 完成后立即按 Enter 采集 after_0s <<<"
            read -r
        fi

        # 非 before 且有延迟的阶段：等待
        if [[ "$delay_s" -gt 0 ]]; then
            echo "  [等待] ${delay_s}s 后采集 $phase ..."
            sleep "$delay_s"
        fi

        # 调用 collect.sh
        OP_ID="${SESSION_NAME}_${op}"
        echo "  [采集] phase=$phase op=$OP_ID delay=${delay_s}s"

        COLLECT_OUT=$(
            bash "$COLLECT_SH" "$TARGET_PID" "$APP_LABEL" \
                -o "$OP_ID" \
                -f "foreground" \
                --out "$LOCAL_OUT" \
                $COLLECT_OPTS \
                2>&1
        ) || {
            echo "  [警告] collect.sh 退出码非零，继续下一个 phase"
        }

        # 从输出中提取 SAMPLE_ID
        SAMPLE_ID=$(echo "$COLLECT_OUT" | grep -oP 'SAMPLE_ID=\K\S+' | head -1 || true)
        if [[ -z "$SAMPLE_ID" ]]; then
            # 退化：用时间戳生成
            SAMPLE_ID="sample_$(date +%Y%m%d_%H%M%S)"
            echo "  [警告] 未能从 collect.sh 输出中解析 SAMPLE_ID，使用 $SAMPLE_ID"
        fi

        # 写入 process_snapshot.csv
        TS_NOW="$(date +%s%3N 2>/dev/null || echo $(($(date +%s) * 1000)))"
        echo "$SESSION_ID,$SAMPLE_ID,$OP_ID,$phase,$delay_s,$TARGET_PID,$APP_LABEL,$TS_NOW," >> "$PROCESS_SNAPSHOT"

        TOTAL_SAMPLES=$((TOTAL_SAMPLES + 1))
        COLLECTED_SAMPLES+=("$SAMPLE_ID")
        echo "  [完成] $SAMPLE_ID ($phase)"

        PHASE_INDEX=$((PHASE_INDEX + 1))
    done

    OPERATION_INDEX=$((OPERATION_INDEX + 1))
done

SESSION_END_MS="$(date +%s%3N 2>/dev/null || echo $(($(date +%s) * 1000)))"

# ====== 写入 session_index.csv ======
echo "$SESSION_ID,$SESSION_NAME,app_auto,$APP_LABEL,$APP_LABEL,$TARGET_PID,$SESSION_START_MS,$SESSION_END_MS,${#OPERATIONS[@]},$TOTAL_SAMPLES,foreground," >> "$SESSION_INDEX"

echo ""
echo "============================================"
echo "  会话采集完成"
echo "============================================"
echo "  会话ID:         $SESSION_ID"
echo "  操作数:         ${#OPERATIONS[@]}"
echo "  总样本数:       $TOTAL_SAMPLES"
echo "  阶段数/操作:    ${#PHASES[@]}"
echo "  session_index:  $SESSION_INDEX"
echo "  process_snap:   $PROCESS_SNAPSHOT"
echo "  样本列表:"
for s in "${COLLECTED_SAMPLES[@]}"; do
    echo "    $s"
done
echo "============================================"
