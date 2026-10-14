#!/bin/bash
# Revision 27: toggle via polder-shell IPC; fallback to the standalone launcher process (old mode)
# Rust launcher (polder-launcher, same PID file + SIGUSR1 protocol) when POLDER_LAUNCHER_IMPL=rust or ~/.config/osb/launcher-impl = rust.
C=$(cd "$(dirname "$0")/.." && pwd)
python3 "$C/osb/shellipc.py" launcher && exit 0
P=$(cat "${OSB_RUNDIR:-/tmp}/osb-launcher.pid" 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else
  impl=${POLDER_LAUNCHER_IMPL:-$(cat "$HOME/.config/osb/launcher-impl" 2>/dev/null || echo python)}
  if [ "$impl" = rust ] && command -v polder-launcher >/dev/null; then setsid polder-launcher --show >"${OSB_RUNDIR:-/tmp}/osb-launcher.log" 2>&1 &
  else setsid python3 "$C/launcher/launcher.py" --show >"${OSB_RUNDIR:-/tmp}/osb-launcher.log" 2>&1 & fi
fi
