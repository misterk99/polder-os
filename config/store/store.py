#!/usr/bin/env python3
"""Polder Store: lightweight software center (Revision 22). Runs only while open.
Metadata: AppStream (Debian DEP-11 + Flathub appstream) -> only real desktop apps with icons.
Backends: Debian packages via PackageKit (PackageKitGlib over the system bus, polkit-authorised like any distro),
Flathub via the flatpak CLI (system installation). Dutch UI, unified Polder OS palette (light/dark)."""
import os, sys, re, html, json, subprocess, threading, time, urllib.request, hashlib, concurrent.futures as CF
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(C, 'notify')); sys.path.insert(0, os.path.join(C, 'osb'))
sys.path.insert(0, HERE)
import store_catalog as Catalog
import gi
for n, v in (('Gtk', '3.0'), ('AppStream', '1.0'), ('PackageKitGlib', '1.0')): gi.require_version(n, v)
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Gio, Pango, AppStream as AS, PackageKitGlib as PK
import osbnotify as N
def OSBS_FILE(): return os.environ.get('OSB_SETTINGS') or os.path.expanduser('~/.config/osb/settings.json')
CACHE = os.path.expanduser('~/.cache/polder-store'); os.makedirs(CACHE, exist_ok=True)
POOL = CF.ThreadPoolExecutor(4)
FEATURED = ['org.gimp.GIMP', 'org.libreoffice.LibreOffice', 'org.videolan.VLC', 'org.inkscape.Inkscape',
            'com.github.xournalpp.xournalpp', 'org.gnome.Mines', 'org.kde.krita', 'com.obsproject.Studio']
CATS = [('Alles', None), ('Kantoor', 'Office'), ('Grafisch', 'Graphics'), ('Audio en video', 'AudioVideo'), ('Spellen', 'Game'),
        ('Internet', 'Network'), ('Ontwikkeling', 'Development'), ('Onderwijs', 'Education'), ('Hulpmiddelen', 'Utility')]

def run(cmd, t=60):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout
    except Exception: return ''

class App:
    """One AppStream component (Debian package or Flathub app)."""
    def __init__(self, c, icon_dirs=None):
        self.c = c; self.id = c.get_id(); self.name = c.get_name() or self.id; self.summary = c.get_summary() or ''
        b = c.get_bundle(AS.BundleKind.FLATPAK)
        self.flatpak = b.get_id() if b else None          # Native-architecture Flatpak reference.
        self.pkg = None if self.flatpak else c.get_pkgname()
        self.source = 'Flathub' if self.flatpak else 'Debian'
        self.cats = list(c.get_categories() or [])
        self.icon_file, self.icon_url, self.stock = Catalog.resolve_icons(
            c.get_icons(), AS.IconKind, Catalog.icon_directories() if icon_dirs is None else icon_dirs)
    @property
    def key(self): return f'{self.source}:{self.id}'
    def has_icon(self): return bool(self.icon_file or self.icon_url or self.stock)
    def flatpak_app(self): return self.flatpak.split('/')[1] if self.flatpak else None

def fetch(url):
    """Download (and cache) an icon/screenshot URL, return local path or None."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + os.path.splitext(url)[1][:5])
    if not os.path.exists(f):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'PolderStore/0.1'}), timeout=15) as r:
                open(f + '.part', 'wb').write(r.read()); os.rename(f + '.part', f)
        except Exception: return None
    return f

def desc_text(c):
    """AppStream description is tiny XML (<p>, <ul><li>) -> plain text with bullets."""
    d = c.get_description() or ''
    d = re.sub(r'<li>', '• ', d); d = re.sub(r'</(p|li)>', '\n', d); d = re.sub(r'<[^>]+>', '', d)
    paras = []
    for para in re.split(r'\n\s*\n', d):          # join wrapped lines inside a paragraph; keep bullets on their own line
        out = []
        for l in (x.strip() for x in para.splitlines()):
            if not l: continue
            if out and not l.startswith('•') and not out[-1].startswith('•'): out[-1] += ' ' + l
            else: out.append(l)
        paras.append('\n'.join(out))
    d = '\n\n'.join(p for p in paras if p)
    return html.unescape(re.sub(r'\n{3,}', '\n\n', d)).strip()

class Backend:
    def __init__(self):
        self.pk = PK.Client()
        self.debs, self.flats = set(), set()
    def refresh_installed(self):
        self.debs = {l.split()[0] for l in run(['dpkg-query', '-W', '-f', '${Package} ${db:Status-Status}\n']).splitlines() if l.endswith(' installed')}
        self.flats = set(run(['flatpak', 'list', '--app', '--columns=application']).split())
    def installed(self, a): return (a.flatpak_app() in self.flats) if a.flatpak else (a.pkg in self.debs)
    # all calls below run in a worker thread; progress(pct, text) is marshalled by the caller
    def record(self, a, add):   # Rev 30: list of Store-installed apps for Polder Sync (restore offers to install them)
        f = os.path.join(os.path.dirname(OSBS_FILE()), 'store-installed.json')
        try: lst = json.load(open(f))
        except Exception: lst = []
        aid = a.flatpak_app() or a.pkg; lst = [x for x in lst if x.get('id') != aid]
        if add: lst.append({'id': aid, 'source': a.source, 'name': a.name})
        os.makedirs(os.path.dirname(f), exist_ok=True); json.dump(lst, open(f, 'w'), indent=1)
    def install(self, a, progress):
        self._install(a, progress)
        try: self.record(a, True)
        except Exception as e: print('record', e)
    def remove(self, a, progress):
        self._remove(a, progress)
        try: self.record(a, False)
        except Exception as e: print('record', e)
    def _install(self, a, progress):
        if a.flatpak: return self._flatpak(['install', '--system', '-y', '--noninteractive', 'flathub', a.flatpak_app()], progress)
        ids = [p.get_id() for p in self.pk.resolve(PK.FilterEnum.NOT_INSTALLED, [a.pkg], None, lambda *x: None, None).get_package_array()]
        if not ids: raise RuntimeError(f'pakket {a.pkg} niet gevonden')
        self.pk.install_packages(1 << PK.TransactionFlagEnum.ONLY_TRUSTED, ids[:1], None, self._pkprog(progress), None)
    def _remove(self, a, progress):
        if a.flatpak: return self._flatpak(['uninstall', '--system', '-y', '--noninteractive', a.flatpak_app()], progress)
        ids = [p.get_id() for p in self.pk.resolve(PK.FilterEnum.INSTALLED, [a.pkg], None, lambda *x: None, None).get_package_array()]
        self.pk.remove_packages(0, ids[:1], False, True, None, self._pkprog(progress), None)
    def updates(self):
        out = [('Debian', p.get_name(), p.get_version()) for p in
               self.pk.get_updates(PK.FilterEnum.NONE, None, lambda *x: None, None).get_package_array()]
        for l in run(['flatpak', 'remote-ls', '--system', '--updates', '--app', '--columns=application,version'], 120).splitlines():
            if l.strip(): p = l.split('\t'); out.append(('Flathub', p[0], p[1] if len(p) > 1 else ''))
        return out
    def update_all(self, progress):
        self.pk.refresh_cache(False, None, lambda *x: None, None)
        ids = [p.get_id() for p in self.pk.get_updates(PK.FilterEnum.NONE, None, lambda *x: None, None).get_package_array()]
        if ids: self.pk.update_packages(1 << PK.TransactionFlagEnum.ONLY_TRUSTED, ids, None, self._pkprog(progress), None)
        self._flatpak(['update', '--system', '-y', '--noninteractive'], progress)
    def _pkprog(self, progress):
        def cb(p, t, *a):
            pct = p.get_property('percentage')
            if 0 <= pct <= 100: progress(pct, 'Bezig…')
        return cb
    def _flatpak(self, args, progress):
        p = subprocess.Popen(['flatpak'] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        buf = ''
        while True:
            ch = p.stdout.read(1)
            if not ch: break
            buf += ch
            if ch in '\r\n':
                m = re.findall(r'(\d{1,3})%', buf)
                if m: progress(int(m[-1]), 'Downloaden…')
                buf = ''
        if p.wait(timeout=1800): raise RuntimeError('flatpak ' + args[0] + ' mislukt')

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
window, .bg {{ background: {P['SURFACE']}; color: {P['ON_SURFACE']}; }}
#top {{ padding: 10px 18px; border-bottom: 1px solid {P['SURFACE_VARIANT']}; }}
.brand {{ font-size: 18px; font-weight: 500; }}
.tab {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; padding: 6px 16px; color: {P['ON_SURFACE']}; }}
.tab:checked {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
#search {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 20px; padding: 6px 14px; color: {P['ON_SURFACE']}; min-width: 280px; }}
.h2 {{ font-size: 16px; font-weight: 500; padding: 14px 4px 6px 4px; }}
.card {{ background: {P['SURFACE_VARIANT']}; border-radius: 16px; padding: 12px; }}
.card:hover {{ background: {P['ACCENT_CONTAINER']}; }}
.feat {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; border-radius: 20px; padding: 16px; }}
.cname {{ font-weight: 500; font-size: 14px; }}
.csum, .sub {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 12px; }}
.feat .csum {{ color: {P['ON_ACCENT_CONTAINER']}; }}
.badge {{ background: {P['SURFACE']}; color: {P['ACCENT']}; border-radius: 10px; padding: 1px 8px; font-size: 11px; font-weight: 500; }}
.chip {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 14px; color: {P['ON_SURFACE']}; }}
.chip:checked {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; }}
.big {{ font-size: 24px; font-weight: 500; }}
.primary {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; border: none; box-shadow: none; border-radius: 20px; padding: 7px 22px; font-weight: 500; }}
button.primary:disabled, button.primary:disabled label {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE_VARIANT']}; }}
.secondary {{ background: transparent; color: {P['ACCENT']}; border: 1px solid {P['OUTLINE']}; box-shadow: none; border-radius: 20px; padding: 7px 22px; font-weight: 500; }}
.flat {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; color: {P['ON_SURFACE']}; }}
.flat:hover {{ background: {P['SURFACE_VARIANT']}; }}
progressbar trough {{ background: {P['SURFACE_VARIANT']}; border-radius: 4px; min-height: 6px; }}
progressbar progress {{ background: {P['ACCENT']}; border-radius: 4px; min-height: 6px; }}
.row {{ padding: 10px 6px; border-bottom: 1px solid {P['SURFACE_VARIANT']}; }}
.shot {{ border-radius: 12px; }}
'''

class Store(Gtk.Window):
    def __init__(self):
        super().__init__(title='Polder Store'); self.set_default_size(1000, 640); self.set_wmclass('polder-store', 'Polder Store')
        self.set_icon_name('system-software-install')
        self.prov = Gtk.CssProvider(); self.prov.load_from_data(css().encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.prov, 900)
        self.be = Backend(); self.apps = []; self.byid = {}; self.busy = {}
        self.pool = None; self.closed = False; self.catalog_loading = False; self.catalog_reload_pending = False
        self.catalog_status = Catalog.read_status(); self.catalog_seen = Catalog.catalog_signature()
        self.catalog_last_request = 0; self.catalog_request_pending = False
        self.catalog_error = None; self.catalog_last_load = 0; self.category = None
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.add(v)
        top = Gtk.Box(spacing=8); top.set_name('top'); v.pack_start(top, False, False, 0)
        self.back = Gtk.Button.new_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON); self.back.get_style_context().add_class('flat')
        self.back.connect('clicked', lambda *a: self.go_back()); top.pack_start(self.back, False, False, 0)
        logo = GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(C, 'brand', 'polderos-logo-64.png'), 28, 28, True)
        top.pack_start(Gtk.Image.new_from_pixbuf(logo), False, False, 4)
        l = Gtk.Label(label='Polder Store'); l.get_style_context().add_class('brand'); top.pack_start(l, False, False, 0)
        self.tabs = {}; g = None
        for key, lab in (('home', 'Ontdekken'), ('installed', 'Geïnstalleerd'), ('updates', 'Updates')):
            b = Gtk.RadioButton.new_with_label_from_widget(g, lab); g = g or b; b.set_mode(False); b.get_style_context().add_class('tab')
            b.connect('toggled', self.on_tab, key); self.tabs[key] = b; top.pack_start(b, False, False, 2 if key != 'home' else 12)
        self.search = Gtk.SearchEntry(placeholder_text='Apps zoeken'); self.search.set_name('search')
        self.search.connect('search-changed', self.on_search); top.pack_end(self.search, False, False, 0)
        self.catalog_bar = Gtk.Box(spacing=12); self.catalog_bar.set_border_width(12)
        self.catalog_bar.set_no_show_all(True)
        self.catalog_label = Gtk.Label(xalign=0); self.catalog_label.set_line_wrap(True)
        self.catalog_bar.pack_start(self.catalog_label, True, True, 0)
        self.catalog_retry = Gtk.Button(label='Opnieuw proberen')
        self.catalog_retry.connect('clicked', lambda *args: self.request_catalog_refresh(True))
        self.catalog_bar.pack_end(self.catalog_retry, False, False, 0); v.pack_start(self.catalog_bar, False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120); v.pack_start(self.stack, True, True, 0)
        sp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=12)
        self.catalog_spinner = Gtk.Spinner(); self.catalog_spinner.set_size_request(32, 32)
        sp.pack_start(self.catalog_spinner, False, False, 0)
        self.catalog_empty_label = Gtk.Label(label='Apps laden…')
        sp.pack_start(self.catalog_empty_label, False, False, 0); self.stack.add_named(sp, 'loading')
        self.history = []; self.connect('destroy', self.on_destroy); self.show_all(); self.back.hide()
        self.load(); self.update_catalog_status()
        GLib.timeout_add_seconds(3, self.watch_catalog)

    # ---------- data ----------
    def load(self):
        if self.closed: return
        if self.catalog_loading:
            self.catalog_reload_pending = True
            return
        self.catalog_loading = True; self.catalog_last_load = time.time()
        def work():
            try:
                pool = AS.Pool(); pool.load()
                directories = Catalog.icon_directories()
                apps = Catalog.collect_apps(pool.get_components().as_array(), AS.ComponentKind.DESKTOP_APP,
                                            lambda component: App(component, directories))
                self.be.refresh_installed()
                GLib.idle_add(self.catalog_loaded, pool, apps, None)
            except Exception as error:
                print('Store catalog load failed:', error, flush=True)
                GLib.idle_add(self.catalog_loaded, None, None, error)
        threading.Thread(target=work, daemon=True).start()

    def catalog_loaded(self, pool, apps, error):
        if self.closed: return False
        if not error and self.apps and not apps:
            error = RuntimeError('The refreshed catalog contains no desktop applications')
        self.catalog_loading = False; self.catalog_error = error
        if error:
            self.update_catalog_status()
            if self.catalog_reload_pending:
                self.catalog_reload_pending = False; self.load()
            return False  # A refresh failure must not erase the usable cached catalog.
        self.apps = apps; self.pool = pool; self.byid = {}
        for a in self.apps: self.byid.setdefault(a.id, []).append(a)
        visible = self.stack.get_visible_child_name()
        if visible in ('loading', 'home', 'search'):
            if self.search.get_text().strip(): self.on_search(self.search)
            else: self.show_home(self.category)
        self.update_catalog_status()
        if Catalog.should_refresh(self.catalog_status, len(self.apps), self.catalog_last_request):
            self.request_catalog_refresh()
        if self.catalog_reload_pending:
            self.catalog_reload_pending = False; self.load()
        return False

    def watch_catalog(self):
        if self.closed: return False
        previous = self.catalog_status
        self.catalog_status = Catalog.read_status()
        signature = Catalog.catalog_signature()
        finished = self.catalog_status.get('phase') in ('ready', 'retry') and (
            self.catalog_status.get('updated_at'), self.catalog_status.get('phase')) != (
            previous.get('updated_at'), previous.get('phase'))
        if signature != self.catalog_seen or finished or (self.catalog_error and time.time() - self.catalog_last_load >= 60):
            self.catalog_seen = signature; self.load()
        self.update_catalog_status()
        if Catalog.should_refresh(self.catalog_status, len(self.apps), self.catalog_last_request):
            self.request_catalog_refresh()
        return True

    def request_catalog_refresh(self, force=False):
        if self.closed or self.catalog_request_pending: return
        if not force and not Catalog.should_refresh(self.catalog_status, len(self.apps), self.catalog_last_request): return
        self.catalog_last_request = time.time(); self.catalog_request_pending = True
        self.update_catalog_status()
        def work():
            try:
                result = subprocess.run(['systemctl', 'start', '--no-block', Catalog.REFRESH_UNIT],
                                        stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
                success = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                success = False
            GLib.idle_add(self.catalog_refresh_requested, success)
        threading.Thread(target=work, daemon=True).start()

    def catalog_refresh_requested(self, success):
        if self.closed: return False
        self.catalog_request_pending = False
        if success:
            self.catalog_status = dict(self.catalog_status, phase='refreshing')
        else:
            self.catalog_status = dict(self.catalog_status, phase='retry', reason='offline')
        self.update_catalog_status()
        return False

    def update_catalog_status(self):
        message = Catalog.status_message(self.catalog_status, len(self.apps))
        if self.catalog_error:
            message = 'De appcatalogus kon niet worden gelezen. We proberen het automatisch opnieuw.'
            if self.apps: message += ' Je opgeslagen apps blijven beschikbaar.'
        self.catalog_label.set_text(message); self.catalog_bar.set_visible(bool(message))
        self.catalog_label.show(); self.catalog_retry.show()
        refreshing = self.catalog_status.get('phase') == 'refreshing'
        self.catalog_retry.set_sensitive(not refreshing and not self.catalog_request_pending)
        if not self.apps:
            self.catalog_empty_label.set_text('Apps laden…' if self.catalog_loading or refreshing else 'Nog geen appcatalogus beschikbaar')
            if self.catalog_loading or refreshing: self.catalog_spinner.start()
            else: self.catalog_spinner.stop()

    def on_destroy(self, *args):
        self.closed = True
        Gtk.main_quit()

    def set_icon(self, img, a, size):
        def done(path):
            try: img.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True))
            except Exception: img.set_from_icon_name('application-x-executable', Gtk.IconSize.DIALOG)
        if a.icon_file: done(a.icon_file); return
        img.set_from_icon_name(a.stock or 'application-x-executable', Gtk.IconSize.DIALOG); img.set_pixel_size(size)
        if a.icon_url:
            POOL.submit(lambda: (lambda p: p and GLib.idle_add(done, p))(fetch(a.icon_url)))

    # ---------- widgets ----------
    def card(self, a, feat=False):
        eb = Gtk.EventBox(); b = Gtk.Box(spacing=12); b.get_style_context().add_class('feat' if feat else 'card'); eb.add(b)
        img = Gtk.Image(); self.set_icon(img, a, 64 if feat else 48); b.pack_start(img, False, False, 0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER); b.pack_start(t, True, True, 0)
        n = Gtk.Label(label=a.name, xalign=0, ellipsize=Pango.EllipsizeMode.END); n.get_style_context().add_class('cname'); t.pack_start(n, False, False, 0)
        s = Gtk.Label(label=a.summary, xalign=0, ellipsize=Pango.EllipsizeMode.END, lines=2, wrap=True, max_width_chars=28)
        s.get_style_context().add_class('csum'); t.pack_start(s, False, False, 0)
        bd = Gtk.Box(spacing=6); x = Gtk.Label(label=a.source); x.get_style_context().add_class('badge'); bd.pack_start(x, False, False, 0)
        if self.be.installed(a):
            y = Gtk.Label(label='Geïnstalleerd'); y.get_style_context().add_class('badge'); bd.pack_start(y, False, False, 0)
        t.pack_start(bd, False, False, 2)
        eb.connect('button-release-event', lambda *e: self.show_detail(a)); eb.set_size_request(300 if not feat else 230, -1)
        return eb

    def grid(self, apps, cols=3):
        fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=cols, min_children_per_line=cols,
                         column_spacing=10, row_spacing=10, homogeneous=True)
        for a in apps: fb.add(self.card(a))
        return fb

    def page(self, name, child):
        old = self.stack.get_child_by_name(name)
        if old: old.destroy()
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER); box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_border_width(18); box.pack_start(child, False, False, 0); sw.add(box); sw.show_all()
        self.stack.add_named(sw, name); self.stack.set_visible_child_name(name)

    def h2(self, box, text):
        l = Gtk.Label(label=text, xalign=0); l.get_style_context().add_class('h2'); box.pack_start(l, False, False, 0)

    # ---------- pages ----------
    def show_home(self, cat=None):
        self.category = cat
        if not self.apps:
            self.stack.set_visible_child_name('loading'); self.back.hide()
            self.update_catalog_status()
            return False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.h2(box, 'Uitgelicht')
        fr = Gtk.Box(spacing=10, homogeneous=True); n = 0
        for fid in FEATURED:
            for a in self.byid.get(fid, []) + self.byid.get(fid + '.desktop', []):
                if a.source == 'Debian' or not any(x.source == 'Debian' for x in self.byid.get(fid, [])):
                    fr.pack_start(self.card(a, True), True, True, 0); n += 1; break
            if n == 4: break
        box.pack_start(fr, False, False, 0)
        self.h2(box, 'Categorieën')
        cb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12, column_spacing=6, row_spacing=6); g = None
        for lab, key in CATS:
            b = Gtk.RadioButton.new_with_label_from_widget(g, lab); g = g or b; b.set_mode(False); b.get_style_context().add_class('chip')
            b.set_active(key == cat); b.connect('toggled', lambda w, k: w.get_active() and self.show_home(k), key); cb.add(b)
        box.pack_start(cb, False, False, 0)
        sel = [a for a in self.apps if cat is None or cat in a.cats]
        sel.sort(key=lambda a: (a.source != 'Debian', a.name.lower()))
        self.h2(box, f'{dict((k, l) for l, k in CATS)[cat] if cat else "Alle apps"} · {len(sel)} apps')
        box.pack_start(self.grid(sel[:60]), False, False, 0)
        self.page('home', box); self.back.hide(); self.history = []
        return False

    def on_tab(self, b, key):
        if not b.get_active() or not self.apps: return
        self.search.set_text('')
        {'home': self.show_home, 'installed': self.show_installed, 'updates': self.show_updates}[key]()

    def on_search(self, e):
        q = e.get_text().strip()
        if not q: self.show_home(); return
        if not getattr(self, 'pool', None): return
        hits = []
        for c in self.pool.search(q).as_array():
            for a in self.byid.get(c.get_id(), []):
                if a not in hits: hits.append(a)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.h2(box, f'Resultaten voor “{q}” · {len(hits)}' if hits else f'Geen apps gevonden voor “{q}”')
        box.pack_start(self.grid(hits[:45]), False, False, 0); self.page('search', box); self.back.hide()

    def show_installed(self):
        self.be.refresh_installed()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); inst = [a for a in self.apps if self.be.installed(a)]
        self.h2(box, f'Geïnstalleerde apps · {len(inst)}'); box.pack_start(self.grid(inst), False, False, 0)
        self.page('installed', box); self.back.hide()

    def show_updates(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hb = Gtk.Box(); self.h2(hb, 'Updates zoeken…'); box.pack_start(hb, False, False, 0); self.page('updates', box)
        def work():
            try: ups = self.be.updates(); err = None
            except Exception as e: ups, err = [], str(e)
            GLib.idle_add(self.fill_updates, ups, err)
        threading.Thread(target=work, daemon=True).start()

    def fill_updates(self, ups, err):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hb = Gtk.Box(spacing=12)
        self.h2(hb, f'Fout: {err}' if err else (f'{len(ups)} updates beschikbaar' if ups else 'Alles is up-to-date'))
        if ups:
            b = Gtk.Button(label='Alles bijwerken'); b.get_style_context().add_class('primary'); b.set_valign(Gtk.Align.CENTER)
            pb = Gtk.ProgressBar(valign=Gtk.Align.CENTER); pb.set_size_request(200, -1); pb.set_no_show_all(True)
            b.connect('clicked', lambda *a: self.job(self.be.update_all, None, b, pb, lambda: self.show_updates()))
            hb.pack_end(b, False, False, 0); hb.pack_end(pb, False, False, 0)
        box.pack_start(hb, False, False, 0)
        for src, name, ver in ups:
            r = Gtk.Box(spacing=10); r.get_style_context().add_class('row')
            r.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0); s = Gtk.Label(label=ver); s.get_style_context().add_class('sub'); r.pack_start(s, False, False, 0)
            x = Gtk.Label(label=src); x.get_style_context().add_class('badge'); r.pack_start(x, False, False, 0); box.pack_start(r, False, False, 0)
        self.page('updates', box)

    def show_detail(self, a):
        cur = self.stack.get_visible_child_name()
        if cur != 'detail': self.history.append(cur)
        self.cur = a
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        hd = Gtk.Box(spacing=18); img = Gtk.Image(); self.set_icon(img, a, 96); hd.pack_start(img, False, False, 0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER); hd.pack_start(t, True, True, 0)
        n = Gtk.Label(label=a.name, xalign=0); n.get_style_context().add_class('big'); t.pack_start(n, False, False, 0)
        dev = a.c.get_developer().get_name() if a.c.get_developer() else ''
        s = Gtk.Label(label=a.summary + (f' · {dev}' if dev else ''), xalign=0, wrap=True); s.get_style_context().add_class('sub'); t.pack_start(s, False, False, 0)
        meta = Gtk.Box(spacing=8); bd = Gtk.Label(label=a.source); bd.get_style_context().add_class('badge'); meta.pack_start(bd, False, False, 0)
        self.size_l = Gtk.Label(label='Grootte: …'); self.size_l.get_style_context().add_class('sub'); meta.pack_start(self.size_l, False, False, 0)
        lic = a.c.get_project_license()
        if lic: q = Gtk.Label(label=lic); q.get_style_context().add_class('sub'); meta.pack_start(q, False, False, 0)
        t.pack_start(meta, False, False, 2)
        act = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER); hd.pack_end(act, False, False, 0)
        bb = Gtk.Box(spacing=8); act.pack_start(bb, False, False, 0)
        self.pb = Gtk.ProgressBar(); self.pb.set_no_show_all(True); act.pack_start(self.pb, False, False, 0)
        self.stat = Gtk.Label(label=''); self.stat.get_style_context().add_class('sub'); act.pack_start(self.stat, False, False, 0)
        self.bb = bb; self.fill_buttons(a); box.pack_start(hd, False, False, 0)
        shots = Gtk.Box(spacing=10); sw = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER); sw.add(shots); sw.set_min_content_height(0)
        urls = []
        for sc in a.c.get_screenshots_all()[:4]:
            best = None
            for im in sc.get_images():
                if im.get_kind() == AS.ImageKind.THUMBNAIL and 300 <= im.get_width() <= 760: best = im.get_url(); break
                best = best or im.get_url()
            if best: urls.append(best)
        if urls:
            hl = Gtk.Label(label='Schermafbeeldingen', xalign=0); hl.get_style_context().add_class('h2'); box.pack_start(hl, False, False, 0)
            sw.set_min_content_height(250); box.pack_start(sw, False, False, 0)
            for w in (hl, sw): w.set_no_show_all(True)   # only shown once a screenshot really downloaded (stale URLs exist)
            for u in urls:
                def setp(p, hl=hl, sw=sw, shots=shots):
                    try:
                        im = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(p, 420, 240, True))
                        shots.pack_start(im, False, False, 0); im.show(); shots.show()
                        for w in (hl, sw): w.set_no_show_all(False); w.show_all()
                    except Exception: pass
                POOL.submit(lambda u=u, setp=setp: (lambda p: p and GLib.idle_add(setp, p))(fetch(u)))
        self.h2(box, 'Over deze app')
        d = Gtk.Label(label=desc_text(a.c) or a.summary, xalign=0, wrap=True, max_width_chars=110, selectable=True); box.pack_start(d, False, False, 0)
        self.page('detail', box); self.back.show()
        threading.Thread(target=self.load_size, args=(a,), daemon=True).start()

    def load_size(self, a):
        txt = ''
        if a.flatpak:
            out = run(['flatpak', 'remote-info', '--system', 'flathub', a.flatpak_app()], 30)
            m = re.search(r'Download:\s*(.+)', out) or re.search(r'Download size:\s*(.+)', out)
            i = re.search(r'Installed:\s*(.+)', out) or re.search(r'Installed size:\s*(.+)', out)
            txt = ' · '.join(x for x in (m and 'download ' + m.group(1).strip(), i and 'geïnstalleerd ' + i.group(1).strip()) if x)
        elif a.pkg:
            out = run(['apt-cache', 'show', '--no-all-versions', a.pkg], 20)
            m = re.search(r'^Installed-Size:\s*(\d+)', out, re.M); s = re.search(r'^Size:\s*(\d+)', out, re.M)
            if m: txt = f'{int(m.group(1))/1024:.1f} MB geïnstalleerd' + (f' · download {int(s.group(1))/1048576:.1f} MB' if s else '')
        GLib.idle_add(lambda: self.cur is a and self.size_l.set_text('Grootte: ' + (txt or 'onbekend')))

    def fill_buttons(self, a):
        for w in self.bb.get_children(): w.destroy()
        if a.key in self.busy: return
        if self.be.installed(a):
            o = Gtk.Button(label='Openen'); o.get_style_context().add_class('primary'); o.connect('clicked', lambda *x: self.open_app(a))
            r = Gtk.Button(label='Verwijderen'); r.get_style_context().add_class('secondary')
            r.connect('clicked', lambda *x: self.job(self.be.remove, a, r, self.pb, lambda: self.after(a, 'verwijderd')))
            self.bb.pack_start(r, False, False, 0); self.bb.pack_start(o, False, False, 0)
        else:
            i = Gtk.Button(label='Installeren'); i.get_style_context().add_class('primary')
            i.connect('clicked', lambda *x: self.job(self.be.install, a, i, self.pb, lambda: self.after(a, 'geïnstalleerd')))
            self.bb.pack_start(i, False, False, 0)
        self.bb.show_all()

    def job(self, fn, a, btn, pb, done):
        for w in (self.bb.get_children() if a else [btn]): w.set_sensitive(False)
        if a: self.busy[a.key] = True
        pb.show(); pb.set_fraction(0); pb.set_text(None)
        if a: self.stat.set_text('Wachten op autorisatie…')
        def prog(p, t): GLib.idle_add(lambda: (pb.set_fraction(p / 100), a and self.cur is a and self.stat.set_text(f'{t} {p}%')) and False)
        def work():
            err = None
            try: fn(a, prog) if a else fn(prog)
            except Exception as e: err = getattr(e, 'message', None) or str(e)
            GLib.idle_add(fin, err)
        def fin(err):
            if a: self.busy.pop(a.key, None)
            pb.hide()
            if err:
                if a and self.cur is a: self.stat.set_text('Mislukt: ' + err[:80])
                subprocess.Popen(['notify-send', '-a', 'Polder Store', 'Mislukt', err[:200]])
                if a: self.fill_buttons(a)
                else: btn.set_sensitive(True)
            else: done()
        threading.Thread(target=work, daemon=True).start()

    def after(self, a, what):
        self.be.refresh_installed()
        if self.cur is a: self.stat.set_text(f'{a.name} is {what}'); self.fill_buttons(a)
        subprocess.Popen(['notify-send', '-a', 'Polder Store', '-i', 'system-software-install', f'{a.name} {what}', f'Bron: {a.source}'])

    def open_app(self, a):
        if a.flatpak: subprocess.Popen(['flatpak', 'run', a.flatpak_app()], start_new_session=True); return
        l = a.c.get_launchable(AS.LaunchableKind.DESKTOP_ID); ids = l.get_entries() if l else [a.id]
        for i in ids:
            try:
                ai = Gio.DesktopAppInfo.new(i if i.endswith('.desktop') else i + '.desktop')
                if ai: ai.launch([], None); return
            except Exception: pass
        self.stat.set_text('Geen starter gevonden')

    def go_back(self):
        prev = self.history.pop() if self.history else 'home'
        if self.stack.get_child_by_name(prev): self.stack.set_visible_child_name(prev)
        else: self.show_home()
        if prev in ('installed',): self.show_installed()
        self.back.set_visible(bool(self.history))

if __name__ == '__main__':
    st = Store()
    if 'updates' in sys.argv[1:]: GLib.idle_add(lambda: st.tabs['updates'].set_active(True))   # Revision 26: deep link from Instellingen
    Gtk.main()
