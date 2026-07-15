#!/usr/bin/env bash
set -u
out="${1:-/tmp/display-geometry.txt}"
pid="$(pgrep -u "$(id -u)" -n gnome-shell)"
while IFS= read -r -d '' item; do
    case "$item" in
        DISPLAY=*|XAUTHORITY=*|XDG_RUNTIME_DIR=*|DBUS_SESSION_BUS_ADDRESS=*) export "$item" ;;
    esac
done < "/proc/$pid/environ"
{
    echo "DISPLAY=$DISPLAY"
    xdotool getdisplaygeometry
    command -v xdpyinfo >/dev/null && xdpyinfo | grep -E 'dimensions|resolution' || true
} > "$out" 2>&1
