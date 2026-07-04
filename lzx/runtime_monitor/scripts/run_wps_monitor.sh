#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 monitor.py \
  --config config.yaml \
  --target-app WPS \
  --sample-interval 1 \
  --output-dir ./output \
  --path-mode hash \
  "$@"

