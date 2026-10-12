#!/usr/bin/env python3
"""Rev 34h: X11 desk keys. usage: desks.py desk|move prev|next  (wraps neither way, like ChromeOS)."""
import sys, subprocess, winlist as WL
what, d = sys.argv[1], sys.argv[2]
cur, n = WL.current_desk(), WL.desks(); t = cur + (1 if d == 'next' else -1)
if 0 <= t < n:
    if what == 'move': subprocess.run(['wmctrl', '-r', ':ACTIVE:', '-t', str(t)])
    subprocess.run(['wmctrl', '-s', str(t)])
