"""Polder OS shared settings: one JSON file (~/.config/osb/settings.json) that every component reads.
Writers save atomically; osb-settingsd.py watches the file and applies changes live."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, json, copy, datetime
CFG = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
FILE = os.environ.get('OSB_SETTINGS') or os.path.expanduser('~/.config/osb/settings.json')
CACHE = os.path.expanduser('~/.cache/osb')
VERSION = 'Polder OS 0.30.1'
DEFAULTS = {
    'theme': 'light',            # light | dark | auto (licht 07:00-19:00)
    'reduced_motion': False,
    'accent': 'blauw',
    'color_source': 'accent',    # accent | wallpaper ("Kleuren uit achtergrond", Material You: seed colour from the wallpaper)
    'dynamic_seed': 0,           # which of the (max. 4) wallpaper seed colours, best first
    'wallpaper': 'polderheuvel',  # dark theme automatically uses polderheuvel-avond
    'notifications': True,       # pop-ups aan/uit
    'notif_history': True,       # bewaar in geschiedenis als pop-ups uit staan
    'popup_secs': 6,
    'feeds': [],                 # [{id, name, url, color}]
    'feed_refresh_min': 60,
    'kbd_layout': 'us', 'kbd_variant': '',
    'clock24': True, 'show_date': True,
    'night_light': False,
    'displays': {},             # confirmed Wayland output profiles, matched to monitor identity
    'lock_idle_min': 10,         # automatisch vergrendelen na N min inactiviteit (0 = nooit)
    'pinned': ['chromium.desktop', 'xfce4-terminal.desktop', 'files.desktop', 'polder-store.desktop'],   # plank (desktop ids, in order)
    'app_order': [],             # launcher grid order (desktop ids); rest alphabetically
    'clipboard_history': True,   # Super+V klembordgeschiedenis
    'welcome_done': False,       # Welkom bij Polder OS (eerste keer) afgerond
}
ACCENTS = {  # name: (light ACCENT, light CONTAINER, light ON_CONTAINER, dark ACCENT, dark CONTAINER, dark ON_CONTAINER, dark ON_ACCENT)
    'blauw':  ('#0b57d0', '#d3e3fd', '#041e49', '#a8c7fa', '#0842a0', '#d3e3fd', '#062e6f'),
    'groen':  ('#146c2e', '#c4eed0', '#072711', '#6dd58c', '#0f5223', '#c4eed0', '#0a3818'),
    'paars':  ('#6750a4', '#e9ddff', '#22005d', '#cfbcff', '#4f378b', '#e9ddff', '#381e72'),
    'roze':   ('#a0396c', '#ffd8e7', '#3e0022', '#ffb0cd', '#7f2153', '#ffd8e7', '#5e0b3a'),
    'oranje': ('#8f4c00', '#ffdcbe', '#2e1500', '#ffb871', '#6d3900', '#ffdcbe', '#4c2700'),
}
BASES = {
    'light': dict(SURFACE='#f8f9fc', SURFACE_VARIANT='#e8eef7', OUTLINE='#d3dbe5', ON_SURFACE='#1f1f1f', ON_SURFACE_VARIANT='#5f6368'),
    'dark':  dict(SURFACE='#1f2023', SURFACE_VARIANT='#2e3135', OUTLINE='#44474b', ON_SURFACE='#e3e3e3', ON_SURFACE_VARIANT='#c4c7c5'),
}
WALLPAPERS = ['polderheuvel', 'blauw', 'avond', 'groen', 'roze', 'grafiet']
LAYOUTS = [('us', '', _('English (US)')), ('us', 'intl', _('English (US, international)')), ('nl', '', _('Dutch')),
           ('be', '', _('Belgian')), ('de', '', _('German')), ('gb', '', _('English (UK)')), ('fr', '', _('French'))]

def wallpaper_thumb(name, w=176, h=99):
    """Cached thumbnail path for a wallpaper (shared by Instellingen and Welkom); None if the wallpaper is missing."""
    src = os.path.join(CFG, 'wallpapers', name + '.png'); tdir = os.path.join(CACHE, 'thumbs'); th = os.path.join(tdir, f'{name}-{w}.png')
    if not os.path.exists(src): return None
    if not os.path.exists(th) or os.path.getmtime(th) < os.path.getmtime(src):
        os.makedirs(tdir, exist_ok=True)
        from gi.repository import GdkPixbuf
        GdkPixbuf.Pixbuf.new_from_file_at_scale(src, w, h, False).savev(th, 'png', [], [])
    return th

def load():
    s = copy.deepcopy(DEFAULTS)
    try: s.update(json.load(open(FILE)))
    except Exception: pass
    return s

def save(s):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + '.tmp'; json.dump(s, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, FILE)

def update(**kw):
    s = load(); s.update(kw); save(s); return s

def effective_theme(s=None, now=None):
    s = s or load(); t = s.get('theme', 'light')
    if t == 'auto':
        h = (now or datetime.datetime.now()).hour
        return 'light' if 7 <= h < 19 else 'dark'
    return 'dark' if t == 'dark' else 'light'

def dyncolor_bin():
    import shutil
    for b in (os.environ.get('POLDER_DYNCOLOR'), shutil.which('polder-dynamic-color'),
              os.path.join(CFG, '..', 'shell', 'polder-shelf', 'target', 'release', 'polder-dynamic-color')):
        if b and os.path.isfile(b) and os.access(b, os.X_OK): return b
    return None

def wallpaper_path(name):
    return os.path.join(CFG, 'wallpapers', name + '.png')

def _dyn(name, *args):
    """Run polder-dynamic-color on wallpaper `name` (the day variant, so light/dark/auto keep one seed); cached by mtime."""
    import subprocess, hashlib
    wp, b = wallpaper_path(name), dyncolor_bin()
    if not b or not os.path.exists(wp): return None
    key = hashlib.sha1(f'{wp}:{os.path.getmtime(wp)}:{args}'.encode()).hexdigest()[:16]
    cf = os.path.join(CACHE, 'dyncolor', key)
    try: return open(cf).read()
    except OSError: pass
    try: out = subprocess.run([b, wp, *args], capture_output=True, text=True, timeout=20, check=True).stdout
    except Exception as e: print('polder-dynamic-color:', e); return None
    os.makedirs(os.path.dirname(cf), exist_ok=True); open(cf, 'w').write(out); return out

def dynamic_seeds(name):
    """Up to 4 seed colours (#rrggbb, best first) extracted from the wallpaper; [] if unavailable."""
    out = _dyn(name, '--seeds'); return out.split() if out else []

def dynamic_palette(theme, name, index=0):
    out = _dyn(name, '--theme', theme, '--index', str(int(index)))
    if not out: return None
    p = dict(l.split('=', 1) for l in out.splitlines() if '=' in l); p.pop('SEED', None)
    return p if 'ACCENT' in p else None

def palette_for(theme, accent, s=None):
    if s and s.get('color_source') == 'wallpaper':
        p = dynamic_palette(theme, s.get('wallpaper', 'polderheuvel'), s.get('dynamic_seed', 0))
        if p: return p   # else: fall back to the accent palette
    a = ACCENTS.get(accent, ACCENTS['blauw']); p = dict(BASES[theme])
    if theme == 'light': p.update(ACCENT=a[0], ACCENT_CONTAINER=a[1], ON_ACCENT_CONTAINER=a[2], ON_ACCENT='#ffffff')
    else: p.update(ACCENT=a[3], ACCENT_CONTAINER=a[4], ON_ACCENT_CONTAINER=a[5], ON_ACCENT=a[6])
    return p
