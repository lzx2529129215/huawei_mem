#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
for p in "$ROOT/patches/0002-linux617-myself-kswapd-l01.patch" "$ROOT/patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch"; do test -s "$p"; done
test "$(sha256sum "$ROOT/patches/0002-linux617-myself-kswapd-l01.patch" | awk '{print $1}')" = ecc0e4f473ea4a657578568b2a57658ed37590c1a89e366ede7c2c81814d2711
test "$(sha256sum "$ROOT/patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch" | awk '{print $1}')" = 35bacaea2de3aae1552f24564d853b0ffb352f7d9929091da3d6026d2cd70b89
echo 'patch checksum gate: PASS'
