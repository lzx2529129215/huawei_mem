#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
USER_ROOT="$ROOT/用户态模拟器/v1"
OUT="$USER_ROOT/output/task19"
REPORT="$ROOT/docs/reports/linux-l02-validation.md"
mkdir -p "$OUT" "$ROOT/docs/reports"
LOCK_FILE="$OUT/.check_l02.lock"
APPENDIX=$(mktemp)
trap 'rm -f -- "$APPENDIX"' EXIT
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "another L0.2 validation run is already active" >&2
    exit 1
fi
if [[ -f "$REPORT" ]]; then
    sed -n '/^## Runtime smoke/,$p' "$REPORT" > "$APPENDIX"
fi
exec > >(tee "$OUT/validation.log") 2>&1

echo "# Linux L0.2 validation"
echo
echo "- date: $(date --iso-8601=seconds)"
echo "- branch: $(git -C "$ROOT" branch --show-current)"
echo

python3 -m unittest discover -s "$ROOT/tools/myself_kswapd/tests" -p 'test_*.py'
cmake -S "$USER_ROOT" -B "$OUT/default" -DCMAKE_BUILD_TYPE=Debug -DRECLAIM_ENABLE_TESTS=ON
cmake --build "$OUT/default" --parallel
ctest --test-dir "$OUT/default" --output-on-failure

cmake -S "$USER_ROOT" -B "$OUT/asan" -DCMAKE_BUILD_TYPE=Debug \
    -DRECLAIM_ENABLE_TESTS=ON -DRECLAIM_ENABLE_SANITIZERS=ON
cmake --build "$OUT/asan" --parallel
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
    UBSAN_OPTIONS=halt_on_error=1 \
    ctest --test-dir "$OUT/asan" --output-on-failure

for run in $(seq 1 100); do
    "$OUT/default/bin/reclaim_tests" >/dev/null
done
echo "100-run user-space tests: PASS"

KERNEL="$ROOT/Linux6.17"
BASE="$ROOT/patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch"
PATCH_CHECK=$(mktemp -d)
cleanup() {
    rm -rf -- "$PATCH_CHECK"
    rm -f -- "$APPENDIX"
}
trap cleanup EXIT
cp -a "$ROOT/../myself-kswapd-l01/Linux6.17" "$PATCH_CHECK/Linux6.17"
(cd "$PATCH_CHECK" && git apply --check "$BASE")

kernel_object_build() {
    local name="$1"
    shift
    local build="/tmp/myself-kswapd-l02-$name"
    rm -rf -- "$build"
    mkdir -p "$build"
    make -C "$KERNEL" O="$build" defconfig
    "$KERNEL/scripts/config" --file "$build/.config" \
        --enable MYSELF_KSWAPD --enable MYSELF_KSWAPD_KUNIT_TEST \
        "$@"
    make -C "$KERNEL" O="$build" olddefconfig prepare
    make -C "$KERNEL" O="$build" M=mm/myself_kswapd \
        adapter/lruvec_sample.o heartbeat.o debugfs/lruvec_debugfs.o \
        tests/lruvec_observer_test.o
    find "$KERNEL/mm/myself_kswapd" -type f \
        \( -name '.*.cmd' -o -name '*.o' -o -name modules.order \
        -o -name Module.symvers \) -delete
    echo "kernel $name: PASS"
}

kernel_object_build memcg-y-lru-n-debug-y --enable MEMCG --disable LRU_GEN --enable DEBUG_FS
kernel_object_build memcg-n-lru-n-debug-y --disable MEMCG --disable LRU_GEN --enable DEBUG_FS
kernel_object_build memcg-y-lru-y-debug-y --enable MEMCG --enable LRU_GEN --enable DEBUG_FS
kernel_object_build debugfs-n --enable MEMCG --disable LRU_GEN --disable DEBUG_FS

bash -n "$ROOT/tools/myself_kswapd"/*.sh "$ROOT/tools/myself_kswapd/tests"/*.sh
CLI="$OUT/default/bin/lruvec_observer_cli" \
    bash "$ROOT/tools/myself_kswapd/tests/test_lruvec_cli.sh"
bash "$ROOT/tools/myself_kswapd/tests/test_bootstrap_l02_tree.sh"
bash "$ROOT/tools/myself_kswapd/tests/test_refresh_l02_patch.sh"
bash "$ROOT/tools/myself_kswapd/tests/test_capture_lruvec_trace.sh"
git -C "$ROOT" diff --check
echo "shell tests, syntax and diff check: PASS"
echo "validation complete"
cp "$OUT/validation.log" "$REPORT"
if [[ -s "$APPENDIX" ]]; then
    printf '\n' >> "$REPORT"
    cat "$APPENDIX" >> "$REPORT"
fi
