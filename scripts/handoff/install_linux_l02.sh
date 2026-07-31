#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
execute=0; build_dir="$ROOT/builds/linux-6.17-l02"; source_dir="$ROOT/work/linux-6.17"
while (($#)); do case "$1" in --help) usage_header; echo "Usage: $0 [--build-dir DIR] [--source-dir DIR] [--execute]"; exit 0;; --build-dir) build_dir=$2; shift 2;; --source-dir) source_dir=$2; shift 2;; --execute) execute=1; shift;; *) die "unknown argument: $1";; esac; done
source_dir=$(absolute_path "$source_dir"); build_dir=$(absolute_path "$build_dir")
release=$(kernelrelease "$source_dir" "$build_dir"); bz="$build_dir/arch/x86/boot/bzImage"; [[ -s "$bz" ]] || die "missing bzImage: $bz"
if (( ! execute )); then echo "DRY RUN: no files changed. Would install release $release from $build_dir."; echo 'Re-run with --execute only under direct supervision; no reboot is performed.'; exit 0; fi
[[ $EUID -eq 0 ]] || die '--execute requires root (run via sudo explicitly)'; command -v update-initramfs >/dev/null || die 'update-initramfs is unavailable'; command -v update-grub >/dev/null || die 'update-grub is unavailable'
if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi enabled; then warn 'Secure Boot is enabled; unsigned kernel may not boot'; fi
cp -a -- /boot/grub/grub.cfg "/boot/grub/grub.cfg.handoff-backup-$(date +%Y%m%d%H%M%S)"; make -C "$source_dir" O="$build_dir" modules_install
install -m 0644 -- "$bz" "/boot/vmlinuz-$release"; install -m 0644 -- "$build_dir/System.map" "/boot/System.map-$release"; install -m 0644 -- "$build_dir/.config" "/boot/config-$release"; update-initramfs -c -k "$release"; update-grub
echo "Installed $release; reboot was not performed. Select it manually from GRUB after review."
