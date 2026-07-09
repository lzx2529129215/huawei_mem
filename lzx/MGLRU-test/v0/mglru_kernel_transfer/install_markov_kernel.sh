#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SRC_DIR:-$SCRIPT_DIR/linux-hwe-6.17-6.17.0}"
BUILD_DIR="${BUILD_DIR:-$SCRIPT_DIR/linux-hwe-6.17-mglru-build}"
LOCALVERSION="${LOCALVERSION:--mglru}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example:" >&2
  echo "  sudo $0" >&2
  exit 1
fi

release="$(make -s -C "$SRC_DIR" O="$BUILD_DIR" LOCALVERSION="$LOCALVERSION" kernelrelease)"
echo "Installing kernel release: $release"

if [[ ! -s "$BUILD_DIR/vmlinux" || ! -s "$BUILD_DIR/arch/x86/boot/bzImage" ]]; then
  echo "Build artifacts are missing. Run build_on_target.sh first." >&2
  exit 1
fi

if ! grep -a -q 'lru_gen_workload_markov' "$BUILD_DIR/vmlinux"; then
  echo "Built vmlinux does not contain lru_gen_workload_markov." >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="/boot/mglru-backup-$timestamp"
mkdir -p "$backup_dir"
for path in \
  "/boot/vmlinuz-$release" \
  "/boot/initrd.img-$release" \
  "/boot/System.map-$release" \
  "/boot/config-$release"; do
  if [[ -e "$path" ]]; then
    cp -a "$path" "$backup_dir/"
  fi
done
echo "Backed up existing boot files to: $backup_dir"

make -C "$SRC_DIR" O="$BUILD_DIR" LOCALVERSION="$LOCALVERSION" modules_install
make -C "$SRC_DIR" O="$BUILD_DIR" LOCALVERSION="$LOCALVERSION" install

if command -v update-grub >/dev/null 2>&1; then
  update-grub
elif command -v grub-mkconfig >/dev/null 2>&1; then
  grub-mkconfig -o /boot/grub/grub.cfg
else
  echo "warning: neither update-grub nor grub-mkconfig found; update bootloader manually" >&2
fi

echo
echo "Install finished."
echo "Expected release after reboot: $release"
echo "Reboot, then verify:"
echo "  uname -r"
echo "  ls /sys/kernel/debug/lru_gen_pages"
echo "  ls /sys/kernel/debug/lru_gen_workload_markov"
echo "  cat /sys/kernel/debug/lru_gen_workload_markov"
