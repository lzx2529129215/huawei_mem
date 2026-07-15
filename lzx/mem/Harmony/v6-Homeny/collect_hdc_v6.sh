#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""
LOCAL_OUT="${SCRIPT_DIR}/hdc_out"
DEVICE_DIR="/data/local/tmp/mem_analyze_v6"
DEVICE_OUT="/storage/media/100/local/files/Docs/Desktop/output-lzx"
OPERATION_CMD=""
WITH_VMA=0
NO_BUILD=0
NO_PUSH=0

usage() {
    cat <<EOF
Usage:
  $0 <pid|app_keyword> [--with-vma]
  $0 <pid|app_keyword> --out ./hdc_out --device-out /storage/media/100/local/files/Docs/Desktop/output-lzx

Options:
  --target <value>          PID or app/package keyword. Digits are treated as PID.
  -o, --out <path>          Local output directory. Default: lzx-Test1/v6-Homeny/hdc_out
  --device-dir <path>       Device binary/work directory. Default: /data/local/tmp/mem_analyze_v6
  --device-out <path>       Device report output directory. Default: /storage/media/100/local/files/Docs/Desktop/output-lzx
  --operation-cmd <cmd>     Local command to run after clear_refs and before smaps sampling.
                            If omitted, the script waits for Enter.
  --with-vma                Include VMA-level Referenced table.
  --no-build                Skip cross compilation and reuse local mem_analyze-v6-ohos.
  --no-push                 Skip sending the binary to device.
  -h, --help                Show this help.

Examples:
  $0 12345 --with-vma
  $0 com.example.app --operation-cmd 'hdc shell "aa start -a EntryAbility -b com.example.app"'
  $0 com.example.app --no-build --no-push
EOF
}

run() {
    "$@"
}

default_sdk_path() {
    local candidate="/d/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native"
    if [[ -d "$candidate" ]]; then
        printf '%s' "$candidate"
        return
    fi
    candidate="/mnt/d/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native"
    if [[ -d "$candidate" ]]; then
        printf '%s' "$candidate"
        return
    fi
    candidate="D:/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/native"
    if [[ -d "$candidate" ]]; then
        printf '%s' "$candidate"
        return
    fi
}

while (($# > 0)); do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --target|-Target)
            if (($# < 2)); then
                echo "$1 requires a value" >&2
                exit 1
            fi
            TARGET="$2"
            shift 2
            ;;
        -o|--out|-Out)
            if (($# < 2)); then
                echo "$1 requires a value" >&2
                exit 1
            fi
            LOCAL_OUT="$2"
            shift 2
            ;;
        --device-dir|-DeviceDir)
            if (($# < 2)); then
                echo "$1 requires a value" >&2
                exit 1
            fi
            DEVICE_DIR="$2"
            shift 2
            ;;
        --device-out|-DeviceOut)
            if (($# < 2)); then
                echo "$1 requires a value" >&2
                exit 1
            fi
            DEVICE_OUT="$2"
            shift 2
            ;;
        --operation-cmd|-OperationCommand)
            if (($# < 2)); then
                echo "$1 requires a value" >&2
                exit 1
            fi
            OPERATION_CMD="$2"
            shift 2
            ;;
        --with-vma|-WithVma)
            WITH_VMA=1
            shift
            ;;
        --no-build|-NoBuild)
            NO_BUILD=1
            shift
            ;;
        --no-push|-NoPush)
            NO_PUSH=1
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            if [[ -n "$TARGET" ]]; then
                echo "Only one target can be specified" >&2
                exit 1
            fi
            TARGET="$1"
            shift
            ;;
    esac
done

if [[ -z "$TARGET" ]]; then
    usage >&2
    echo "Missing target" >&2
    exit 1
fi

SOURCE="${SCRIPT_DIR}/mem_analyze-v6.c"
LOCAL_BIN="${SCRIPT_DIR}/mem_analyze-v6-ohos"
DEVICE_BIN="${DEVICE_DIR}/mem_analyze-v6"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEVICE_REPORT="${DEVICE_OUT}/referenced_${TIMESTAMP}.md"

if ((NO_BUILD == 0)); then
    SDK="${OHOS_SDK:-$(default_sdk_path)}"
    if [[ -z "$SDK" || ! -d "$SDK" ]]; then
        echo "OHOS_SDK is not set and the default SDK path was not found." >&2
        exit 1
    fi

    CLANG="${SDK}/llvm/bin/clang"
    if [[ ! -x "$CLANG" && -x "${CLANG}.exe" ]]; then
        CLANG="${CLANG}.exe"
    fi
    SYSROOT="${SDK}/sysroot"
    if [[ ! -x "$CLANG" ]]; then
        echo "OpenHarmony clang not found: $CLANG" >&2
        exit 1
    fi
    if [[ ! -d "$SYSROOT" ]]; then
        echo "OpenHarmony sysroot not found: $SYSROOT" >&2
        exit 1
    fi

    echo "==> Building HarmonyOS collector"
    run "$CLANG" -O2 -std=c11 -Wall -Wextra \
        -target aarch64-linux-ohos \
        --sysroot="$SYSROOT" \
        -o "$LOCAL_BIN" "$SOURCE"
fi

if [[ ! -f "$LOCAL_BIN" ]]; then
    echo "Local collector binary not found: $LOCAL_BIN. Build first or remove --no-build." >&2
    exit 1
fi

if ((NO_PUSH == 0)); then
    echo "==> Pushing collector to device"
    run hdc shell "mkdir -p '$DEVICE_DIR' '$DEVICE_OUT'"
    run hdc file send "$LOCAL_BIN" "$DEVICE_BIN"
    run hdc shell "chmod 755 '$DEVICE_BIN'"
fi

TARGET_ARGS=()
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    TARGET_ARGS=("$TARGET")
else
    TARGET_ARGS=(--app "$TARGET")
fi

echo "==> Device and /proc permission check"
TARGETS="$(hdc list targets | tr -d '\r' | awk 'NF && $1 !~ /^\[/ {print $1}')"
if [[ -z "$TARGETS" ]]; then
    echo "No hdc target is connected." >&2
    exit 1
fi
if [[ "$(printf '%s\n' "$TARGETS" | wc -l | tr -d ' ')" -ne 1 ]]; then
    echo "Multiple hdc targets are connected; use a single-target environment." >&2
    printf '%s\n' "$TARGETS" >&2
    exit 1
fi
run hdc list targets
IDENTITY="$(run hdc shell "id")"
if [[ "$IDENTITY" != *"uid=0"* ]]; then
    echo "v6 requires a root hdc shell; got: $IDENTITY" >&2
    exit 1
fi
run hdc shell "test -r /proc/self/smaps -a -w /proc/self/clear_refs"

echo "==> Clearing referenced bits"
run hdc shell "'$DEVICE_BIN' --clear-refs ${TARGET_ARGS[*]}"

if [[ -z "$OPERATION_CMD" ]]; then
    echo
    echo "Referenced bits are cleared. Perform the target operation on the HarmonyOS device now."
    read -r -p "Press Enter to sample smaps..."
else
    echo "==> Running operation command"
    bash -lc "$OPERATION_CMD"
fi

echo "==> Sampling smaps"
SAMPLE_CMD="'$DEVICE_BIN' ${TARGET_ARGS[*]} -o '$DEVICE_REPORT'"
if ((WITH_VMA == 1)); then
    SAMPLE_CMD+=" --with-vma"
fi
run hdc shell "$SAMPLE_CMD"

echo "==> Pulling reports"
mkdir -p "$LOCAL_OUT"
run hdc file recv "$DEVICE_OUT" "$LOCAL_OUT"

echo "==> Done"
echo "Local output: $LOCAL_OUT"
echo "Device output: $DEVICE_OUT"
