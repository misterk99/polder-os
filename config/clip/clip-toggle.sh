#!/bin/bash
# Revision 27: toggle via polder-shell IPC; fallback to the standalone clipd process (old mode)
# Rust clipboard history (polder-clipd, same PID file + SIGUSR1/SIGUSR2) when POLDER_CLIP_IMPL=rust or ~/.config/osb/clip-impl = rust.
C=$(cd "$(dirname "$0")/.." && pwd)
python3 "$C/osb/shellipc.py" clip && exit 0
P=$(cat "${OSB_RUNDIR:-/tmp}/osb-clipd.pid" 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else
  impl=${POLDER_CLIP_IMPL:-$(cat "$HOME/.config/osb/clip-impl" 2>/dev/null || echo python)}
  if [ "$impl" = rust ] && [ -n "${WAYLAND_DISPLAY:-}" ] && command -v polder-clipd >/dev/null; then setsid polder-clipd >"${OSB_RUNDIR:-/tmp}/osb-clipd.log" 2>&1 &
  else setsid python3 "$C/clip/clipd.py" >"${OSB_RUNDIR:-/tmp}/osb-clipd.log" 2>&1 & fi
fi
