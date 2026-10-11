#!/bin/sh
# Toggle the resident Polder OS launcher (start it if it isn't running).
P=$(cat /tmp/osb-launcher.pid 2>/dev/null)
if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then kill -USR1 "$P"
else setsid python3 /workspace/osbuilder/config/launcher/launcher.py --show >/tmp/osb-launcher.log 2>&1 & fi
