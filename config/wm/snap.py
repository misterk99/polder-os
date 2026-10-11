#!/usr/bin/env python3
"""Window snapping helpers (ChromeOS style). CLI: snap.py left|right|max|min [wid]"""
import subprocess, sys
SW, SH, SHELF = 1366, 768, 52
WA_H = SH - SHELF  # work area height above the shelf

def sh(*a):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=5).stdout
    except subprocess.TimeoutExpired: return ''

def active():
    try: return int(sh('xdotool', 'getactivewindow').strip())
    except ValueError: return None

def is_max(w): return '_NET_WM_STATE_MAXIMIZED_HORZ' in sh('xprop', '-id', hex(w), '_NET_WM_STATE')

def geom(side):
    return {'left': (0, 0, SW // 2, WA_H), 'right': (SW // 2, 0, SW - SW // 2, WA_H)}[side]

def snap(side, w=None):
    w = w or active()
    if not w: return
    h = hex(w)
    if side == 'min': sh('xdotool', 'windowminimize', str(w)); return
    if side == 'max':
        sh('wmctrl', '-i', '-r', h, '-b', ('remove' if is_max(w) else 'add') + ',maximized_vert,maximized_horz'); return
    sh('wmctrl', '-i', '-r', h, '-b', 'remove,maximized_vert,maximized_horz')
    x, y, ww, hh = geom(side)
    # wmctrl -e sets the frame-inclusive size on xfwm4 closely enough; subtract title/border via _NET_FRAME_EXTENTS
    ext = sh('xprop', '-id', h, '_NET_FRAME_EXTENTS').split('=')[-1].replace(',', ' ').split()
    l, r, t, b = (int(v) for v in ext) if len(ext) == 4 else (0, 0, 0, 0)
    sh('wmctrl', '-i', '-r', h, '-e', f'0,{x},{y},{ww - l - r},{hh - t - b}')
    sh('wmctrl', '-i', '-a', h)

if __name__ == '__main__':
    snap(sys.argv[1], int(sys.argv[2], 0) if len(sys.argv) > 2 else None)
