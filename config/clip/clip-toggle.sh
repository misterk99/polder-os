#!/bin/bash
# Revision 27: toggle via polder-shell IPC; fallback to the standalone clipd process (old mode)
C=$(cd "$(dirname "$0")/.." && pwd)
python3 "$C/osb/shellipc.py" clip && exit 0
P=$(cat "${OSB_RUNDIR:-/tmp}/osb-clipd.pid" 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else setsid python3 "$C/clip/clipd.py" >"${OSB_RUNDIR:-/tmp}/osb-clipd.log" 2>&1 & fi
