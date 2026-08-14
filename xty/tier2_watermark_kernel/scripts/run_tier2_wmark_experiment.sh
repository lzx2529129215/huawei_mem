#!/bin/bash
# Tier-2 Watermark Experiment Runner
# Runs baseline (disabled) and enabled experiments, collects data.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXP_DIR="${EXP_DIR:-$SCRIPT_DIR}"
LOG_DIR="${EXP_DIR}/logs"
mkdir -p "$LOG_DIR"

# Configuration
DURATION=60
STRESS_MB=256
HOT_RATIO=30
STATE_PATH="/sys/kernel/debug/tier2_watermark/state"
STATS_PATH="/sys/kernel/debug/tier2_watermark/stats"
SYSCTL_PREFIX="/proc/sys/vm"

echo "============================================"
echo " Tier-2 Watermark Experiment"
echo " Started at: $(date)"
echo " Log dir: $LOG_DIR"
echo "============================================"

# Step 1: Record environment
echo ""
echo "=== Step 1: Environment Info ==="
uname -a | tee "$LOG_DIR/uname.txt"
echo "Kernel: $(uname -r)"

# NUMA topology
if command -v numactl &>/dev/null; then
    numactl --hardware 2>&1 | tee "$LOG_DIR/numactl.txt" || true
else
    echo "numactl not available" | tee "$LOG_DIR/numactl.txt"
fi

cat /proc/meminfo > "$LOG_DIR/meminfo_before.txt"
cat /proc/zoneinfo > "$LOG_DIR/zoneinfo_before.txt"
cat /proc/vmstat > "$LOG_DIR/vmstat_before.txt"
echo "Saved meminfo, zoneinfo, vmstat"

# Step 2: Check interfaces
echo ""
echo "=== Step 2: Interface Check ==="

check_sysctl() {
    local key="$1"
    local path="${SYSCTL_PREFIX}/${key}"
    if [ -f "$path" ]; then
        echo "  [OK] $path = $(cat "$path" 2>/dev/null || echo 'read error')"
    else
        echo "  [MISSING] $path"
    fi
}

check_sysctl "tier2_wmark_enabled"
check_sysctl "tier2_alloc_scale_factor"
check_sysctl "tier2_demote_scale_factor"

# Debugfs state/stats
if [ -f "$STATE_PATH" ]; then
    echo "  [OK] $STATE_PATH"
else
    echo "  [MISSING] $STATE_PATH - check CONFIG_DEBUG_FS and mount"
    # Try mounting debugfs
    if ! mount | grep -q debugfs; then
        echo "  Attempting to mount debugfs..."
        sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
    fi
fi

if [ -f "$STATS_PATH" ]; then
    echo "  [OK] $STATS_PATH"
else
    echo "  [MISSING] $STATS_PATH"
fi

# Step 3: Compile tools if needed
echo ""
echo "=== Step 3: Build Tools ==="
cd "$SCRIPT_DIR"

if [ ! -x "./tier2_wmark_stress" ]; then
    echo "Compiling stress tool..."
    gcc -Wall -O2 -o tier2_wmark_stress tier2_wmark_stress.c || {
        echo "ERROR: compile failed"
        exit 1
    }
    echo "Compiled OK"
fi

chmod +x tier2_wmark_watch.py

# Step 4: Baseline run (disabled)
echo ""
echo "=== Step 4: Baseline (Disabled) ==="
echo "Disabling tier2 watermark..."
echo 0 | sudo tee ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || {
    echo "WARNING: Could not write sysctl (no sudo?). Trying anyway..."
    echo 0 > ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || true
}

echo "Sleeping 2s for stabilization..."
sleep 2

echo "Starting baseline watcher..."
python3 tier2_wmark_watch.py --duration $DURATION --out "$LOG_DIR/baseline.csv" \
    --state-path "$STATE_PATH" &
WATCHER_PID=$!

sleep 1

echo "Starting baseline stress test..."
./tier2_wmark_stress --mb $STRESS_MB --seconds $DURATION --hot-ratio $HOT_RATIO || true

wait $WATCHER_PID 2>/dev/null || true
echo "Baseline complete"

cat /proc/vmstat > "$LOG_DIR/vmstat_baseline.txt"
cat "$STATE_PATH" 2>/dev/null > "$LOG_DIR/state_baseline.txt" || echo "No state file" > "$LOG_DIR/state_baseline.txt"
cat "$STATS_PATH" 2>/dev/null > "$LOG_DIR/stats_baseline.txt" || echo "No stats file" > "$LOG_DIR/stats_baseline.txt"

# Step 5: Enabled run
echo ""
echo "=== Step 5: Enabled Run ==="
echo "Enabling tier2 watermark..."
echo 1 | sudo tee ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || {
    echo 1 > ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || true
}

# Set scale factors more aggressively for testing
echo 100 | sudo tee ${SYSCTL_PREFIX}/tier2_alloc_scale_factor 2>/dev/null || true
echo 500 | sudo tee ${SYSCTL_PREFIX}/tier2_demote_scale_factor 2>/dev/null || true

echo "Current settings:"
echo "  enabled = $(cat ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || echo ?)"
echo "  alloc_scale = $(cat ${SYSCTL_PREFIX}/tier2_alloc_scale_factor 2>/dev/null || echo ?)"
echo "  demote_scale = $(cat ${SYSCTL_PREFIX}/tier2_demote_scale_factor 2>/dev/null || echo ?)"

echo "Sleeping 2s for stabilization..."
sleep 2

echo "Starting enabled watcher..."
python3 tier2_wmark_watch.py --duration $DURATION --out "$LOG_DIR/enabled.csv" \
    --state-path "$STATE_PATH" &
WATCHER_PID=$!

sleep 1

echo "Starting enabled stress test..."
./tier2_wmark_stress --mb $STRESS_MB --seconds $DURATION --hot-ratio $HOT_RATIO || true

wait $WATCHER_PID 2>/dev/null || true
echo "Enabled run complete"

cat /proc/vmstat > "$LOG_DIR/vmstat_enabled.txt"
cat "$STATE_PATH" 2>/dev/null > "$LOG_DIR/state_enabled.txt" || echo "No state file" > "$LOG_DIR/state_enabled.txt"
cat "$STATS_PATH" 2>/dev/null > "$LOG_DIR/stats_enabled.txt" || echo "No stats file" > "$LOG_DIR/stats_enabled.txt"

# Restore settings
echo 0 | sudo tee ${SYSCTL_PREFIX}/tier2_wmark_enabled 2>/dev/null || true

# Step 6: Compare
echo ""
echo "=== Step 6: Comparison ==="
echo ""
echo "--- Baseline CSV ---"
if [ -f "$LOG_DIR/baseline.csv" ]; then
    wc -l "$LOG_DIR/baseline.csv"
    head -3 "$LOG_DIR/baseline.csv"
else
    echo "No baseline CSV"
fi

echo ""
echo "--- Enabled CSV ---"
if [ -f "$LOG_DIR/enabled.csv" ]; then
    wc -l "$LOG_DIR/enabled.csv"
    head -3 "$LOG_DIR/enabled.csv"
else
    echo "No enabled CSV"
fi

echo ""
echo "--- State Output ---"
if [ -f "$STATE_PATH" ]; then
    cat "$STATE_PATH"
else
    echo "State file not available"
fi

echo ""
echo "--- Stats Output ---"
if [ -f "$STATS_PATH" ]; then
    cat "$STATS_PATH"
else
    echo "Stats file not available"
fi

echo ""
echo "============================================"
echo " Experiment completed at: $(date)"
echo " All logs in: $LOG_DIR"
echo "============================================"
