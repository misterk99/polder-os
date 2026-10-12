#!/usr/bin/env python3
"""Polder OS app shelf (centre of the plank): pinned apps + running unpinned apps, running dot, active highlight,
right-click rounded menu (Losmaken/Vastzetten, Nieuw venster, Sluiten). Replaces tint2-shelf-apps.rc because tint2
has no per-icon context menus. Pinned list = settings.json 'pinned' (desktop ids); reloads live on change."""
import os, sys, subprocess, shlex
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Gio
from Xlib import display as xdisplay, X
import shutil

class WlTasks:
    """Rev 33: running windows on Wayland (polder-comp) via wlr-foreign-toplevel-management. The protocol is spoken by
    the small C helper polder-toplevels (JSON lines out, commands in), so no pywayland dependency."""
    def __init__(self, on_change):
        exe = os.environ.get('POLDER_TOPLEVELS') or shutil.which('polder-toplevels') or \
              os.path.join(C, '..', 'compositor', 'polder-comp', 'tools', 'polder-toplevels')
        self.tl = {}; self.on_change = on_change
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1); self.buf = b''
        GLib.io_add_watch(self.p.stdout.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self.read)
    def read(self, src, cond):
        data = os.read(self.p.stdout.fileno(), 65536)   # raw read: a buffered readline() would strand queued lines
        if not data: return False
        self.buf += data
        *lines, self.buf = self.buf.split(b'\n')
        for line in lines:
            try: ev = json.loads(line)
            except ValueError: continue
            if ev['ev'] == 'state': self.tl[ev['id']] = ev
            elif ev['ev'] == 'closed': self.tl.pop(ev['id'], None)
        self.on_change(); return True
    def send(self, cmd, wid):
        try: self.p.stdin.write(f'{cmd} {wid}\n'); self.p.stdin.flush()
        except (BrokenPipeError, OSError) as e: print('toplevels', e, flush=True)
    def active(self): return next((i for i, t in self.tl.items() if t['activated']), 0)
import osbsettings as S, osbnotify as N, popmenu, mpris, json, time
import layershell as LSH   # Rev 32d: layer-shell on polder-comp (Wayland), no-op on X11
H = 52; PID = os.path.join(LSH.rundir(), 'osb-shelf.pid')
SKIPCLS = {'tint2', 'polder-shell.py', 'qs.py', 'osb-notifyd.py', 'launcher.py', 'shelf.py', 'cal.py', 'overview.py', 'clipd.py', 'xfdesktop', 'lock.py'}

def css():
    P = N.palette()
    return f'''
#shelf {{ background: {P['SURFACE']}; }}
.sapp {{ background: transparent; border: none; box-shadow: none; border-radius: 20px; padding: 3px 5px 1px 5px; min-width: 40px; }}
.sapp:hover {{ background: {P['SURFACE_VARIANT']}; }}
.sapp.active {{ background: {P['ACCENT_CONTAINER']}; }}
.dot {{ background: {P['ON_SURFACE_VARIANT']}; border-radius: 2px; min-width: 4px; min-height: 4px; }}
.sapp.active .dot {{ background: {P['ACCENT']}; min-width: 12px; }}
.nodot {{ min-height: 4px; }}
.recpill {{ background: #d93025; color: #ffffff; border: none; box-shadow: none; border-radius: 18px; padding: 4px 12px; font-family: Roboto; font-weight: 500; }}
.recpill image {{ color: #ffffff; }}
.mediapill {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border: none; box-shadow: none; border-radius: 18px; padding: 4px 12px; font-family: Roboto; }}
.pill {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border: none; box-shadow: none; border-radius: 18px; padding: 0 14px; min-height: 36px; font-family: Roboto; font-weight: 500; font-size: 11.5pt; }}
.pill:hover {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.pill image {{ color: {P['ON_SURFACE']}; }}
.badge {{ background: {P['ON_SURFACE']}; color: {P['SURFACE']}; border-radius: 10px; min-width: 18px; min-height: 18px; font-size: 8.5pt; }}
.lbtn {{ background: transparent; border: none; box-shadow: none; border-radius: 22px; padding: 2px; }}
.lbtn:hover {{ background: {P['SURFACE_VARIANT']}; }}
.mediapill:hover {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
'''

class AppDB:
    def __init__(self): self.reload()
    def reload(self):
        self.apps = {}; self.keys = {}
        for a in Gio.AppInfo.get_all():
            if not isinstance(a, Gio.DesktopAppInfo): continue
            i = a.get_id(); self.apps[i] = a
            ks = {i[:-8].lower().split('.')[-1], (a.get_startup_wm_class() or '').lower()}
            # entries with StartupWMClass (e.g. webapps running 'chromium --app=') match on that only, never steal 'chromium'
            if not a.get_startup_wm_class():
              try: ks |= {os.path.basename(t).lower() for t in shlex.split(a.get_commandline() or '') if not t.startswith('-') and '%' not in t}
              except ValueError: pass
            for k in ks:
                if k and k not in ('python3', 'sh', 'env', 'bash') and (k not in self.keys or a.should_show()): self.keys[k] = i
    def for_class(self, inst, cls):
        for k in (inst, cls, inst.split('.')[0]):
            if k and k.lower() in self.keys: return self.keys[k.lower()]
        return None

class Desktop(Gtk.Window):
    """Revision 20: a _NET_WM_WINDOW_TYPE_DESKTOP window showing the wallpaper, so right-clicks on the empty desktop
    reach us (xfwm4 owns ButtonPress on the root window). Lives in the shelf process: no extra daemon."""
    def __init__(self, sw, sh):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Polder Bureaublad')
        self.set_name('desk'); self.set_decorated(False); self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.stick(); self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        if not LSH.setup(self, 'polder-desktop', layer='background', anchors=('left', 'right', 'top', 'bottom'), exclusive=-1):
            self.move(0, 0); self.set_size_request(sw, sh)
        self.prov = Gtk.CssProvider(); self.get_style_context().add_provider(self.prov, 900)
        self.wpm = None; self.refresh()
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK); self.connect('button-press-event', self.on_press)
        self.connect('delete-event', lambda *a: True); self.show_all()

    def refresh(self):
        wp = os.path.join(C, 'wallpaper.png')
        if not os.path.exists(wp): wp = os.path.join(C, 'wallpapers', 'polderheuvel.png')   # Rev 33b: default Polderheuvel
        try: m = os.path.getmtime(wp)
        except OSError: return
        if m != self.wpm:
            self.wpm = m; out = f'/tmp/osb-desk-{int(m)}.png'   # new path per change: GTK caches images by URL
            import shutil, glob
            for f in glob.glob('/tmp/osb-desk-*.png'):
                try: os.remove(f)
                except OSError: pass
            shutil.copyfile(wp, out)
            self.prov.load_from_data(f"#desk {{ background-image: url('{out}'); background-size: cover; background-color: #000; }}".encode())
            self.queue_draw()

    def on_press(self, w, e):
        if e.button != 3: return False
        run = lambda *a: subprocess.Popen(list(a), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        settings = os.path.join(C, 'settings', 'instellingen.py')
        items = [('preferences-desktop-wallpaper-symbolic', 'Achtergrond en stijl', lambda: run('python3', settings, 'personalisatie')),
                 ('system-file-manager-symbolic', 'Bestanden openen', lambda: run(os.path.join(C, 'files', 'run-files.sh'))),
                 None,
                 ('emblem-system-symbolic', 'Instellingen', lambda: run('python3', settings)),
                 ('input-keyboard-symbolic', 'Sneltoetsen', lambda: run('python3', os.path.join(C, 'shortcuts', 'sneltoetsen.py')))]
        self.menu = popmenu.PopMenu(items, int(e.x_root), int(e.y_root), anchor='below')
        return True

SYM = '/usr/share/icons/Papirus/24x24/symbolic'
def sh(cmd, t=3):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception: return ''
def run(*a): subprocess.Popen(list(a), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class Status:
    """Rev 33b: launcher button + right-hand status pills, native GTK (tint2 + render-status.sh do this on X11).
    Same rules as render-status.sh: wifi/volume/battery icons only when the real hardware/info exists."""
    def __init__(self, shelf):
        self.launcher = Gtk.Button(valign=Gtk.Align.CENTER); self.launcher.get_style_context().add_class('lbtn')
        try:
            from gi.repository import GdkPixbuf
            self.launcher.add(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(C, 'launcher-icon.png'), 32, 32)))
        except Exception: self.launcher.add(Gtk.Image.new_from_icon_name('view-app-grid-symbolic', Gtk.IconSize.LARGE_TOOLBAR))
        self.launcher.set_tooltip_text('Launcher'); self.launcher.connect('clicked', lambda *a: run(os.path.join(C, 'launcher', 'launcher-toggle.sh')))
        self.right = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.shelf = shelf
        self.kb = self.pill(self.kb_menu, 'Toetsenbordindeling')
        self.wx = self.pill(lambda b: run('python3', os.path.join(C, 'calendar', 'cal.py'), '--weather', self.right_of(b)), 'Weer')
        self.date = self.pill(lambda b: run('python3', os.path.join(C, 'calendar', 'cal.py'), self.right_of(b)), 'Agenda')
        self.tray = self.pill(lambda *a: run('python3', os.path.join(C, 'quicksettings', 'qs.py')), 'Snelle instellingen')
        for p in (self.kb, self.wx, self.date, self.tray): self.right.pack_start(p, False, False, 0)
        self.key = None; self.slow = 0; self.wxtext = ''; self.right.show_all(); self.wx.set_no_show_all(True); self.wx.hide()
    def layout(self):
        """The keymap polder-comp compiled: XKB_DEFAULT_LAYOUT (inherited from the compositor), else its default 'us'."""
        return (os.environ.get('XKB_DEFAULT_LAYOUT') or 'us').split(',')[0]
    def kb_menu(self, b):
        x = b.translate_coordinates(self.shelf, 0, 0)[0]; lay = self.layout(); v = os.environ.get('XKB_DEFAULT_VARIANT', '')
        items = [('input-keyboard-symbolic', f'Indeling: {lay}' + (f' ({v})' if v else ''), lambda: None),
                 ('input-keyboard-symbolic', 'Sneltoetsen', lambda: run('python3', os.path.join(C, 'shortcuts', 'sneltoetsen.py')))]
        self.shelf.menu = popmenu.PopMenu(items, x, self.shelf.sh - H - 6, anchor='above', title='Toetsenbord')
    def right_of(self, b):
        """--right=<px from the screen's right edge to the pill's right edge> so the panel opens right above the pill."""
        x = b.translate_coordinates(self.shelf, 0, 0)[0] + b.get_allocated_width()
        return f'--right={self.shelf.sw - x}'
    def pill(self, cb, tip):
        b = Gtk.Button(); b.get_style_context().add_class('pill'); b.add(Gtk.Box(spacing=8)); b.set_tooltip_text(tip); b.connect('clicked', cb); return b
    def icon(self, name):
        import glob
        f = glob.glob(f'{SYM}/*/{name}-symbolic.svg')
        im = Gtk.Image.new_from_icon_name(name + '-symbolic', Gtk.IconSize.MENU) if not f else Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(f[0])), Gtk.IconSize.MENU)
        im.set_pixel_size(18); return im
    def fill(self, btn, parts):
        bx = btn.get_child()
        for c in bx.get_children(): c.destroy()
        for p in parts: bx.pack_start(p, False, False, 0)
        bx.show_all()
    def slow_probe(self):
        """wifi / volume / battery / weather: polled every ~10 s (cheap enough, and only real values)."""
        st = {}
        q = sh(['nmcli', '-t', '-f', 'IN-USE,SIGNAL', 'dev', 'wifi']) if shutil.which('nmcli') else ''
        sig = next((l.split(':')[1] for l in q.splitlines() if l.startswith('*')), None)
        if sig and sig.isdigit():
            n = int(sig); st['wifi'] = 'network-wireless-signal-' + ('excellent' if n >= 80 else 'good' if n >= 60 else 'ok' if n >= 30 else 'weak')
        elif shutil.which('nmcli') and 'ethernet:connected' in sh(['nmcli', '-t', '-f', 'TYPE,STATE', 'dev']): st['wifi'] = 'network-wired'
        if shutil.which('pactl'):
            v = sh(['pactl', 'get-sink-volume', '@DEFAULT_SINK@']); m = sh(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'])
            import re; pc = re.findall(r'(\d+)%', v)
            if pc: n = int(pc[0]); st['vol'] = 'audio-volume-' + ('muted' if 'yes' in m or n == 0 else 'high' if n > 66 else 'medium' if n > 33 else 'low')
        import glob
        bat = sorted(glob.glob('/sys/class/power_supply/BAT*'))
        if bat:
            try: st['bat'] = f'battery-level-{(int(open(bat[0] + "/capacity").read()) + 5) // 10 * 10}'
            except (OSError, ValueError): pass
        st['upd'] = os.path.exists('/tmp/osb-update.json')
        return st
    def update(self):
        self.slow -= 1
        if self.slow <= 0:
            self.slow = 14; self.st = self.slow_probe()
            import threading
            def wx():
                r = sh(['python3', os.path.join(C, 'weather', 'weather.py'), 'pill'], 6); GLib.idle_add(self.set_wx, r)
            threading.Thread(target=wx, daemon=True).start()
        sets = S.load()
        try: ns = json.load(open('/tmp/osb-notify/state.json'))
        except Exception: ns = {}
        tf = '%H:%M' if sets.get('clock24', True) else '%-I:%M'
        M = 'jan feb mrt apr mei jun jul aug sep okt nov dec'.split(); t = time.localtime()
        key = (time.strftime(tf), sets.get('show_date', True), ns.get('unread', 0), ns.get('dnd', False), tuple(sorted(self.st.items())), N.palette()['THEME'])
        if key == self.key: return
        self.key = key
        self.fill(self.kb, [Gtk.Label(label=self.layout().upper())])
        self.date.set_visible(bool(sets.get('show_date', True)))
        self.fill(self.date, [Gtk.Label(label=f'{t.tm_mday} {M[t.tm_mon - 1]}')])
        parts = [Gtk.Label(label=key[0])]
        if ns.get('dnd'): parts.append(self.icon('notifications-disabled'))
        elif ns.get('unread'): b = Gtk.Label(label=str(ns['unread'])); b.get_style_context().add_class('badge'); parts.append(b)
        if self.st.get('upd'): parts.append(self.icon('go-up'))
        for k in ('wifi', 'vol', 'bat'):
            if k in self.st: parts.append(self.icon(self.st[k]))
        self.fill(self.tray, parts)
    def set_wx(self, r):
        if r and ' ' in r: self.fill(self.wx, [self.icon(r.split(' ')[0]), Gtk.Label(label=r.split(' ', 1)[1])]); self.wx.show()
        else: self.wx.hide()

class Shelf(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Polder Plank')
        self.set_name('shelf'); self.set_decorated(False); self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True); self.stick(); self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True); self.set_resizable(False)
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        # Rev 33b: on Wayland there is no tint2, so the shelf IS the whole bar: full width, launcher left, apps centred,
        # status pills right (same layout as tint2rc 'EFSEEEE' in the X11 session). On X11 it stays the centred app strip.
        self.full = LSH.wayland()
        LSH.setup(self, 'polder-shelf', layer='top', anchors=('left', 'right', 'bottom') if self.full else ('bottom',), exclusive=H)
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.prov, 800); self.palm = None
        outer = Gtk.Box(spacing=8); self.box = Gtk.Box(spacing=4); self.box.set_border_width(4)
        if self.full:
            bar = Gtk.Box(); bar.set_size_request(-1, H); self.add(bar); self.status = Status(self)
            bar.pack_start(self.status.launcher, False, False, 6); bar.set_center_widget(outer); bar.pack_end(self.status.right, False, False, 8)
        else: self.add(outer)
        outer.pack_start(self.box, False, False, 0)
        # Revision 18: recording stop pill + media pill (only while something plays); live in this process, no new daemon
        self.extra = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER); outer.pack_start(self.extra, False, False, 0)
        self.rec = Gtk.Button(); self.rec.get_style_context().add_class('recpill'); rb = Gtk.Box(spacing=6)
        rb.pack_start(Gtk.Image.new_from_icon_name('media-playback-stop-symbolic', Gtk.IconSize.MENU), False, False, 0)
        self.reclabel = Gtk.Label(label='0:00'); rb.pack_start(self.reclabel, False, False, 0); self.rec.add(rb)
        self.rec.set_tooltip_text('Schermopname stoppen'); self.rec.connect('clicked', self.stop_rec); self.rec.set_no_show_all(True); rb.show_all()
        self.media = Gtk.Button(); self.media.get_style_context().add_class('mediapill'); mb = Gtk.Box(spacing=6)
        self.mediaicon = Gtk.Image.new_from_icon_name('media-playback-pause-symbolic', Gtk.IconSize.MENU); mb.pack_start(self.mediaicon, False, False, 0)
        self.medialabel = Gtk.Label(); self.medialabel.set_max_width_chars(18); self.medialabel.set_ellipsize(3); mb.pack_start(self.medialabel, False, False, 0)
        self.media.add(mb); mb.show_all(); self.media.set_no_show_all(True); self.media.connect('clicked', self.media_toggle)
        self.extra.pack_start(self.rec, False, False, 0); self.extra.pack_start(self.media, False, False, 0); self.mstate = None; self.mpoll = 0
        self.db = AppDB(); Gio.AppInfoMonitor.get().connect('changed', lambda *a: (self.db.reload(), self.render(force=True)))
        self.wl = WlTasks(lambda: GLib.idle_add(self.render)) if LSH.wayland() else None
        if not self.wl: self.x = xdisplay.Display(); self.root = self.x.screen().root
        self.A = {} if self.wl else {n: self.x.intern_atom(n) for n in ('_NET_CLIENT_LIST_STACKING', '_NET_ACTIVE_WINDOW', '_NET_CURRENT_DESKTOP', '_NET_WM_DESKTOP',
                  '_NET_WM_WINDOW_TYPE', '_NET_WM_WINDOW_TYPE_NORMAL', '_NET_WM_WINDOW_TYPE_DIALOG', '_NET_WM_STATE', '_NET_WM_STATE_SKIP_TASKBAR', '_NET_WM_STATE_HIDDEN')}
        self.sig = None; self.setm = None; self.menu = None
        self.desk = Desktop(self.sw, self.sh)
        self.render(force=True); GLib.timeout_add(700, self.tick)
        if self.full: self.status.update()

    def prop(self, w, name):
        try:
            p = w.get_full_property(self.A[name], X.AnyPropertyType); return list(p.value) if p else []
        except Exception: return []

    def windows(self):
        """[(wid, app_id or 'cls:<class>', class, hidden)] topmost first, current desk, normal windows only."""
        if self.wl:
            out = []
            for i, t in sorted(self.wl.tl.items()):   # creation order: icons must not jump when focus changes
                aid = t['app_id'] or t['title']
                if aid.lower() in SKIPCLS: continue
                did = next((d for d in (aid + '.desktop', aid.lower() + '.desktop') if d in self.db.apps), None)
                out.append((i, did or self.db.for_class(aid, aid) or f'cls:{aid}', aid, t['minimized']))
            return out
        desk = (self.prop(self.root, '_NET_CURRENT_DESKTOP') or [0])[0]; out = []
        for wid in reversed(self.prop(self.root, '_NET_CLIENT_LIST_STACKING')):
            w = self.x.create_resource_object('window', wid)
            d = self.prop(w, '_NET_WM_DESKTOP')
            if d and d[0] not in (desk, 0xFFFFFFFF): continue
            t = self.prop(w, '_NET_WM_WINDOW_TYPE')
            if t and not set(t) & {self.A['_NET_WM_WINDOW_TYPE_NORMAL'], self.A['_NET_WM_WINDOW_TYPE_DIALOG']}: continue
            st = self.prop(w, '_NET_WM_STATE')
            if self.A['_NET_WM_STATE_SKIP_TASKBAR'] in st: continue
            try: inst, cls = (w.get_wm_class() or ('', ''))
            except Exception: continue
            inst = inst.split(' ')[0]
            if inst.lower() in SKIPCLS: continue
            app = self.db.for_class(inst, cls) or f'cls:{cls or inst}'
            out.append((wid, app, cls or inst, self.A['_NET_WM_STATE_HIDDEN'] in st))
        return out

    def stop_rec(self, *a):
        try: os.kill(json.load(open('/tmp/osb-rec.json'))['pid'], 2)
        except Exception as e: print('stop rec', e, flush=True)

    def media_toggle(self, *a):
        if self.mstate: mpris.control(self.mstate['name'], 'PlayPause'); self.mpoll = 0

    def update_extra(self):
        changed = False
        try: st = json.load(open('/tmp/osb-rec.json'))
        except Exception: st = None
        if st:
            el = int(time.time() - st['start']); self.reclabel.set_text(f'{el // 60}:{el % 60:02d}')
        if bool(st) != self.rec.get_visible(): self.rec.set_visible(bool(st)); changed = True
        self.mpoll -= 1
        if self.mpoll <= 0:
            self.mpoll = 3; m = mpris.active(); self.mstate = m
            show = bool(m and m['status'] == 'Playing')
            if show: self.medialabel.set_text(m['title'] + (f" · {m['artist']}" if m['artist'] else ''))
            if show != self.media.get_visible(): self.media.set_visible(show); changed = True
        return changed

    def tick(self):
        if self.full:
            try: self.status.update()
            except Exception as e: print('status', e, flush=True)
        try: self.desk.refresh()
        except Exception as e: print('desk', e, flush=True)
        try:
            if self.update_extra(): self.render(force=True)
        except Exception as e: print('extra', e, flush=True)
        try: self.render()
        except Exception as e: print('tick', e, flush=True)
        return True

    def render(self, force=False):
        pal = os.path.join(C, 'palette.env')
        if os.path.getmtime(pal) != self.palm: self.palm = os.path.getmtime(pal); self.prov.load_from_data(css().encode())
        try: m = os.path.getmtime(S.FILE)
        except OSError: m = 0
        if m != self.setm: self.setm = m; self.pinned = [p for p in S.load().get('pinned', []) if p in self.db.apps]; force = True
        self.wins = self.windows(); act = self.wl.active() if self.wl else (self.prop(self.root, '_NET_ACTIVE_WINDOW') or [0])[0]
        self.active_app = next((a for wid, a, c, h in self.wins if wid == act), None)
        running = []
        for wid, a, c, h in self.wins:
            if a not in running: running.append(a)
        order = self.pinned + [a for a in running if a not in self.pinned]
        sig = (tuple(order), tuple(running), self.active_app)
        if sig == self.sig and not force: return
        self.sig = sig
        for ch in self.box.get_children(): ch.destroy()
        for a in order: self.box.pack_start(self.button(a, a in running), False, False, 0)
        self.box.show_all(); w = self.get_child().get_preferred_size()[1].width
        if self.full: w = self.sw
        self.resize(max(w, 1), H)
        if not LSH.active(self): self.move((self.sw - w) // 2, self.sh - H)
        if not self.get_visible(): self.show_all()

    def button(self, app, running):
        b = Gtk.Button(); sc = b.get_style_context(); sc.add_class('sapp')
        if app == self.active_app: sc.add_class('active')
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ai = self.db.apps.get(app)
        gicon = ai.get_icon() if ai and ai.get_icon() else Gio.ThemedIcon.new_from_names([app[4:].lower(), 'application-x-executable'])
        im = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DND); im.set_pixel_size(34); v.pack_start(im, False, False, 0)
        d = Gtk.Box(halign=Gtk.Align.CENTER); d.get_style_context().add_class('dot' if running else 'nodot'); v.pack_start(d, False, False, 0)
        b.add(v); b.set_tooltip_text(ai.get_display_name() if ai else app[4:])
        b.connect('button-press-event', self.on_press, app); return b

    def app_windows(self, app): return [w for w in self.wins if w[1] == app]

    def on_press(self, b, e, app):
        if e.button == 3: self.context(b, app); return True
        if e.button == 2: self.launch(app); return True
        if e.button == 1 and e.type == Gdk.EventType.BUTTON_PRESS:
            ws = self.app_windows(app)
            if not ws: self.launch(app)
            elif self.wl: self.wl.send('minimize' if self.active_app == app else 'activate', ws[0][0])
            elif self.active_app == app: subprocess.run(['xdotool', 'windowminimize', str(ws[0][0])], timeout=3)
            else: subprocess.run(['wmctrl', '-i', '-a', hex(ws[0][0])], timeout=3)
            GLib.timeout_add(250, self.tick); return True
        return False

    def launch(self, app):
        ai = self.db.apps.get(app)
        if ai:
            try: ai.launch([], None)
            except Exception as ex: print('launch', ex, flush=True)

    def context(self, b, app):
        ai = self.db.apps.get(app); ws = self.app_windows(app); items = []
        if ai:
            items.append(('view-pin-symbolic', 'Losmaken', lambda: self.set_pin(app, False)) if app in self.pinned
                         else ('view-pin-symbolic', 'Vastzetten', lambda: self.set_pin(app, True)))
            items.append(('window-new-symbolic', 'Nieuw venster', lambda: self.launch(app)))
        if ws:
            items.append(None); items.append(('window-close-symbolic', 'Sluiten' if len(ws) == 1 else f'Sluiten ({len(ws)} vensters)',
                                              lambda: [self.wl.send('close', w[0]) if self.wl else subprocess.run(['wmctrl', '-i', '-c', hex(w[0])], timeout=3) for w in ws]))
        ox, oy = self.get_window().get_origin()[1:]; bx = b.translate_coordinates(self, 0, 0)[0]
        if LSH.active(self): ox, oy = (0 if self.full else (self.sw - self.get_allocated_width()) // 2), self.sh - H   # layer surface: origin is ours to compute
        self.menu = popmenu.PopMenu(items, ox + bx, oy - 6, anchor='above', title=ai.get_display_name() if ai else app[4:])

    def set_pin(self, app, on):
        p = [x for x in S.load().get('pinned', []) if x != app]
        if on: p.append(app)
        S.update(pinned=p)

if __name__ == '__main__':
    try: os.kill(int(open(PID).read()), 0); print('already running'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    Shelf(); Gtk.main()
