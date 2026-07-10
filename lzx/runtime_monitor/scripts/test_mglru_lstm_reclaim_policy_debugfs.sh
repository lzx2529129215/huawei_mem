#!/usr/bin/env bash
set -euo pipefail

DEBUGFS_PATH="/sys/kernel/debug/lru_gen_workload_markov"
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debugfs-path)
      DEBUGFS_PATH="$2"
      shift 2
      ;;
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 2
      ;;
  esac
done

if ! sudo -n test -e "$DEBUGFS_PATH"; then
  echo "FAIL: debugfs 不存在: $DEBUGFS_PATH" >&2
  exit 1
fi

write_command() {
  printf '%s\n' "$1" | sudo -n tee "$DEBUGFS_PATH" >/dev/null
}

write_command "policy mode observe"
write_command "policy threshold 9000 5000 2000"
write_command "policy factor 700 750 1000 1100 1250"
write_command "policy bounds 700 1300 1 4096"
write_command "policy default 3000 1000 1000 0"
write_command "app probability 1 9500 300000"
write_command "app probability 2 7000 300000"
write_command "app probability 3 3500 300000"
write_command "app probability 4 1000 300000"

if [[ -n "$OUTPUT" ]]; then
  mkdir -p "$(dirname "$OUTPUT")"
  sudo -n cat "$DEBUGFS_PATH" > "$OUTPUT"
  RESULT_FILE="$OUTPUT"
else
  RESULT_FILE="$(mktemp)"
  trap 'rm -f "$RESULT_FILE"' EXIT
  sudo -n cat "$DEBUGFS_PATH" > "$RESULT_FILE"
fi

grep -q '^policy_config mode observe$' "$RESULT_FILE"
grep -q '^policy_config thresholds 9000 5000 2000$' "$RESULT_FILE"
grep -q '^prob 1 9500 ' "$RESULT_FILE"
grep -q '^prob 2 7000 ' "$RESULT_FILE"
grep -q '^prob 3 3500 ' "$RESULT_FILE"
grep -q '^prob 4 1000 ' "$RESULT_FILE"

echo "PASS: 策略参数和四组受控概率已由 debugfs 正确保存。"
