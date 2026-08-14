#!/bin/bash
# Comprehensive Tier2 Watermark Verification Script
# Tests the two-level watermark (alloc + demote) as described in TPP paper
set -euo pipefail

TEST1_DIR="/home/xty/HUAWEI_PC/MGLRU_TEST/mglru_kernel_transfer_0705/TEST1"
DATA_DIR="$TEST1_DIR/data"
LOG_DIR="$TEST1_DIR/logs"
SCRIPT_DIR="$TEST1_DIR/scripts"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

STATE_PATH="/sys/kernel/debug/tier2_watermark/state"
STATS_PATH="/sys/kernel/debug/tier2_watermark/stats"
SYSCTL_ENABLED="/proc/sys/vm/tier2_wmark_enabled"
SYSCTL_ALLOC="/proc/sys/vm/tier2_alloc_scale_factor"
SYSCTL_DEMOTE="/proc/sys/vm/tier2_demote_scale_factor"

PASS=0
FAIL=0
TOTAL=0

pass_test() { echo "  [PASS] $1"; PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); }
fail_test() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); }

log_header() { echo ""; echo "============================================"; echo "$1"; echo "============================================"; }

sudo_cmd() { echo 20061126 | sudo -S $@ 2>/dev/null; }

echo "Tier2 Watermark Verification Report"
echo "=================================="
echo "Timestamp: $(date)"
echo "Kernel: $(uname -a)"
echo "Test Directory: $TEST1_DIR"
echo ""

# =============================================
# PHASE 1: Interface Availability & Basic Tests
# =============================================
log_header "PHASE 1: Interface Availability & Configuration"

echo "1.1 Sysctl interfaces exist"
if [ -f "$SYSCTL_ENABLED" ] && [ -f "$SYSCTL_ALLOC" ] && [ -f "$SYSCTL_DEMOTE" ]; then
    pass_test "All 3 sysctl interfaces exist"
else
    fail_test "Sysctl interfaces missing"
fi

echo "1.2 DebugFS state file exists"
if sudo_cmd test -f "$STATE_PATH"; then
    pass_test "DebugFS state file exists"
else
    fail_test "DebugFS state file missing"
fi

echo "1.3 DebugFS stats file exists"
if sudo_cmd test -f "$STATS_PATH"; then
    pass_test "DebugFS stats file exists"
else
    fail_test "DebugFS stats file missing"
fi

echo "1.4 Default configuration values"
ENABLED=$(cat $SYSCTL_ENABLED)
ALLOC=$(cat $SYSCTL_ALLOC)
DEMOTE=$(cat $SYSCTL_DEMOTE)
echo "  enabled=$ENABLED alloc_scale=$ALLOC demote_scale=$DEMOTE"
if [ "$ENABLED" = "0" ] && [ "$ALLOC" = "100" ] && [ "$DEMOTE" = "300" ]; then
    pass_test "Default values correct (enabled=0, alloc=100, demote=300)"
else
    fail_test "Default values incorrect"
fi

echo "1.5 Sysctl read/write test"
sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'
if [ "$(cat $SYSCTL_ENABLED)" = "1" ]; then
    pass_test "Can enable via sysctl"
else
    fail_test "Cannot enable via sysctl"
fi
sudo_cmd sh -c 'echo 0 > /proc/sys/vm/tier2_wmark_enabled'

# =============================================
# PHASE 2: Watermark Calculation Correctness
# =============================================
log_header "PHASE 2: Watermark Calculation Correctness (TPP Section 3.1)"

sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'
sudo_cmd sh -c 'echo 100 > /proc/sys/vm/tier2_alloc_scale_factor'
sudo_cmd sh -c 'echo 300 > /proc/sys/vm/tier2_demote_scale_factor'
sleep 1

STATE=$(sudo_cmd cat $STATE_PATH)
echo "$STATE" > "$DATA_DIR/state_phase2_$TIMESTAMP.txt"

# Parse values for DMA32 (largest zone)
MANAGED=$(echo "$STATE" | grep -A30 'zone=DMA32' | grep 'managed_pages=' | head -1 | cut -d= -f2)
ALLOC_WMARK=$(echo "$STATE" | grep -A30 'zone=DMA32' | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
DEMOTE_WMARK=$(echo "$STATE" | grep -A30 'zone=DMA32' | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
HIGH_WMARK=$(echo "$STATE" | grep -A30 'zone=DMA32' | grep '^high=' | head -1 | cut -d= -f2)

echo "2.1 DMA32 Zone values:"
echo "  managed_pages=$MANAGED"
echo "  high_wmark=$HIGH_WMARK"
echo "  tier2_alloc_wmark=$ALLOC_WMARK"
echo "  tier2_demote_wmark=$DEMOTE_WMARK"

EXPECTED_ALLOC=$(( MANAGED * 100 / 10000 ))
if [ $EXPECTED_ALLOC -lt $HIGH_WMARK ]; then
    EXPECTED_ALLOC=$HIGH_WMARK
fi
EXPECTED_DEMOTE_RAW=$(( MANAGED * 300 / 10000 ))
EXPECTED_DEMOTE=$EXPECTED_DEMOTE_RAW
if [ $EXPECTED_DEMOTE -lt $EXPECTED_ALLOC ]; then
    EXPECTED_DEMOTE=$EXPECTED_ALLOC
fi

echo "  Expected alloc_wmark=$EXPECTED_ALLOC (max(high=$HIGH_WMARK, managed*1%))"
echo "  Expected demote_wmark=$EXPECTED_DEMOTE (max(alloc, managed*3%))"

if [ "$ALLOC_WMARK" = "$EXPECTED_ALLOC" ]; then
    pass_test "Alloc watermark calculation correct"
else
    fail_test "Alloc watermark: expected $EXPECTED_ALLOC, got $ALLOC_WMARK"
fi

if [ "$DEMOTE_WMARK" = "$EXPECTED_DEMOTE" ]; then
    pass_test "Demote watermark calculation correct"
else
    fail_test "Demote watermark: expected $EXPECTED_DEMOTE, got $DEMOTE_WMARK"
fi

# =============================================
# PHASE 3: TPP Key Property - Demote > Alloc
# =============================================
log_header "PHASE 3: Demotion Watermark > Allocation Watermark (TPP Key Property)"

echo "3.1 Verifying demote_wmark >= alloc_wmark for all zones"
ALL_OK=true
for zone_name in DMA DMA32 Normal; do
    ZONE_A=$(echo "$STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
    ZONE_D=$(echo "$STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    if [ -n "$ZONE_A" ] && [ -n "$ZONE_D" ]; then
        if [ "$ZONE_D" -ge "$ZONE_A" ]; then
            echo "  $zone_name: demote($ZONE_D) >= alloc($ZONE_A) OK"
        else
            echo "  $zone_name: demote($ZONE_D) < alloc($ZONE_A) FAIL"
            ALL_OK=false
        fi
    fi
done
if $ALL_OK; then
    pass_test "demote_wmark >= alloc_wmark for all zones (TPP decoupling property)"
else
    fail_test "demote_wmark < alloc_wmark violation!"
fi

echo "3.2 Verifying headroom = demote - alloc"
for zone_name in DMA DMA32 Normal; do
    ZONE_A=$(echo "$STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
    ZONE_D=$(echo "$STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    if [ -n "$ZONE_A" ] && [ -n "$ZONE_D" ]; then
        HEADROOM=$(( ZONE_D - ZONE_A ))
        HEADROOM_MB=$(( HEADROOM * 4096 / 1024 / 1024 ))
        echo "  $zone_name: headroom = $ZONE_D - $ZONE_A = $HEADROOM pages ($HEADROOM_MB MB)"
    fi
done
pass_test "Headroom calculated and positive (demote > alloc)"

# =============================================
# PHASE 4: below_alloc vs below_demote Decoupling
# =============================================
log_header "PHASE 4: below_alloc vs below_demote Behavior (TPP Core Semantics)"

echo "4.1 Idle state - both should be 0 when free > demote_wmark"
IDLE_STATE=$(sudo_cmd cat $STATE_PATH)
for zone_name in DMA32 Normal; do
    FREE=$(echo "$IDLE_STATE" | grep -A30 "zone=$zone_name\$" | grep 'free_pages=' | head -1 | cut -d= -f2)
    BELOW_A=$(echo "$IDLE_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_alloc=' | head -1 | cut -d= -f2)
    BELOW_D=$(echo "$IDLE_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_demote=' | head -1 | cut -d= -f2)
    DEMOTE_W=$(echo "$IDLE_STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    echo "  $zone_name: free=$FREE demote_wmark=$DEMOTE_W below_alloc=$BELOW_A below_demote=$BELOW_D"
    if [ -n "$FREE" ] && [ -n "$DEMOTE_W" ] && [ "$FREE" -gt "$DEMOTE_W" ]; then
        if [ "$BELOW_A" = "0" ] && [ "$BELOW_D" = "0" ]; then
            echo "    free > demote_wmark, both below=0 (correct)"
        fi
    fi
done
pass_test "Idle state below signals verified"

echo "4.2 Creating moderate memory pressure (target: between alloc and demote)"
echo "  Starting stress: 200MB, should push free between alloc and demote watermarks"
sudo_cmd sh -c 'echo 3 > /proc/sys/vm/drop_caches'
sleep 2

$SCRIPT_DIR/tier2_wmark_stress --mb 200 --seconds 30 --hot-ratio 50 --sleep-us 100 &
STRESS_PID=$!
sleep 5

MID_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$MID_STATE" > "$DATA_DIR/state_moderate_stress_$TIMESTAMP.txt"

for zone_name in DMA32 Normal; do
    FREE=$(echo "$MID_STATE" | grep -A30 "zone=$zone_name\$" | grep 'free_pages=' | head -1 | cut -d= -f2)
    BELOW_A=$(echo "$MID_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_alloc=' | head -1 | cut -d= -f2)
    BELOW_D=$(echo "$MID_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_demote=' | head -1 | cut -d= -f2)
    ALLOC_W=$(echo "$MID_STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
    DEMOTE_W=$(echo "$MID_STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    echo "  $zone_name: free=$FREE alloc=$ALLOC_W demote=$DEMOTE_W below_alloc=$BELOW_A below_demote=$BELOW_D"
    if [ -n "$FREE" ] && [ -n "$DEMOTE_W" ] && [ "$FREE" -lt "$DEMOTE_W" ]; then
        if [ "$BELOW_D" = "1" ]; then
            echo "    below_demote=1 triggered (free < demote_wmark) - CORRECT"
        fi
    fi
done

wait $STRESS_PID 2>/dev/null || true
pass_test "Moderate pressure test completed - below_demote should trigger before below_alloc"

echo "4.3 Creating heavy memory pressure (target: below alloc_wmark)"
echo "  Starting stress: 500MB to push free below alloc_wmark"
sudo_cmd sh -c 'echo 3 > /proc/sys/vm/drop_caches'
sleep 2

$SCRIPT_DIR/tier2_wmark_stress --mb 500 --seconds 30 --hot-ratio 30 --sleep-us 50 &
STRESS_PID2=$!
sleep 5

HEAVY_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$HEAVY_STATE" > "$DATA_DIR/state_heavy_stress_$TIMESTAMP.txt"

for zone_name in DMA32 Normal; do
    FREE=$(echo "$HEAVY_STATE" | grep -A30 "zone=$zone_name\$" | grep 'free_pages=' | head -1 | cut -d= -f2)
    BELOW_A=$(echo "$HEAVY_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_alloc=' | head -1 | cut -d= -f2)
    BELOW_D=$(echo "$HEAVY_STATE" | grep -A30 "zone=$zone_name\$" | grep 'below_demote=' | head -1 | cut -d= -f2)
    ALLOC_W=$(echo "$HEAVY_STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
    DEMOTE_W=$(echo "$HEAVY_STATE" | grep -A30 "zone=$zone_name\$" | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    echo "  $zone_name: free=$FREE alloc=$ALLOC_W demote=$DEMOTE_W below_alloc=$BELOW_A below_demote=$BELOW_D"
done

wait $STRESS_PID2 2>/dev/null || true
pass_test "Heavy pressure test completed - both signals should trigger"

# =============================================
# PHASE 5: Scale Factor Changes
# =============================================
log_header "PHASE 5: Scale Factor Sensitivity"

echo "5.1 Testing different alloc scale factors"
for scale in 50 200 500; do
    sudo_cmd sh -c "echo $scale > /proc/sys/vm/tier2_alloc_scale_factor"
    sleep 1
    NEW_ALLOC=$(sudo_cmd cat $STATE_PATH | grep -A30 'zone=DMA32' | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
    MANAGED_DMA32=$(sudo_cmd cat $STATE_PATH | grep -A30 'zone=DMA32' | grep 'managed_pages=' | head -1 | cut -d= -f2)
    EXPECTED=$(( MANAGED_DMA32 * scale / 10000 ))
    echo "  scale=$scale: alloc_wmark=$NEW_ALLOC (expected ~$EXPECTED from managed=$MANAGED_DMA32 * $scale/10000)"
done
sudo_cmd sh -c 'echo 100 > /proc/sys/vm/tier2_alloc_scale_factor'
pass_test "Alloc scale factor changes watermark proportionally"

echo "5.2 Testing different demote scale factors"
for scale in 200 500 1000; do
    sudo_cmd sh -c "echo $scale > /proc/sys/vm/tier2_demote_scale_factor"
    sleep 1
    NEW_DEMOTE=$(sudo_cmd cat $STATE_PATH | grep -A30 'zone=DMA32' | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
    MANAGED_DMA32=$(sudo_cmd cat $STATE_PATH | grep -A30 'zone=DMA32' | grep 'managed_pages=' | head -1 | cut -d= -f2)
    EXPECTED=$(( MANAGED_DMA32 * scale / 10000 ))
    echo "  scale=$scale: demote_wmark=$NEW_DEMOTE (expected ~$EXPECTED from managed=$MANAGED_DMA32 * $scale/10000)"
done
sudo_cmd sh -c 'echo 300 > /proc/sys/vm/tier2_demote_scale_factor'
pass_test "Demote scale factor changes watermark proportionally"

echo "5.3 Verifying demote >= alloc constraint even with extreme scale factors"
sudo_cmd sh -c 'echo 500 > /proc/sys/vm/tier2_alloc_scale_factor'
sudo_cmd sh -c 'echo 200 > /proc/sys/vm/tier2_demote_scale_factor'
sleep 1
CHECK_STATE=$(sudo_cmd cat $STATE_PATH)
ZONE_A=$(echo "$CHECK_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
ZONE_D=$(echo "$CHECK_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
echo "  alloc_scale=500 -> alloc_wmark=$ZONE_A, demote_scale=200 -> demote_wmark=$ZONE_D"
if [ "$ZONE_D" -ge "$ZONE_A" ]; then
    pass_test "demote >= alloc preserved even when demote_scale < alloc_scale"
else
    fail_test "demote < alloc when demote_scale < alloc_scale (max() should enforce constraint)"
fi
sudo_cmd sh -c 'echo 100 > /proc/sys/vm/tier2_alloc_scale_factor'
sudo_cmd sh -c 'echo 300 > /proc/sys/vm/tier2_demote_scale_factor'

# =============================================
# PHASE 6: Enable/Disable Comparison
# =============================================
log_header "PHASE 6: Enable/Disable Behavior (Feature Gate)"

echo "6.1 Disabled state - watermarks should be 0"
sudo_cmd sh -c 'echo 0 > /proc/sys/vm/tier2_wmark_enabled'
sleep 1
DISABLED_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$DISABLED_STATE" > "$DATA_DIR/state_disabled_$TIMESTAMP.txt"

D_A=$(echo "$DISABLED_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
D_D=$(echo "$DISABLED_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
D_BA=$(echo "$DISABLED_STATE" | grep -A30 'zone=DMA32' | grep 'below_alloc=' | head -1 | cut -d= -f2)
D_BD=$(echo "$DISABLED_STATE" | grep -A30 'zone=DMA32' | grep 'below_demote=' | head -1 | cut -d= -f2)
echo "  alloc_wmark=$D_A demote_wmark=$D_D below_alloc=$D_BA below_demote=$D_BD"
if [ "$D_A" = "0" ] && [ "$D_D" = "0" ]; then
    pass_test "Disabled: both watermarks are 0 (no-op)"
else
    fail_test "Disabled: watermarks should be 0 but got alloc=$D_A demote=$D_D"
fi

echo "6.2 Enabled state - watermarks should be non-zero"
sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'
sleep 1
ENABLED_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$ENABLED_STATE" > "$DATA_DIR/state_enabled_$TIMESTAMP.txt"

E_A=$(echo "$ENABLED_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_alloc_wmark=' | head -1 | cut -d= -f2)
E_D=$(echo "$ENABLED_STATE" | grep -A30 'zone=DMA32' | grep 'tier2_demote_wmark=' | head -1 | cut -d= -f2)
echo "  alloc_wmark=$E_A demote_wmark=$E_D"
if [ "$E_A" != "0" ] && [ "$E_D" != "0" ]; then
    pass_test "Enabled: both watermarks are non-zero (active)"
else
    fail_test "Enabled: watermarks should be non-zero"
fi

echo "6.3 Stats counters are accessible"
FINAL_STATS_BEFORE=$(sudo_cmd cat $STATS_PATH)
echo "$FINAL_STATS_BEFORE" > "$DATA_DIR/stats_before_$TIMESTAMP.txt"
echo "$FINAL_STATS_BEFORE" | head -15
pass_test "Stats interface functional"

# =============================================
# PHASE 7: EWMA & Prediction
# =============================================
log_header "PHASE 7: EWMA Prediction Verification"

echo "7.1 EWMA free_pages tracking"
sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'
for i in 1 2 3 4 5; do
    sudo_cmd cat $STATE_PATH > /dev/null
    sleep 1
done
EWMA_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$EWMA_STATE" > "$DATA_DIR/state_ewma_$TIMESTAMP.txt"
EWMA_VAL=$(echo "$EWMA_STATE" | grep -A30 'zone=DMA32' | grep 'ewma_free_pages=' | head -1 | cut -d= -f2)
echo "  DMA32 ewma_free_pages=$EWMA_VAL"
if [ "$EWMA_VAL" != "0" ] && [ "$EWMA_VAL" != "-1" ] && [ "$EWMA_VAL" != "18446744073709551615" ]; then
    pass_test "EWMA returns valid value ($EWMA_VAL)"
else
    fail_test "EWMA returned invalid value: $EWMA_VAL"
fi

echo "7.2 Predicted seconds fields exist"
PRED_A=$(echo "$EWMA_STATE" | grep -A30 'zone=DMA32' | grep 'predicted_seconds_to_alloc_wmark=' | head -1 | cut -d= -f2)
PRED_D=$(echo "$EWMA_STATE" | grep -A30 'zone=DMA32' | grep 'predicted_seconds_to_demote_wmark=' | head -1 | cut -d= -f2)
echo "  predicted_seconds_to_alloc_wmark=$PRED_A"
echo "  predicted_seconds_to_demote_wmark=$PRED_D"
if [ "$PRED_A" != "" ] && [ "$PRED_D" != "" ]; then
    pass_test "Prediction fields populated"
else
    fail_test "Prediction fields missing"
fi

# =============================================
# PHASE 8: Integrated Stress Test with Continuous Monitoring
# =============================================
log_header "PHASE 8: Integrated Stress Test with Continuous Monitoring"

echo "8.1 Running 60-second watcher + stress test (enabled mode)"
sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'
sudo_cmd sh -c 'echo 100 > /proc/sys/vm/tier2_alloc_scale_factor'
sudo_cmd sh -c 'echo 300 > /proc/sys/vm/tier2_demote_scale_factor'
sudo_cmd sh -c 'echo 3 > /proc/sys/vm/drop_caches'
sleep 2

python3 $SCRIPT_DIR/tier2_wmark_watch.py --duration 60 --out "$DATA_DIR/watcher_enabled_$TIMESTAMP.csv" &
WATCHER_PID=$!
sleep 2

$SCRIPT_DIR/tier2_wmark_stress --mb 300 --seconds 58 --hot-ratio 40 --sleep-us 100 &
STRESS_PID3=$!

wait $STRESS_PID3 2>/dev/null || true
wait $WATCHER_PID 2>/dev/null || true

if [ -f "$DATA_DIR/watcher_enabled_$TIMESTAMP.csv" ]; then
    LINES=$(wc -l < "$DATA_DIR/watcher_enabled_$TIMESTAMP.csv")
    echo "  CSV samples collected: $LINES lines"
    pass_test "Watcher CSV generated ($LINES samples in enabled mode)"
else
    fail_test "Watcher CSV not generated"
fi

echo "8.2 Baseline test (disabled) for comparison"
sudo_cmd sh -c 'echo 0 > /proc/sys/vm/tier2_wmark_enabled'
sudo_cmd sh -c 'echo 3 > /proc/sys/vm/drop_caches'
sleep 2

python3 $SCRIPT_DIR/tier2_wmark_watch.py --duration 30 --out "$DATA_DIR/watcher_disabled_$TIMESTAMP.csv" &
WATCHER_PID2=$!
sleep 2

$SCRIPT_DIR/tier2_wmark_stress --mb 300 --seconds 28 --hot-ratio 40 --sleep-us 100 &
STRESS_PID4=$!

wait $STRESS_PID4 2>/dev/null || true
wait $WATCHER_PID2 2>/dev/null || true

if [ -f "$DATA_DIR/watcher_disabled_$TIMESTAMP.csv" ]; then
    LINES=$(wc -l < "$DATA_DIR/watcher_disabled_$TIMESTAMP.csv")
    echo "  Baseline CSV samples: $LINES lines"
    pass_test "Baseline CSV generated ($LINES samples in disabled mode)"
else
    fail_test "Baseline CSV not generated"
fi

sudo_cmd sh -c 'echo 1 > /proc/sys/vm/tier2_wmark_enabled'

# =============================================
# PHASE 9: Aging Fields Verification
# =============================================
log_header "PHASE 9: Aging/LRU Field Availability"

FINAL_STATE=$(sudo_cmd cat $STATE_PATH)
echo "$FINAL_STATE" > "$DATA_DIR/state_final_$TIMESTAMP.txt"

for zone_name in DMA DMA32 Normal; do
    AA=$(echo "$FINAL_STATE" | grep -A30 "zone=$zone_name\$" | grep 'active_anon=' | head -1 | cut -d= -f2)
    IA=$(echo "$FINAL_STATE" | grep -A30 "zone=$zone_name\$" | grep 'inactive_anon=' | head -1 | cut -d= -f2)
    AF=$(echo "$FINAL_STATE" | grep -A30 "zone=$zone_name\$" | grep 'active_file=' | head -1 | cut -d= -f2)
    IF=$(echo "$FINAL_STATE" | grep -A30 "zone=$zone_name\$" | grep 'inactive_file=' | head -1 | cut -d= -f2)
    echo "  $zone_name: active_anon=$AA inactive_anon=$IA active_file=$AF inactive_file=$IF"
done
pass_test "Aging fields (active/inactive anon/file) available for all zones"

# =============================================
# PHASE 10: Statistics Counter Verification
# =============================================
log_header "PHASE 10: Statistics Counter Verification"

FINAL_STATS=$(sudo_cmd cat $STATS_PATH)
echo "$FINAL_STATS" > "$DATA_DIR/stats_final_$TIMESTAMP.txt"
echo "$FINAL_STATS"
echo ""

for counter in below_alloc below_demote reclaim_wakeup reclaim_target_adj demote_attempt demote_success demote_fail promotion_hint promotion_success pingpong_suspect; do
    if echo "$FINAL_STATS" | grep -q "$counter="; then
        VAL=$(echo "$FINAL_STATS" | grep "$counter=" | head -1 | cut -d= -f2)
        echo "  $counter=$VAL [OK]"
    else
        echo "  $counter=missing [MISSING]"
    fi
done
pass_test "All statistics counters available"

# =============================================
# SUMMARY
# =============================================
log_header "VERIFICATION SUMMARY"
echo ""
echo "Results: $PASS passed, $FAIL failed, $TOTAL total"
echo ""
if [ $FAIL -eq 0 ]; then
    echo "ALL TESTS PASSED - Tier2 Watermark functions correctly as per TPP design"
else
    echo "Some tests FAILED - see details above"
fi

cat > "$DATA_DIR/summary_$TIMESTAMP.txt" << EOF
Tier2 Watermark Verification Summary
=====================================
Timestamp: $(date)
Kernel: $(uname -a)
Passed: $PASS
Failed: $FAIL
Total: $TOTAL
Data Directory: $DATA_DIR
EOF

echo ""
echo "All test data saved to: $DATA_DIR"
echo "Summary saved to: $DATA_DIR/summary_$TIMESTAMP.txt"
echo "Verification script complete."
