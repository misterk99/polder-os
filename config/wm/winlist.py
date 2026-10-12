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


# ---------------- Rev 34g: polder-comp (Wayland) backend ----------------
# The compositor owns desks and windows; we talk to it through its command FIFO ($POLDER_COMP_CMD):
# 'dump' writes $XDG_RUNTIME_DIR/polder-state.json + full-size thumbnails (polder-thumb-ID.raw, read back by the
# renderer, so hidden windows and other desks have real previews too); 'focus ID', 'close ID', 'desk N', 'newdesk', 'movedesk ID N'.
import json, time
WLMODE = bool(os.environ.get('POLDER_COMP') and os.environ.get('WAYLAND_DISPLAY'))
RUN = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
WL_APPS = {'foot': ('Terminal', 'utilities-terminal'), 'org.gnome.Nautilus': ('Bestanden', 'system-file-manager'),
           'Thunar': ('Bestanden', 'system-file-manager'), 'thunar': ('Bestanden', 'system-file-manager'),
           'chromium': ('Chromium', 'chromium-browser'), 'Chromium': ('Chromium', 'chromium-browser')}
WL_SKIP = {'polder-shelf'}
_state = None

def wl_cmd(line):
    with open(os.environ.get('POLDER_COMP_CMD', os.path.join(RUN, 'polder-comp.cmd')), 'w') as f: f.write(line + '\n')

def wl_state(refresh=False):
    global _state
    if _state is not None and not refresh: return _state
    f = os.path.join(RUN, 'polder-state.json'); m0 = os.path.getmtime(f) if os.path.exists(f) else 0
    wl_cmd('dump')
    for _ in range(40):
        if os.path.exists(f) and os.path.getmtime(f) != m0: break
        time.sleep(0.025)
    try: _state = json.load(open(f))
    except Exception: _state = {'desk': 0, 'desks': 1, 'windows': []}
    return _state

def _wl_win(w):
    app, icon = WL_APPS.get(w['app_id'], (w['app_id'].split('.')[-1].capitalize() or 'Venster', w['app_id'].lower() or 'application-x-executable'))
    return dict(id=w['id'], desk=w['desk'], inst=w['app_id'], title=w['title'], app=app, icon=icon, hidden=w['min'], geom=(w['x'], w['y'], w['w'], w['h']))

def _wl_windows(desk=None, all_desks=False):
    st = wl_state(); desk = st['desk'] if desk is None else desk
    return [_wl_win(w) for w in st['windows'] if w['app_id'] not in WL_SKIP and (all_desks or w['desk'] == desk)]

def _wl_thumb(w, maxw, maxh):
    src = os.path.join(RUN, f"polder-thumb-{w['id']}.raw"); out = os.path.join(RUN, f"polder-thumb-{w['id']}-{maxw}.png")
    try:
        import gi; gi.require_version('GdkPixbuf', '2.0'); from gi.repository import GdkPixbuf, GLib
        data = open(src, 'rb').read(); hdr, px = data.split(b'\n', 1); W, H, fmt = hdr.split(); W, H = int(W), int(H)
        if fmt == b'BGRA':   # swap to RGBA
            b = bytearray(px); b[0::4], b[2::4] = px[2::4], px[0::4]; px = bytes(b)
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(px), GdkPixbuf.Colorspace.RGB, True, 8, W, H, W * 4)
        sc = min(maxw / W, maxh / H, 1.0); pb.scale_simple(max(1, int(W * sc)), max(1, int(H * sc)), GdkPixbuf.InterpType.BILINEAR).savev(out, 'png', [], [])
        return out
    except Exception as e:
        print('thumb', w['id'], e, flush=True); return None

if WLMODE:
    current_desk = lambda: wl_state()['desk']
    desks = lambda: wl_state()['desks']
    windows = _wl_windows
    thumb = _wl_thumb
    activate = lambda wid: wl_cmd(f'focus {wid}')
    close = lambda wid: wl_cmd(f'close {wid}')
    switch_desk = lambda d: wl_cmd(f'desk {d}')
    move_to_desk = lambda wid, d: wl_cmd(f'movedesk {wid} {d}')
    new_desk = lambda: wl_cmd('newdesk')
    def desk_windows(d): return _wl_windows(desk=d)
