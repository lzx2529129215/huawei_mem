#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="${1:-$PWD/linux-hwe-6.17-6.17.0}"
BUILD_DIR="${2:-$PWD/linux-hwe-6.17-mglru-build}"
JOBS="${JOBS:-$(nproc)}"

missing=()
for tool in gawk make gcc flex bison openssl; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done

if ((${#missing[@]})); then
  printf 'Missing build dependencies: %s\n' "${missing[*]}" >&2
  printf 'Install them, for example:\n  sudo apt update && sudo apt install -y %s\n' "${missing[*]}" >&2
  exit 127
fi

mkdir -p "$BUILD_DIR"
cp "$(dirname "$0")/config-6.17.13-mglru" "$BUILD_DIR/.config"

make -C "$SRC_DIR" O="$BUILD_DIR" LOCALVERSION=-mglru olddefconfig
make -C "$SRC_DIR" O="$BUILD_DIR" LOCALVERSION=-mglru -j"$JOBS"

cat <<EOF

Build finished.

Install on the target machine with:
  cd "$SRC_DIR"
  sudo make O="$BUILD_DIR" LOCALVERSION=-mglru modules_install
  sudo make O="$BUILD_DIR" LOCALVERSION=-mglru install
  sudo update-grub

Then reboot and verify:
  uname -r
  ls /sys/kernel/debug/lru_gen_pages
EOF
