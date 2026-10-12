#!/bin/bash
# Rev 29: Super+A -> polder-shell IPC; fallback standalone assistant process
C=$(cd "$(dirname "$0")/.." && pwd)
python3 $C/osb/shellipc.py assistant && exit 0
setsid python3 $C/assistant/assistant.py --show >/tmp/osb-assistant.log 2>&1 &
