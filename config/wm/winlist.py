"""Window list helpers (wmctrl/xdotool/ImageMagick) for overview + alt-tab."""
import subprocess, os, hashlib
SKIP = {'tint2', 'polder-shell.py', 'qs.py', 'osb-notifyd.py', 'rofi'}
APPNAMES = {'chromium': 'Chromium', 'thunar': 'Bestanden', 'xfce4-terminal': 'Terminal',
            'xfce4-settings-manager': 'Instellingen'}
ICONS = {'chromium': 'chromium-browser', 'thunar': 'system-file-manager', 'xfce4-terminal': 'utilities-terminal',
         'xfce4-settings-manager': 'preferences-system'}

def sh(*a):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=5).stdout
    except subprocess.TimeoutExpired: return ''

def stacking():
    o = sh('xprop', '-root', '_NET_CLIENT_LIST_STACKING')
    try: return [int(x, 16) for x in o.split('#', 1)[1].replace(',', ' ').split()]
    except Exception: return []

def current_desk():
    for l in sh('wmctrl', '-d').splitlines():
        if ' * ' in l: return int(l.split()[0])
    return 0

def desks(): return len(sh('wmctrl', '-d').splitlines())

def windows(desk=None, all_desks=False):
    """MRU-ordered (topmost first) normal windows."""
    desk = current_desk() if desk is None else desk
    wins = {}
    for l in sh('wmctrl', '-l').splitlines():
        p = l.split(None, 3)
        if len(p) < 3: continue
        wid, d = int(p[0], 16), int(p[1])
        if d < 0 or (not all_desks and d != desk): continue
        wc = sh('xprop', '-id', hex(wid), 'WM_CLASS').split('=')[-1].replace('"', '').split(',')
        inst = wc[0].strip().lower().split(' ')[0] if wc else ''
        if inst in SKIP or (len(wc) > 1 and wc[1].strip().lower() in SKIP): continue
        title = sh('xdotool', 'getwindowname', str(wid)).strip()
        for suf in (' - Chromium', ' - Thunar', ' - Google Chrome'): title = title.replace(suf, '')
        if inst == 'xfce4-terminal': title = 'Terminal'
        if inst == 'xfce4-settings-manager': title = 'Instellingen'
        wins[wid] = dict(id=wid, desk=d, inst=inst, title=title, app=APPNAMES.get(inst, inst.capitalize()),
                         icon=ICONS.get(inst, 'application-x-executable'),
                         hidden='_NET_WM_STATE_HIDDEN' in sh('xprop', '-id', hex(wid), '_NET_WM_STATE'))
    order = [w for w in reversed(stacking()) if w in wins]
    return [wins[w] for w in order]

CACHE = '/tmp/osb-wm/cache'

def capture_active():
    """Called periodically by keyd: snapshot the focused window (on top, so not obscured)."""
    os.makedirs(CACHE, exist_ok=True)
    try: wid = int(sh('xdotool', 'getactivewindow').strip())
    except ValueError: return
    if '_NET_WM_STATE_HIDDEN' in sh('xprop', '-id', hex(wid), '_NET_WM_STATE'): return
    tmp = f'{CACHE}/{wid:x}.tmp.png'
    try:
        if subprocess.run(['import', '-silent', '-window', hex(wid), tmp], capture_output=True, timeout=10).returncode == 0:
            os.replace(tmp, f'{CACHE}/{wid:x}.png')
    except subprocess.TimeoutExpired: pass

def thumb(w, maxw, maxh):
    """Scaled thumbnail from the cached snapshot (taken when the window was last focused; no compositor,
    so obscured windows can't be read live); falls back to a live grab. Returns png path or None."""
    os.makedirs('/tmp/osb-wm', exist_ok=True); out = f"/tmp/osb-wm/thumb-{w['id']:x}-{maxw}.png"
    src = f"{CACHE}/{w['id']:x}.png"
    try:
        if os.path.exists(src):
            r = subprocess.run(['convert', src, '-resize', f'{maxw}x{maxh}', out], capture_output=True, timeout=10)
        elif not w['hidden']:
            r = subprocess.run(['import', '-silent', '-window', hex(w['id']), '-resize', f'{maxw}x{maxh}', out], capture_output=True, timeout=10)
        else: return None
    except subprocess.TimeoutExpired: return None
    return out if r.returncode == 0 and os.path.exists(out) else None

def activate(wid):
    subprocess.run(['wmctrl', '-i', '-a', hex(wid)])

def close(wid):
    subprocess.run(['wmctrl', '-i', '-c', hex(wid)])
