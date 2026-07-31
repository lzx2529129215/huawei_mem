#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
source_dir="$ROOT/work/linux-6.17"; build_dir="$ROOT/builds/linux-6.17-l02"
while (($#)); do case "$1" in --help) usage_header; echo "Usage: $0 [--source-dir DIR] [--build-dir DIR]"; exit 0;; --source-dir) source_dir=$2; shift 2;; --build-dir) build_dir=$2; shift 2;; *) die "unknown argument: $1";; esac; done
source_dir=$(absolute_path "$source_dir"); build_dir=$(absolute_path "$build_dir")
for f in arch/x86/boot/bzImage vmlinux System.map modules.order Module.symvers .config BUILD-METADATA.txt SHA256SUMS; do [[ -s "$build_dir/$f" ]] || die "missing build artifact: $build_dir/$f"; done
grep -q '^CONFIG_MYSELF_KSWAPD=y' "$build_dir/.config" || die 'CONFIG_MYSELF_KSWAPD is not y'; release=$(kernelrelease "$source_dir" "$build_dir"); grep -q "kernelrelease=$release" "$build_dir/BUILD-METADATA.txt" || die 'kernelrelease metadata mismatch'
(cd "$build_dir" && sha256sum -c SHA256SUMS)
for f in mm/myself_kswapd/heartbeat.o mm/myself_kswapd/adapter/observer_config.o mm/myself_kswapd/trace/trace.o mm/myself_kswapd/built-in.a; do [[ -s "$build_dir/$f" ]] || die "missing observer object: $f"; done
python3 "$ROOT/tools/myself_kswapd/tests/test_trace_event_arg_limits.py" "$source_dir/include/trace/events/myself_kswapd.h"; echo "Linux L0.2 build verification: PASS ($release)"
