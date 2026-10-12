#!/bin/bash
# Rev 32b: real key-binding test for polder-comp via wtype (zwp_virtual_keyboard).
# Note: `wtype -M logo` only sets modifier state; a Super *tap* needs `wtype -k Super_L`.
set -e
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
n0=$(pgrep -c -x foot || true)
wtype -M logo -k Return -m logo; sleep 2; wtype -M logo -k Return -m logo; sleep 2
n1=$(pgrep -c -x foot); echo "Super+Return: foot $n0 -> $n1"
wtype -M alt -k Tab -m alt; sleep 1; echo "Alt+Tab sent"
wtype -M logo -k q -m logo; sleep 2
n2=$(pgrep -c -x foot); echo "Super+Q: foot $n1 -> $n2"
wtype -k Super_L; sleep 6
pgrep -f launcher.py >/dev/null && echo "Super tap: launcher running" || echo "Super tap: launcher NOT running"
