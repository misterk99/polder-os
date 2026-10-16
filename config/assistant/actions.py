"""Polder Assistent (Rev 29): the REAL system actions. Shared by the local intent engine and LLM tool calling.
Every action returns a short Dutch result string describing what actually happened (or why it couldn't)."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, sys, shutil, subprocess, time, glob, configparser
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify', 'weather', 'launcher'): sys.path.insert(0, os.path.join(C, d))
import osbsettings as S

def have(c): return shutil.which(c) is not None
def _bg(*a): subprocess.Popen(a, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
def _out(*a):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=5).stdout
    except Exception: return ''

def set_theme(mode):
    mode = {'donker': 'dark', 'licht': 'light'}.get(mode, mode)
    if mode == 'toggle': mode = 'light' if S.effective_theme() == 'dark' else 'dark'
    if mode not in ('dark', 'light', 'auto'): return _('Unknown theme: {mode}').format(mode=mode)
    S.update(theme=mode); return {'dark': _('Dark theme is on.'), 'light': _('Light theme is on.'), 'auto': _('Theme is set to automatic.')}[mode]

def _apps():
    dirs = [os.path.expanduser('~/.local/share/applications'), '/usr/local/share/applications', '/usr/share/applications', os.path.join(C, 'launcher')]
    seen = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, '*.desktop')):
            cp = configparser.RawConfigParser(strict=False)
            try: cp.read(f, encoding='utf-8'); e = cp['Desktop Entry']
            except Exception: continue
            if e.get('NoDisplay', 'false') == 'true' or e.get('Type', 'Application') != 'Application' or 'Exec' not in e: continue
            seen.setdefault(os.path.basename(f), (e.get('Name[nl]') or e.get('Name', ''), e.get('GenericName[nl]') or e.get('GenericName', ''), e.get('Keywords', ''), f))
    return list(seen.values())

def find_app(q):
    from launcher import score
    best = max(((score(q, n, g, k.replace(';', ' ')), n, f) for n, g, k, f in _apps()), default=(0, '', ''))
    return best if best[0] >= 60 else None

def open_app(name):
    alias = {'terminal': 'terminal', 'browser': 'chromium', 'webbrowser': 'chromium', 'bestanden': 'bestanden', 'instellingen': 'instellingen', 'winkel': 'store', 'store': 'store'}
    hit = find_app(alias.get(name.lower(), name))
    if not hit: return _('No app found for "{name}".').format(name=name)
    _bg('gtk-launch', os.path.basename(hit[2])[:-8]) if have('gtk-launch') else _bg('gio', 'launch', hit[2])
    return _('Opening {p0}.').format(p0=hit[1])

def open_calendar():
    _bg(sys.executable, os.path.join(C, 'calendar', 'cal.py')); return _('Calendar opened.')

def set_volume(level):
    level = max(0, min(150, int(level)))
    if have('pactl'): r = subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{level}%'], capture_output=True, timeout=5)
    elif have('amixer'): r = subprocess.run(['amixer', 'set', 'Master', f'{level}%'], capture_output=True, timeout=5)
    else: return _('No audio system (pactl/amixer) found.')
    return _('Volume at {level}%.').format(level=level) if r.returncode == 0 else _('Setting volume failed: ') + r.stderr.decode().strip()[:120]

def set_brightness(level):
    level = max(5, min(100, int(level)))
    if os.path.isdir('/sys/class/backlight') and os.listdir('/sys/class/backlight') and have('brightnessctl'):
        subprocess.run(['brightnessctl', 'set', f'{level}%'], capture_output=True, timeout=5); return _('Brightness at {level}%.').format(level=level)
    out = next((l.split()[0] for l in _out('xrandr', '-q').splitlines() if ' connected' in l), None)
    if not out: return _('No display found for brightness.')
    g = ['--gamma', '1:0.82:0.64'] if S.load().get('night_light') else []
    r = subprocess.run(['xrandr', '--output', out, '--brightness', f'{max(level, 20) / 100:.2f}', *g], capture_output=True, timeout=5)
    return _('Brightness at {p0}% (software, via xrandr).').format(p0=max(level, 20)) if r.returncode == 0 else _('Setting brightness failed.')

def set_wifi(on):
    if not have('nmcli'): return _('Wi‑Fi not available: NetworkManager (nmcli) is missing.')
    r = subprocess.run(['nmcli', 'radio', 'wifi', 'on' if on else 'off'], capture_output=True, text=True, timeout=8)
    return (_('Wi‑Fi is {p0}.').format(p0=_('on') if on else _('off'))) if r.returncode == 0 else _('Switching Wi‑Fi failed: ') + (r.stderr.strip() or r.stdout.strip())[:120]

def set_bluetooth(on):
    if not have('bluetoothctl'): return _('Bluetooth not available: bluetoothctl is missing.')
    r = subprocess.run(['bluetoothctl', 'power', 'on' if on else 'off'], capture_output=True, text=True, timeout=8)
    ok = r.returncode == 0 and 'succeeded' in r.stdout
    return _('Bluetooth is {p0}.').format(p0=_('on') if on else _('off')) if ok else _('Switching Bluetooth failed: ') + ((r.stdout + r.stderr).strip().splitlines() or [_('no adapter')])[-1][:120]

def set_dnd(on):
    import osbnotify as N
    from gi.repository import GLib
    try: N.call('SetDnd', GLib.Variant('(b)', (bool(on),))); return _('Do not disturb is {p0}.').format(p0=_('on') if on else _('off'))
    except Exception as e: return _('Switching do not disturb failed: {e}').format(e=e)

def lock_screen():
    _bg('sh', '-c', 'sleep 0.6; exec "$0"', os.path.join(C, 'lock', 'lock-now.sh')); return _('Locking the screen.')

def screenshot():
    d = os.path.join(os.environ.get('OSB_FILES_HOME', '/tmp/osb-files/Mijn bestanden'), 'Afbeeldingen', _('Screenshots')); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, time.strftime(_('Screenshot %Y-%m-%d %H.%M.%S.png')))
    time.sleep(0.5)   # panel hides first
    r = subprocess.run(['import', '-window', 'root', p], capture_output=True, timeout=15) if have('import') else None
    if not r or r.returncode != 0: return _('Screenshot failed (ImageMagick import missing?).')
    _bg('notify-send', '-a', _('Polder Assistant'), _('Screenshot saved'), os.path.basename(p)); return _('Screenshot saved: {p}').format(p=p)

def weather():
    import weather as W
    w = W.load()
    if not w: return _('No current weather data (Polder Weather could not fetch anything in the last 2 hours).')
    c = w['data'].get('current', {}); desc, _x = W.describe(c.get('weather_code', -1), c.get('is_day', 1))
    d = w['data'].get('daily', {}); extra = ''
    try: extra = _(' Today {p0}–{p1}°, chance of rain {p2}%.').format(p0=round(d['temperature_2m_min'][0]), p1=round(d['temperature_2m_max'][0]), p2=d['precipitation_probability_max'][0])
    except Exception: pass
    return _('{p0}: {desc}, {p1}° (feels like {p2}°), wind {p3} km/h.{extra}').format(p0=w['place'].get('name', '?'), desc=desc, p1=round(c.get('temperature_2m', 0)), p2=round(c.get('apparent_temperature', 0)), p3=round(c.get('wind_speed_10m', 0)), extra=extra)

def search_files(query):
    from launcher import FileIndex
    fi = FileIndex()
    for _x in range(50):
        if fi.t: break
        time.sleep(0.1)
    hits = fi.search(query, 8)
    if not hits: return _('No files found for "{query}".').format(query=query)
    return _('Found:\n') + '\n'.join(f"• {h[2]}{'/' if h[4] else ''} — {os.path.dirname(h[3])}" for h in hits)

def open_path(path):
    if not os.path.exists(path): return _('File does not exist.')
    _bg('xdg-open', path); return _('{p0} opened.').format(p0=os.path.basename(path))

# name: (function, description, params {name: (type, desc, enum?)}, required, destructive)
TOOLS = {
    'set_theme': (set_theme, 'Switch the Polder OS theme', {'mode': ('string', 'dark, light, auto or toggle', ['dark', 'light', 'auto', 'toggle'])}, ['mode'], False),
    'open_app': (open_app, 'Open an installed application by (partial) name', {'name': ('string', 'app name, e.g. Firefox, Terminal, Bestanden', None)}, ['name'], False),
    'open_calendar': (open_calendar, 'Open the calendar popup', {}, [], False),
    'set_volume': (set_volume, 'Set output volume in percent', {'level': ('integer', '0-100', None)}, ['level'], False),
    'set_brightness': (set_brightness, 'Set screen brightness in percent', {'level': ('integer', '5-100', None)}, ['level'], False),
    'set_wifi': (set_wifi, 'Turn wifi on or off', {'on': ('boolean', 'true = on', None)}, ['on'], True),
    'set_bluetooth': (set_bluetooth, 'Turn bluetooth on or off', {'on': ('boolean', 'true = on', None)}, ['on'], True),
    'set_dnd': (set_dnd, 'Turn do-not-disturb on or off', {'on': ('boolean', 'true = on', None)}, ['on'], False),
    'lock_screen': (lock_screen, 'Lock the screen', {}, [], True),
    'screenshot': (screenshot, 'Take a screenshot of the whole screen', {}, [], False),
    'get_weather': (weather, 'Get current weather and today forecast for the configured location', {}, [], False),
    'search_files': (search_files, "Search the user's files by name", {'query': ('string', 'file name words', None)}, ['query'], False),
    'open_path': (open_path, 'Open a file or folder with its default app', {'path': ('string', 'absolute path', None)}, ['path'], False),
}
CONFIRM_TEXT = {'set_wifi': _('Turn Wi‑Fi {}?'), 'set_bluetooth': _('Turn Bluetooth {}?'), 'lock_screen': _('Lock the screen now?')}

def needs_confirm(name, args):
    t = TOOLS.get(name)
    if not t or not t[4]: return None
    if name in ('set_wifi', 'set_bluetooth'):
        if args.get('on'): return None        # only turning OFF is destructive (can cut the connection)
        return CONFIRM_TEXT[name].format(_('off'))
    return CONFIRM_TEXT[name]

def run(name, args):
    t = TOOLS.get(name)
    if not t: return _('Unknown action {name}').format(name=name)
    try: return t[0](**{k: v for k, v in (args or {}).items() if k in t[2]})
    except Exception as e: return _('Action {name} failed: {p0}: {e}').format(name=name, p0=type(e).__name__, e=e)
