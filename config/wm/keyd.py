#!/usr/bin/env python3
"""Global hotkeys for the prototype (python-xlib passive grabs on the root window):
  Super_L (tap) -> Polder OS launcher (ChromeOS 'Search' key); F3 (ChromeOS 'Overview' key position) -> overview.py overview
  Alt+Tab / Alt+Shift+Tab -> overview.py alttab (it takes over the keyboard until Alt is released)."""
import os, subprocess, sys
from Xlib import X, XK, display
HERE = os.path.dirname(os.path.abspath(__file__))
d = display.Display(); root = d.screen().root
def kc(name): return d.keysym_to_keycode(XK.string_to_keysym(name))
MODS_IGNORE = [0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask]
sys.path.insert(0, HERE); import shortcut_table as ST   # single source: binds AND the sneltoetsen overview
MODMASK = {'Alt': X.Mod1Mask, 'Shift': X.ShiftMask, 'Ctrl': X.ControlMask, 'Super': X.Mod4Mask}
RELEVANT = X.Mod1Mask | X.ShiftMask | X.ControlMask | X.Mod4Mask
binds = {}
for sc in ST.KEYD:
    m = 0
    for n in sc['mods']: m |= MODMASK[n]
    binds[(kc(sc['sym']), m)] = sc['action']
for (code, mod) in binds:
    for extra in MODS_IGNORE: root.grab_key(code, mod | extra, True, X.GrabModeAsync, X.GrabModeAsync)
root.change_attributes(event_mask=X.KeyPressMask | X.KeyReleaseMask)
import threading, time
sys.path.insert(0, HERE); import winlist as WL
def snapper():
    while True:
        if not any(os.path.exists(f'/tmp/osb-wm-{m}.pid') for m in ('overview', 'alttab')):
            try: WL.capture_active()
            except Exception as ex: print('snap', ex)
        time.sleep(1.5)
threading.Thread(target=snapper, daemon=True).start()
DISPATCH = None   # Revision 27: set by polder-shell -> launcher/clip toggles go straight to the shell's main loop
def launch(mode):
    if DISPATCH and mode in ('launcher', 'clip', 'assistant'): DISPATCH(mode); return
    if mode == 'shortcuts':   # Ctrl+Alt+/ -> sneltoetsen overview (toggle)
        subprocess.Popen([sys.executable, os.path.join(HERE, '..', 'shortcuts', 'sneltoetsen.py')], start_new_session=True); return
    if mode == 'capture':   # Print / Ctrl+Shift+F5 -> capture bar (or stop a running recording)
        subprocess.Popen([sys.executable, os.path.join(HERE, '..', 'capture', 'capture.py')], start_new_session=True); return
    if mode == 'clip':   # Super+V -> clipboard history
        subprocess.Popen([os.path.join(HERE, '..', 'clip', 'clip-toggle.sh')], start_new_session=True); return
    if mode == 'assistant':   # Super+A -> Polder Assistent (Rev 29)
        subprocess.Popen([os.path.join(HERE, '..', 'assistant', 'assistant-toggle.sh')], start_new_session=True); return
    if mode == 'lock':   # Super+L -> Polder OS lock screen
        subprocess.Popen([os.path.join(HERE, '..', 'lock', 'lock-now.sh')], start_new_session=True); return
    if mode == 'launcher':
        subprocess.Popen([os.path.join(HERE, '..', 'launcher', 'launcher-toggle.sh')]); return
    if mode.startswith('snap '):
        side = mode.split()[1]
        subprocess.Popen([sys.executable, os.path.join(HERE, 'snap.py'), side])
        if side in ('left', 'right'):  # ChromeOS split view: pick a window for the other half
            subprocess.Popen(['sh', '-c', f'sleep 0.4; exec {sys.executable} {os.path.join(HERE, "overview.py")} split-{side}'])
        return
    subprocess.Popen([sys.executable, os.path.join(HERE, 'overview.py'), mode])

def on_titlebar(px, py):
    """True if (px,py) lies in the titlebar band of the window under the pointer:
    between frame top (client_y - top extent) and client top, within the frame's x range."""
    def sh(*a):
        try: return subprocess.run(a, capture_output=True, text=True, timeout=3).stdout
        except subprocess.TimeoutExpired: return ''
    loc = dict(l.split('=', 1) for l in sh('xdotool', 'getmouselocation', '--shell').split() if '=' in l)
    wid = loc.get('WINDOW')
    if not wid: return False
    xi = sh('xwininfo', '-id', wid); g = {}
    for line in xi.splitlines():
        k, _, v = line.strip().partition(':')
        if k == 'Absolute upper-left X': g['X'] = v.strip()
        elif k == 'Absolute upper-left Y': g['Y'] = v.strip()
        elif k == 'Width': g['WIDTH'] = v.strip()
    ext = sh('xprop', '-id', wid, '_NET_FRAME_EXTENTS').split('=')[-1].replace(',', ' ').split()
    if len(ext) != 4 or 'Y' not in g: return False
    l, rr, t, b = (int(v) for v in ext); x, y, w = int(g['X']), int(g['Y']), int(g['WIDTH'])
    return y - t <= py < y and x - l <= px < x + w + rr

def drag_watcher():
    """Shows a snap preview while a window is dragged (button 1 held after pressing on a titlebar) near an edge."""
    from Xlib import display as _d
    dd = _d.Display(); r = dd.screen().root; pv = None; cur = None; started_drag = False; was_held = False
    while True:
        q = r.query_pointer(); held = bool(q.mask & X.Button1Mask)
        if held and not was_held:
            started_drag = on_titlebar(q.root_x, q.root_y)  # decided once, at press time
        was_held = held
        if not held: started_drag = False
        side = None
        if held and started_drag:
            if q.root_x <= 3: side = 'left'
            elif q.root_x >= 1362: side = 'right'
            elif q.root_y <= 3: side = 'max'
        if side != cur:
            if pv: pv.terminate(); pv = None
            if cur and not held:  # released on an edge: snap the dragged (active) window ourselves
                time.sleep(0.15)  # xfwm4's tile_on_move may do it too; this makes it deterministic
                subprocess.Popen([sys.executable, os.path.join(HERE, 'snap.py'), cur])
            if side: pv = subprocess.Popen([sys.executable, os.path.join(HERE, 'preview.py'), side])
            cur = side
        time.sleep(0.06)
threading.Thread(target=drag_watcher, daemon=True).start()
super_down = False
while True:
    e = d.next_event()
    if e.type not in (X.KeyPress, X.KeyRelease): continue
    mod = e.state & (X.Mod1Mask | X.ShiftMask | X.ControlMask | X.Mod4Mask)
    if e.type == X.KeyPress:
        if e.detail == kc('Super_L'): super_down = True; continue
        super_down = False
        m = binds.get((e.detail, mod & RELEVANT))
        if m == 'launcher': m = None   # Super is a tap: handled on release
        if m: launch(m)
    elif e.type == X.KeyRelease and e.detail == kc('Super_L') and super_down:
        super_down = False; launch('launcher')
