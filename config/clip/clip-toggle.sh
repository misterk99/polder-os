#!/bin/sh
# Super+V: toggle the resident clipboard-history popup (start the daemon if needed).
P=$(cat /tmp/osb-clipd.pid 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else setsid python3 /workspace/osbuilder/config/clip/clipd.py >/tmp/osb-clipd.log 2>&1 & fi
