#!/usr/bin/env python3
"""Polder OS launcher (ChromeOS-style, GTK3). Resident process: SIGUSR1 toggles it (launcher-toggle.sh), so
opening is fast. Empty query = app grid; typing = grouped results: Apps, Instellingen, Bestanden, Rekenmachine,
'Zoeken op het web'. No fake results: everything comes from .desktop files, the Settings sections, the real
file tree under the Files home, Python's arithmetic, or a real web search."""
import os, re, sys, ast, operator, signal, threading, time, subprocess, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0'); gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, Gdk, GLib, Gio, Pango, GdkX11
import osbnotify as N
import osbsettings as S, popmenu
DND = [Gtk.TargetEntry.new('osb-app', Gtk.TargetFlags.SAME_APP, 0)]
PID = '/tmp/osb-launcher.pid'
W, H, MARGIN, SHELF = 640, 500, 10, 62
FILES_HOME = os.environ.get('OSB_FILES_HOME', '/tmp/osb-files/Mijn bestanden')   # what the Files app shows as home
SETTINGS = os.path.join(C, 'settings', 'instellingen.py')
SECTIONS = [  # (title, subtitle, section, keywords)
    ('Welkom bij Polder OS', 'Rondleiding en eerste instellingen', '__welkom', 'welkom welcome rondleiding tour eerste start introductie'),
    ('Sneltoetsen bekijken', 'Toetsenbord · Ctrl+Alt+/', '__sneltoetsen', 'sneltoetsen sneltoets shortcuts toetscombinaties toetsen keyboard'),
    ('Thema: licht, donker of automatisch', 'Personalisatie', 'personalisatie', 'thema donker licht dark light modus automatisch nacht'),
    ('Achtergrond', 'Personalisatie', 'personalisatie', 'achtergrond wallpaper bureaublad polderheuvel'),
    ('Accentkleur', 'Personalisatie', 'personalisatie', 'accent kleur kleuren'),
    ('Meldingen', 'Meldingen', 'meldingen', 'meldingen notificaties pop-ups popup'),
    ('Niet storen', 'Meldingen', 'meldingen', 'niet storen dnd stil'),
    ('Agenda-abonnementen (iCal)', 'Agenda', 'agenda', 'agenda kalender ical ics webcal feestdagen'),
    ('Toetsenbordindeling', 'Toetsenbord en taal', 'toetsenbord', 'toetsenbord keyboard indeling layout taal qwerty'),
    ('Datum en tijd', 'Datum en tijd', 'datum', 'datum tijd klok 24-uurs uur'),
    ('Over Polder OS', 'Versie, geheugen, systeem', 'over', 'over versie polder os systeem geheugen info'),
]
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}

def calc(q):
    """Safe arithmetic: digits, + - * x / ^ % ( ), comma decimals. Returns formatted result or None."""
    s = q.strip().replace(',', '.').replace('×', '*').replace('x', '*').replace('÷', '/').replace('^', '**')
    if not s or not any(ch.isdigit() for ch in s) or not any(ch in '+-*/%' for ch in s) or set(s) - set('0123456789.+-*/%() '): return None
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100: raise ValueError
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS: return OPS[type(n.op)](ev(n.operand))
        raise ValueError
    try: r = ev(ast.parse(s, mode='eval'))
    except Exception: return None
    if isinstance(r, float):
        if r != r or abs(r) == float('inf'): return None
        r = round(r, 10); r = int(r) if r == int(r) else r
    return f'{r:,}'.replace(',', ' ') if isinstance(r, int) else str(r).replace('.', ',')

def score(q, *fields):
    """Fuzzy score: name prefix > word prefix > substring > subsequence; secondary fields count less."""
    best = 0
    for i, f in enumerate(fields):
        f = (f or '').lower(); w = 1.0 if i == 0 else 0.6
        if not f: continue
        if f.startswith(q): s = 100
        elif any(t.startswith(q) for t in f.replace('-', ' ').split()): s = 85
        elif q in f: s = 65
        else:
            it = iter(f); s = 30 if len(q) >= 3 and all(ch in it for ch in q) else 0
        best = max(best, s * w)
    return best

class FileIndex:
    """Small in-memory index of the Files home (os.walk, max 20000 entries, hidden skipped), refreshed every 5 min."""
    def __init__(self): self.items = []; self.t = 0; self.lock = threading.Lock(); self.refresh()
    def refresh(self):
        def work():
            out = []; t0 = time.time()
            for root, dirs, files in os.walk(FILES_HOME):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for n in dirs + files:
                    if n.startswith('.'): continue
                    p = os.path.join(root, n)
                    try: out.append((n, p, os.path.isdir(p), os.path.getmtime(p)))
                    except OSError: pass
                if len(out) > 20000 or time.time() - t0 > 5: break
            with self.lock: self.items = out; self.t = time.time()
        threading.Thread(target=work, daemon=True).start()
    def search(self, q, n=5):
        if time.time() - self.t > 300: self.refresh()
        with self.lock: items = list(self.items)
        hits = [(score(q, name), mt, name, p, isdir) for name, p, isdir, mt in items]
        hits = [h for h in hits if h[0] >= 60]
        hits.sort(key=lambda h: (-h[0], -h[1])); return hits[:n]

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#lbox {{ background: {P['SURFACE']}; border-radius: 24px; padding: 16px; color: {P['ON_SURFACE']}; }}
#search {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 22px; padding: 8px 16px; min-height: 28px; color: {P['ON_SURFACE']}; font-size: 15px; caret-color: {P['ACCENT']}; }}
#search image {{ color: {P['ON_SURFACE_VARIANT']}; }}
.app {{ background: transparent; border: none; box-shadow: none; border-radius: 16px; padding: 8px 4px; color: {P['ON_SURFACE']}; }}
.app:hover, flowboxchild:selected .app, flowboxchild:focus .app {{ background: {P['SURFACE_VARIANT']}; }}
flowboxchild {{ background: transparent; padding: 0; }}
.applabel {{ font-size: 12px; }}
list {{ background: transparent; }}
row {{ border-radius: 14px; padding: 6px 10px; color: {P['ON_SURFACE']}; background: transparent; }}
row:hover {{ background: {P['SURFACE_VARIANT']}; }}
row:selected, row:selected label {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
row.hdr, row.hdr:hover {{ background: transparent; padding: 10px 10px 2px 10px; }}
.hdrl {{ font-size: 12px; font-weight: 500; color: {P['ON_SURFACE_VARIANT']}; }}
.rt {{ font-size: 14px; }}
.rs {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
row:selected .rs {{ color: {P['ON_ACCENT_CONTAINER']}; }}
.calc {{ font-size: 20px; font-weight: 500; }}
scrollbar {{ background: transparent; }}
'''

class Launcher(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Polder Launcher')
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG); self.set_name('lwin'); self.set_resizable(False)
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.prov, 800)
        self.bgprov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.bgprov, 900)
        self.palm = self.wpm = None
        self.set_size_request(W, H); self.move(MARGIN, self.sh - SHELF - H)
        self.files = FileIndex(); self.apps = []; self.load_apps()
        Gio.AppInfoMonitor.get().connect('changed', lambda *a: self.load_apps())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); box.set_name('lbox'); self.add(box)
        self.entry = Gtk.SearchEntry(); self.entry.set_name('search')
        self.entry.set_placeholder_text('Zoek op je apparaat, in apps, instellingen, op internet…')
        self.entry.connect('changed', self.on_changed); self.entry.connect('key-press-event', self.on_key)
        self.entry.connect('activate', lambda *a: self.activate_selected())
        box.pack_start(self.entry, False, False, 0)
        self.stack = Gtk.Stack(); box.pack_start(self.stack, True, True, 0)
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.grid = Gtk.FlowBox(); self.grid.set_max_children_per_line(5); self.grid.set_min_children_per_line(5)
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE); self.grid.set_homogeneous(True); self.grid.set_valign(Gtk.Align.START)
        sc.add(self.grid); self.stack.add_named(sc, 'grid')
        sc2 = Gtk.ScrolledWindow(); sc2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.list = Gtk.ListBox(); self.list.connect('row-activated', lambda lb, r: self.run_row(r)); sc2.add(self.list)
        self.stack.add_named(sc2, 'results')
        self.build_grid()
        self.connect('key-press-event', lambda w, e: e.keyval == Gdk.KEY_Escape and self.hide_l())
        self.connect('focus-out-event', lambda *a: GLib.timeout_add(150, self.maybe_hide))
        self.connect('delete-event', lambda *a: self.hide_l() or True)
        self.connect('button-press-event', self.on_press); self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, self.toggle)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, lambda *a: Gtk.main_quit() or False)
        box.show_all()
        if '--show' in sys.argv: self.show_l()

    # ----- data -----
    def load_apps(self):
        apps = [a for a in Gio.AppInfo.get_all() if a.should_show() and isinstance(a, Gio.DesktopAppInfo)]
        order = S.load().get('app_order', [])   # drag & drop order (Revision 17); unknown apps follow alphabetically
        self.apps = sorted(apps, key=lambda a: (order.index(a.get_id()) if a.get_id() in order else len(order), a.get_display_name().lower()))
        if hasattr(self, 'grid'): self.build_grid()

    def build_grid(self):
        for c in self.grid.get_children(): c.destroy()
        for a in self.apps:
            b = Gtk.Button(); b.get_style_context().add_class('app'); v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            v.pack_start(Gtk.Image.new_from_gicon(a.get_icon() or Gio.ThemedIcon.new('application-x-executable'), Gtk.IconSize.DIALOG), False, False, 0)
            l = Gtk.Label(label=a.get_display_name()); l.set_ellipsize(Pango.EllipsizeMode.END); l.set_max_width_chars(11); l.get_style_context().add_class('applabel')
            v.pack_start(l, False, False, 0); b.add(v); b.set_tooltip_text(a.get_description() or a.get_display_name())
            b.connect('clicked', lambda _b, a=a: self.launch_app(a)); self.grid.add(b)
            b.connect('button-press-event', lambda w, e, a=a: e.button == 3 and (self.app_menu(w, a, grid=True) or True))
            b.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, DND, Gdk.DragAction.MOVE)
            b.drag_source_set_icon_gicon(a.get_icon() or Gio.ThemedIcon.new('application-x-executable'))
            b.drag_dest_set(Gtk.DestDefaults.ALL, DND, Gdk.DragAction.MOVE)
            b.connect('drag-data-get', lambda w, ctx, sel, info, t, a=a: sel.set(sel.get_target(), 8, a.get_id().encode()))
            b.connect('drag-data-received', lambda w, ctx, x, y, sel, info, t, a=a: self.reorder(sel.get_data().decode(), a.get_id()))
        self.grid.show_all()

    # ----- pin / order (Revision 17) -----
    def reorder(self, src, dst):
        ids = [a.get_id() for a in self.apps]
        if src == dst or src not in ids: return
        ids.remove(src); ids.insert(ids.index(dst) + (1 if [a.get_id() for a in self.apps].index(src) < [a.get_id() for a in self.apps].index(dst) else 0), src)
        S.update(app_order=ids); print('reorder', src, '->', dst, flush=True); self.load_apps()

    def app_menu(self, w, a, grid=False):
        pinned = S.load().get('pinned', []); i = a.get_id()
        def pin(on):
            p = [x for x in S.load().get('pinned', []) if x != i]
            if on: p.append(i)
            S.update(pinned=p)
        items = [('view-pin-symbolic', 'Losmaken van plank', lambda: pin(False)) if i in pinned else ('view-pin-symbolic', 'Vastzetten aan plank', lambda: pin(True)),
                 ('media-playback-start-symbolic', 'Openen', lambda: self.launch_app(a))]
        if grid: items += [None, ('view-sort-ascending-symbolic', 'Sorteren op naam', lambda: (S.update(app_order=[]), self.load_apps()))]
        ptr = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
        self.menu = popmenu.PopMenu(items, ptr[1], ptr[2], anchor='below', title=a.get_display_name(), on_close=self.menu_closed)

    def menu_closed(self):
        self.menu = None
        if self.get_visible(): self.present(); self.entry.grab_focus_without_selecting(); self.grab()
        return False

    # ----- show/hide -----
    def refresh_style(self):
        pal = os.path.join(C, 'palette.env'); wp = os.path.join(C, 'wallpaper.png')
        if os.path.getmtime(pal) != self.palm: self.palm = os.path.getmtime(pal); self.prov.load_from_data(css().encode())
        if os.path.getmtime(wp) != self.wpm:
            self.wpm = os.path.getmtime(wp); out = f'/tmp/osb-launcher-bg-{int(self.wpm)}.png'
            subprocess.run(['convert', wp, '-crop', f'{W}x{H}+{MARGIN}+{self.sh - SHELF - H}', '+repage', out], timeout=10)
            self.bgprov.load_from_data(f"#lwin {{ background-image: url('{out}'); background-color: transparent; }}".encode())

    def toggle(self, *a):
        self.hide_l() if self.get_visible() else self.show_l(); return True

    def show_l(self):
        self.refresh_style(); self.entry.set_text(''); self.stack.set_visible_child_name('grid')
        self.move(MARGIN, self.sh - SHELF - H); self.show(); self.present_with_time(GdkX11.x11_get_server_time(self.get_window()))
        self.entry.grab_focus(); GLib.timeout_add(250, self.grab)
        try: os.utime('/tmp/osb-launcher.shown', None)
        except OSError: open('/tmp/osb-launcher.shown', 'w').close()

    def hide_l(self):
        Gdk.Display.get_default().get_default_seat().ungrab(); self.hide(); return True

    def grab(self):
        if self.get_visible():
            Gdk.Display.get_default().get_default_seat().grab(self.get_window(), Gdk.SeatCapabilities.ALL_POINTING, True, None, None, None, None)
        return False

    def on_press(self, w, e):
        win = self.get_window(); ox, oy = win.get_origin()[1:]
        if getattr(self, 'menu', None): return False
        if not (ox <= e.x_root < ox + win.get_width() and oy <= e.y_root < oy + win.get_height()): self.hide_l()
        return False

    def maybe_hide(self):
        if getattr(self, 'menu', None): return False   # our own context menu holds the grab
        if self.get_visible() and not self.is_active(): self.hide_l()
        return False

    # ----- search -----
    def on_changed(self, *a):
        q = self.entry.get_text().strip()
        if not q: self.stack.set_visible_child_name('grid'); return
        ql = q.lower()
        for c in self.list.get_children(): c.destroy()
        first = None
        m = re.match(r'^(?:installeer|install)\s+(\S+\.\S+)(?:\s+als\s+app)?(?:\s+(.+))?$', q, re.I)   # Revision 25: webapps
        if m:
            self.header('Webapp'); first = self.row('web-browser-symbolic', f'{m.group(1)} als app installeren', ('Naam: ' + m.group(2) if m.group(2) else 'Pictogram en naam komen van de website') + '  ·  Enter installeert', ('webapp', m.group(1), m.group(2)), big=True)
        r = calc(q)
        if r is not None:
            self.header('Rekenmachine'); first = first or self.row('accessories-calculator-symbolic', f'= {r}', f'{q}  ·  Enter kopieert het resultaat', ('calc', r), big=True)
        apps = sorted(((score(ql, a.get_display_name(), a.get_generic_name(), ' '.join(a.get_keywords() or []), a.get_id()), a) for a in self.apps), key=lambda t: -t[0])
        apps = [a for s, a in apps if s >= 30][:5]
        if apps:
            self.header('Apps')
            for a in apps: rw = self.row(a.get_icon() or 'application-x-executable', a.get_display_name(), a.get_generic_name() or a.get_description() or '', ('app', a)); first = first or rw
        sets = sorted(((score(ql, t, k, sub), (t, sub, sec)) for t, sub, sec, k in SECTIONS), key=lambda t: -t[0])
        sets = [x for s, x in sets if s >= 45][:3]
        if sets:
            self.header('Instellingen')
            for t, sub, sec in sets: rw = self.row('emblem-system-symbolic', t, f'Instellingen › {sub}', ('set', sec)); first = first or rw
        if len(ql) >= 2:
            files = self.files.search(ql)
            if files:
                self.header('Bestanden')
                for s, mt, name, p, isdir in files:
                    rel = os.path.relpath(os.path.dirname(p), os.path.dirname(FILES_HOME))
                    when = time.strftime('%d-%m-%Y %H:%M', time.localtime(mt))
                    rw = self.row('folder-symbolic' if isdir else self.file_icon(p), name, f'{rel} · gewijzigd {when}', ('file', p, isdir)); first = first or rw
        self.header('Internet')
        web = self.row('web-browser-symbolic', f'Zoeken op het web: {q}', 'Google in Chromium', ('web', q))
        self.list.show_all(); self.stack.set_visible_child_name('results')
        self.list.select_row(first or web)

    def file_icon(self, p):
        ct, _ = Gio.content_type_guess(p, None); return Gio.content_type_get_icon(ct)

    def header(self, text):
        r = Gtk.ListBoxRow(); r.set_selectable(False); r.set_activatable(False); r.get_style_context().add_class('hdr')
        l = Gtk.Label(label=text, xalign=0); l.get_style_context().add_class('hdrl'); r.add(l); self.list.add(r)

    def row(self, icon, title, sub, action, big=False):
        r = Gtk.ListBoxRow(); r.action = action; b = Gtk.Box(spacing=14)
        if action[0] == 'app':   # right-click a search result app -> pin menu
            eb = Gtk.EventBox(); eb.connect('button-press-event', lambda w, e: e.button == 3 and (self.app_menu(w, action[1]) or True))
        img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.DND) if not isinstance(icon, str) else Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DND)
        img.set_pixel_size(28); b.pack_start(img, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0); t.set_ellipsize(Pango.EllipsizeMode.END); t.get_style_context().add_class('calc' if big else 'rt'); v.pack_start(t, False, False, 0)
        if sub: s = Gtk.Label(label=sub, xalign=0); s.set_ellipsize(Pango.EllipsizeMode.END); s.get_style_context().add_class('rs'); v.pack_start(s, False, False, 0)
        b.pack_start(v, True, True, 0)
        if action[0] == 'app': eb.add(b); r.add(eb)
        else: r.add(b)
        self.list.add(r); return r

    def on_key(self, w, e):
        if self.stack.get_visible_child_name() != 'results' or e.keyval not in (Gdk.KEY_Down, Gdk.KEY_Up): return False
        rows = [r for r in self.list.get_children() if r.get_selectable()]
        cur = self.list.get_selected_row(); i = rows.index(cur) if cur in rows else -1
        i = max(0, min(len(rows) - 1, i + (1 if e.keyval == Gdk.KEY_Down else -1)))
        self.list.select_row(rows[i]); rows[i].grab_focus(); self.entry.grab_focus_without_selecting(); return True

    def activate_selected(self):
        r = self.list.get_selected_row()
        if self.stack.get_visible_child_name() == 'results' and r: self.run_row(r)

    # ----- actions -----
    def run_row(self, r):
        a = getattr(r, 'action', None)
        if not a: return
        kind = a[0]
        if kind == 'app': self.launch_app(a[1]); return
        if kind == 'calc':
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD); cb.set_text(a[1].replace(' ', ''), -1); cb.store()
            subprocess.Popen(['notify-send', '-a', 'Rekenmachine', 'Gekopieerd', a[1]])
        elif kind == 'webapp':
            def work(url=a[1], name=a[2]):
                sys.path.insert(0, os.path.join(C, 'webapps')); import webapps
                try: r = webapps.install(url, name); subprocess.run(['notify-send', '-a', 'Webapps', '-i', r['icon'], 'Webapp geïnstalleerd', f"{r['name']} staat nu in de launcher"])
                except Exception as e: subprocess.run(['notify-send', '-a', 'Webapps', 'Installeren mislukt', str(e)[:200]])
            threading.Thread(target=work, daemon=True).start()
        elif kind == 'set' and a[1] == '__welkom': subprocess.Popen([sys.executable, os.path.join(C, 'welcome', 'welkom.py')], start_new_session=True)
        elif kind == 'set' and a[1] == '__sneltoetsen': subprocess.Popen([sys.executable, os.path.join(C, 'shortcuts', 'sneltoetsen.py')], start_new_session=True)
        elif kind == 'set': subprocess.Popen([sys.executable, SETTINGS, a[1]], start_new_session=True)
        elif kind == 'file':
            if a[2]: subprocess.Popen([os.path.join(C, 'files', 'run-files.sh'), a[1]], start_new_session=True)
            else: subprocess.Popen(['gio', 'open', a[1]], start_new_session=True)
        elif kind == 'web':
            url = 'https://www.google.com/search?q=' + urllib.parse.quote_plus(a[1])
            # same profile as the shelf's Chromium -> opens as a tab in the running browser
            subprocess.Popen(['chromium', '--user-data-dir=/tmp/protohome/chromium', '--no-first-run', url], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.hide_l()

    def launch_app(self, a):
        try: a.launch([], None)
        except Exception as e: print('launch', e)
        self.hide_l()

if __name__ == '__main__':
    try:
        os.kill(int(open(PID).read()), 0); print('already running'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    Launcher(); Gtk.main()
