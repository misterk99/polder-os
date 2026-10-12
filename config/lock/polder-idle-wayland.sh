#!/bin/bash
# Rev 34b: idle lock on polder-comp via ext-idle-notify-v1 (swayidle). Timeout = settings.json 'lock_idle_min'
# (Instellingen > Privacy; 0 = never), default 10 min; also locks before suspend (logind).
C=$(cd "$(dirname "$0")/.." && pwd)
MIN=$(python3 -c "import json,os;f=os.path.expanduser('~/.config/osb/settings.json');print(int(json.load(open(f)).get('lock_idle_min',10)) if os.path.exists(f) else 10)" 2>/dev/null || echo 10)
SEC=${POLDER_IDLE_SECS:-$((MIN*60))}
[ "$SEC" -gt 0 ] || exit 0
L="$C/lock/lock-now.sh"   # same entry point as Super+L / QS (handles the prototype test account)
exec swayidle -w timeout "$SEC" "$L -f" before-sleep "$L -f"
