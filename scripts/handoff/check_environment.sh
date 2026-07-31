#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
if [[ "${1:-}" == --help ]]; then usage_header; echo "Usage: $0"; exit 0; fi
[[ $# -eq 0 ]] || die "unknown argument: $1"
fail=0
[[ "$(uname -m)" == x86_64 ]] || { warn "x86_64 recommended; found $(uname -m)"; fail=1; }
if [[ -r /etc/os-release ]]; then . /etc/os-release; case "${ID:-}" in ubuntu|debian) ;; *) warn "Ubuntu/Debian expected; found ${ID:-unknown}";; esac; else warn "/etc/os-release unavailable"; fi
for cmd in gcc make ld bc bison flex openssl python3 perl rsync curl git sha256sum tar xz; do
    if command -v "$cmd" >/dev/null 2>&1; then printf 'OK   %-16s %s\n' "$cmd" "$(command -v "$cmd")"; else printf 'MISS %-16s\n' "$cmd"; fail=1; fi
done
for header in openssl/ssl.h gelf.h; do
    if printf '#include <%s>\n' "$header" | gcc -x c - -c -o /tmp/l02-header-test.o >/dev/null 2>&1; then printf 'OK   header           %s\n' "$header"; else printf 'MISS header           %s\n' "$header"; fail=1; fi
done
rm -f -- /tmp/l02-header-test.o
avail_kib=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}'); avail_gib=$((avail_kib / 1024 / 1024)); printf 'INFO disk_available   %s GiB\n' "$avail_gib"
(( avail_gib >= 30 )) || { warn 'at least 30 GiB free disk is required'; fail=1; }
mem_mib=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo); printf 'INFO memory_available  %s MiB\n' "$mem_mib"; printf 'INFO suggested_jobs    %s\n' "$(cpu_jobs)"
if (( mem_mib < 4096 )); then warn 'less than 4 GiB available memory; use --jobs 1 or 2'; fi
if (( fail )); then
    cat >&2 <<'EOF'
Environment is incomplete. No packages were installed.
Ubuntu/Debian suggestion (run manually, after review):
  sudo apt-get install build-essential bc bison flex libssl-dev libelf-dev openssl python3 perl rsync curl git xz-utils
EOF
    exit 1
fi
echo 'Environment check: PASS'
