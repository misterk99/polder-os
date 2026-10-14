#!/bin/bash
# Revision 27: toggle via polder-shell IPC; fallback to the standalone launcher process (old mode)
C=$(cd "$(dirname "$0")/.." && pwd)
python3 "$C/osb/shellipc.py" launcher && exit 0
P=$(cat "${OSB_RUNDIR:-/tmp}/osb-launcher.pid" 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else setsid python3 "$C/launcher/launcher.py" --show >"${OSB_RUNDIR:-/tmp}/osb-launcher.log" 2>&1 & fi
