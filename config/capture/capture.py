#!/usr/bin/env python3
"""Polder OS screen capture (ChromeOS capture bar). On-demand process (exits after capturing), so no resident RAM.
Bar: Screenshot/Video, Volledig scherm / Gedeelte / Venster, settings gear, close. Screenshots are cut from a frozen
grab taken at start; video uses wf-recorder on Wayland and ffmpeg on X11.
If a recording is running, starting this stops it instead."""
import os, sys, json, time, signal, subprocess, shlex, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'osb')); import rgba as RGBA   # Rev 29.2: real rounded corners
import cairo
import osbsettings as S, osbnotify as N, popmenu
import layershell as LSH   # Rev 34d: polder-comp = wlr-screencopy (grim / wf-recorder) + layer surfaces
import capture_backend as backend
WL = bool(os.environ.get('POLDER_COMP') and os.environ.get('WAYLAND_DISPLAY'))
FILES_HOME = os.environ.get('OSB_FILES_HOME', '/tmp/osb-files/Mijn bestanden')
SHELF = 52

def dirs():
    s = S.load(); base = s.get('capture_dir') or ''
    shot = base or os.path.join(FILES_HOME, 'Afbeeldingen', 'Schermafbeeldingen')
    vid = base or os.path.join(FILES_HOME, "Video's", 'Schermopnamen')
    return shot, vid

def wl_windows():
    """polder-comp: SIGUSR2 makes it dump visible windows (topmost first, window geometry) to polder-windows.json."""
    f = os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'polder-windows.json')
    try:
        m0 = os.path.getmtime(f) if os.path.exists(f) else 0
        os.kill(int(os.environ['POLDER_COMP_PID']), signal.SIGUSR2)
        for _ in range(20):
            if os.path.exists(f) and os.path.getmtime(f) != m0: break
            time.sleep(0.05)
        skip = {'polder-shelf', 'sneltoetsen.py'}
        return [dict(id=i, title=w['title'], x=w['x'], y=w['y'], w=w['w'], h=w['h']) for i, w in enumerate(json.load(open(f))) if w['app_id'] not in skip]
    except Exception as e: print('wl_windows', e, flush=True); return []

def windows():
    """Normal windows on the current desk, topmost first, with frame geometry (x, y, w, h)."""
    if WL: return wl_windows()
    out = []
    try:
        cur = [l.split()[0] for l in subprocess.run(['wmctrl', '-d'], capture_output=True, text=True, timeout=3).stdout.splitlines() if ' * ' in l][0]
        st = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'], capture_output=True, text=True, timeout=3).stdout
        stack = [int(x, 16) for x in st.split('#', 1)[1].replace(',', ' ').split()]
        info = {int(l.split()[0], 16): l.split(None, 3) for l in subprocess.run(['wmctrl', '-l'], capture_output=True, text=True, timeout=3).stdout.splitlines()}
    except Exception: return out
    for wid in reversed(stack):
        p = info.get(wid)
        if not p or p[1] != cur: continue
        wi = subprocess.run(['xwininfo', '-id', hex(wid), '-frame'], capture_output=True, text=True, timeout=3).stdout
        g = {}
        for l in wi.splitlines():
            l = l.strip()
            for k, n in (('Absolute upper-left X:', 'x'), ('Absolute upper-left Y:', 'y'), ('Width:', 'w'), ('Height:', 'h'), ('Map State:', 'm')):
                if l.startswith(k): g[n] = l.split(':', 1)[1].strip()
        if g.get('m') != 'IsViewable': continue
        # frame extents (titlebar/borders) so the highlight covers the whole window like ChromeOS
        ext = subprocess.run(['xprop', '-id', hex(wid), '_NET_FRAME_EXTENTS'], capture_output=True, text=True, timeout=3).stdout
        try: l_, r_, t_, b_ = [int(v) for v in ext.split('=')[1].split(',')]
        except Exception: l_ = r_ = t_ = b_ = 0
        x, y, w, h = int(g['x']) - l_, int(g['y']) - t_, int(g['w']) + l_ + r_, int(g['h']) + t_ + b_
        out.append(dict(id=wid, title=(p[3] if len(p) > 3 else ''), x=x, y=y, w=w, h=h))
    return out

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#bar {{ background: {P['SURFACE']}; border-radius: 26px; padding: 6px 8px; border: 1px solid {P['OUTLINE']}; }}
.seg {{ background: {P['SURFACE_VARIANT']}; border-radius: 20px; padding: 2px; }}
.cb {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; min-width: 36px; min-height: 36px; padding: 0 8px; color: {P['ON_SURFACE']}; }}
.cb:hover {{ background: {P['OUTLINE']}; }}
.cb:checked, .cb:checked label, .cb:checked image {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.sep {{ background: {P['OUTLINE']}; min-width: 1px; margin: 8px 4px; }}
.go {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; border: none; box-shadow: none; border-radius: 20px; padding: 8px 18px; font-weight: 500; }}
.go.rec {{ background: #d93025; color: #ffffff; }}
.hint {{ background: alpha({P['SURFACE']}, 0.92); color: {P['ON_SURFACE']}; border-radius: 16px; padding: 6px 14px; }}
'''

class Overlay(Gtk.Window):
    """Fullscreen layer over the frozen screen: dims everything except the selection (region / window / full)."""
    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL if WL else Gtk.WindowType.POPUP); self.app = app
        if WL: LSH.setup(self, 'polder-capture', layer='overlay', anchors=('left', 'right', 'top', 'bottom'), exclusive=-1, keyboard='exclusive')
        self.move(0, 0); self.set_size_request(app.sw, app.sh)
        self.da = Gtk.DrawingArea(); self.da.connect('draw', self.draw)
        self.da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.da.connect('button-press-event', self.press); self.da.connect('button-release-event', self.release); self.da.connect('motion-notify-event', self.motion)
        self.fx = Gtk.Fixed(); ov = Gtk.Overlay(); ov.add(self.da); ov.add_overlay(self.fx); ov.set_overlay_pass_through(self.fx, True); self.add(ov)
        self.go = Gtk.Button(); self.go.get_style_context().add_class('go'); self.go.connect('clicked', lambda *a: app.capture()); self.go.set_no_show_all(True)
        self.hint = Gtk.Label(); self.hint.get_style_context().add_class('hint'); self.hint.set_no_show_all(True)
        self.fx.put(self.go, 0, 0); self.fx.put(self.hint, 0, 0)
        self.drag = None; self.sel = None; self.hover = None

    def draw(self, w, cr):
        a = self.app; Gdk.cairo_set_source_pixbuf(cr, a.frozen, 0, 0); cr.paint()
        r = self.sel if a.source == 'region' else (self.hover and (self.hover['x'], self.hover['y'], self.hover['w'], self.hover['h'])) if a.source == 'window' else None
        if a.source == 'full': cr.set_source_rgba(0, 0, 0, 0.12); cr.paint(); return
        cr.set_source_rgba(0, 0, 0, 0.5); cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD); cr.rectangle(0, 0, a.sw, a.sh)
        if r: cr.rectangle(*r)
        cr.fill()
        if r:
            P = N.palette(); c = Gdk.RGBA(); c.parse(P['ACCENT_CONTAINER'] if a.source == 'region' else P['ACCENT'])
            cr.set_source_rgba(c.red, c.green, c.blue, 1); cr.set_line_width(2); cr.rectangle(r[0] + .5, r[1] + .5, r[2] - 1, r[3] - 1); cr.stroke()
            if a.source == 'region':   # corner handles
                for hx, hy in ((r[0], r[1]), (r[0] + r[2], r[1]), (r[0], r[1] + r[3]), (r[0] + r[2], r[1] + r[3])):
                    cr.set_source_rgb(1, 1, 1); cr.arc(hx, hy, 5, 0, 6.3); cr.fill()

    def place_widgets(self):
        a = self.app; r = self.sel if a.source == 'region' else (self.hover and (self.hover['x'], self.hover['y'], self.hover['w'], self.hover['h']))
        self.go.set_label('Opnemen' if a.mode == 'video' else 'Vastleggen'); sc = self.go.get_style_context()
        (sc.add_class if a.mode == 'video' else sc.remove_class)('rec')
        if a.source == 'full':
            self.hint.set_text('Klik ergens om het ' + ('volledige scherm op te nemen' if a.mode == 'video' else 'volledige scherm vast te leggen'))
        elif a.source == 'window': self.hint.set_text('Klik op een venster om het ' + ('op te nemen' if a.mode == 'video' else 'vast te leggen'))
        else: self.hint.set_text('Sleep om een gedeelte te selecteren')
        show_hint = a.source == 'full' or (a.source == 'window' and not self.hover) or (a.source == 'region' and not self.sel)
        self.hint.set_visible(show_hint)
        if show_hint:
            hw, hh = self.hint.get_preferred_size()[1].width, self.hint.get_preferred_size()[1].height
            self.fx.move(self.hint, (a.sw - hw) // 2, a.sh // 2 - hh // 2)
        if a.source == 'region' and self.sel and not self.drag and self.sel[2] > 8 and self.sel[3] > 8:
            self.go.show(); gw, gh = self.go.get_preferred_size()[1].width, self.go.get_preferred_size()[1].height
            self.fx.move(self.go, int(r[0] + r[2] / 2 - gw / 2), int(r[1] + r[3] / 2 - gh / 2))
        else: self.go.hide()
        if a.source == 'region' and self.sel and self.drag:   # live size label (ChromeOS shows W × H)
            self.hint.set_text(f'{int(self.sel[2])} × {int(self.sel[3])}'); self.hint.show()
            self.fx.move(self.hint, int(self.sel[0] + self.sel[2] / 2 - 40), int(self.sel[1] + self.sel[3] + 8))
        self.da.queue_draw()

    def press(self, w, e):
        a = self.app
        if e.button != 1: return
        if a.source == 'region': self.drag = (e.x, e.y); self.sel = (e.x, e.y, 0, 0); self.place_widgets()
        elif a.source == 'window' and self.hover: a.capture()
        elif a.source == 'full': a.capture()

    def motion(self, w, e):
        a = self.app
        if a.source == 'region' and self.drag:
            x0, y0 = self.drag; self.sel = (min(x0, e.x), min(y0, e.y), abs(e.x - x0), abs(e.y - y0)); self.place_widgets()
        elif a.source == 'window':
            hv = next((wi for wi in a.wins if wi['x'] <= e.x < wi['x'] + wi['w'] and wi['y'] <= e.y < wi['y'] + wi['h']), None)
            if hv is not self.hover: self.hover = hv; self.place_widgets()

    def release(self, w, e):
        if self.drag: self.drag = None; self.place_widgets()

class App:
    def __init__(self):
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        self.origin = (0, 0); self.monitor = None
        self.bar_background = str(backend.runtime_dir() / 'osb-capbar-bg.png')
        if WL:   # frozen frame via wlr-screencopy (grim), taken before our overlay maps
            display = Gdk.Display.get_default()
            self.monitor = display.get_primary_monitor() or display.get_monitor(0)
            geometry = self.monitor.get_geometry()
            self.origin = (geometry.x, geometry.y)
            self.sw, self.sh = geometry.width, geometry.height
            fd, tmp = tempfile.mkstemp(prefix='capture-', suffix='.png', dir=backend.runtime_dir())
            os.close(fd)
            try:
                subprocess.run(['grim', '-s', '1', '-g', f'{geometry.x},{geometry.y} {self.sw}x{self.sh}', tmp],
                               timeout=10, check=True, capture_output=True)
                self.frozen = GdkPixbuf.Pixbuf.new_from_file(tmp)
            finally:
                os.unlink(tmp)
        else:
            root = Gdk.get_default_root_window(); self.frozen = Gdk.pixbuf_get_from_window(root, 0, 0, self.sw, self.sh)
        self.wins = windows(); self.mode = 'shot'; self.source = 'region'
        if WL:
            for window in self.wins:
                window['x'] -= self.origin[0]; window['y'] -= self.origin[1]
        prov = Gtk.CssProvider(); prov.load_from_data(css().encode()); Gtk.StyleContext.add_provider_for_screen(scr, prov, 850)
        self.ov = Overlay(self)
        if WL: LSH.LS.set_monitor(self.ov, self.monitor)
        self.ov.show_all()
        self.bar = Gtk.Window(type=Gtk.WindowType.TOPLEVEL if WL else Gtk.WindowType.POPUP); self.bar.set_name('barwin'); RGBA.enable(self.bar)
        b = Gtk.Box(spacing=4); b.set_name('bar'); self.bar.add(b)
        seg1 = Gtk.Box(spacing=2); seg1.get_style_context().add_class('seg'); self.mbtn = {}
        for k, icon, tip in (('shot', 'camera-photo-symbolic', 'Screenshot'), ('video', 'camera-video-symbolic', 'Schermopname (video)')):
            t = Gtk.ToggleButton(); t.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)); t.get_style_context().add_class('cb'); t.set_tooltip_text(tip)
            t.connect('toggled', self.set_mode, k); seg1.pack_start(t, False, False, 0); self.mbtn[k] = t
        b.pack_start(seg1, False, False, 0); s = Gtk.Box(); s.get_style_context().add_class('sep'); b.pack_start(s, False, False, 0)
        self.sbtn = {}
        for k, icon, label in (('full', 'view-fullscreen-symbolic', 'Volledig scherm'), ('region', 'edit-select-all-symbolic', 'Gedeelte'), ('window', 'window-new-symbolic', 'Venster')):
            t = Gtk.ToggleButton(); bx = Gtk.Box(spacing=6); bx.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            bx.pack_start(Gtk.Label(label=label), False, False, 0); t.add(bx); t.get_style_context().add_class('cb'); t.set_tooltip_text(label)
            t.connect('toggled', self.set_source, k); b.pack_start(t, False, False, 0); self.sbtn[k] = t
        s = Gtk.Box(); s.get_style_context().add_class('sep'); b.pack_start(s, False, False, 0)
        g = Gtk.Button(); g.add(Gtk.Image.new_from_icon_name('emblem-system-symbolic', Gtk.IconSize.MENU)); g.get_style_context().add_class('cb'); g.set_tooltip_text('Instellingen')
        g.connect('clicked', self.settings); b.pack_start(g, False, False, 0)
        x = Gtk.Button(); x.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); x.get_style_context().add_class('cb'); x.set_tooltip_text('Sluiten (Esc)')
        x.connect('clicked', lambda *a: self.quit()); b.pack_start(x, False, False, 0)
        self._busy = False; self.mbtn['shot'].set_active(True); self.sbtn['region'].set_active(True)
        b.show_all(); bw, bh = b.get_preferred_size()[1].width, b.get_preferred_size()[1].height
        self.bx, self.by = (self.sw - bw) // 2, self.sh - SHELF - bh - 16
        if WL:
            LSH.setup(self.bar, 'polder-capture-bar', layer='overlay', anchors=('bottom',), margins={'bottom': SHELF + 16}, exclusive=-1, keyboard='none')
            LSH.LS.set_monitor(self.bar, self.monitor)
        bg = self.bar_background
        if RGBA.active(self.bar):
            p2 = Gtk.CssProvider(); p2.load_from_data(b'#barwin { background: transparent; background-image: none; }'); self.bar.get_style_context().add_provider(p2, 905)
        else: self.frozen.new_subpixbuf(self.bx, self.by, bw, bh).savev(bg, 'png', [], [])   # rounded corners show the real screen
        p2 = Gtk.CssProvider(); p2.load_from_data(f"#barwin {{ background-image: url('{bg}'); }}".encode()); self.bar.get_style_context().add_provider(p2, 900)
        # dimmed backdrop under the bar would differ from the overlay; use the overlay's dimmed look by re-rendering later
        self.bar.move(self.bx, self.by); self.bar.show_all()
        if not RGBA.active(self.bar): self.bar_bg(bw, bh)
        for w in (self.ov, self.bar): w.connect('key-press-event', self.key)
        GLib.timeout_add(80, self.grab)

    def bar_bg(self, bw, bh):
        """Bar corners must match the dimmed overlay underneath -> render overlay pixels for that rect."""
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, bw, bh); cr = cairo.Context(surf); cr.translate(-self.bx, -self.by)
        self.ov.draw(None, cr); surf.write_to_png(self.bar_background)
        p = Gtk.CssProvider(); p.load_from_data(f"#barwin {{ background-image: url('{self.bar_background}'); }}".encode())
        self.bar.get_style_context().add_provider(p, 901); self.bar.queue_draw()

    def grab(self):
        if WL: return False   # the overlay layer has exclusive keyboard interactivity
        st = Gdk.Display.get_default().get_default_seat().grab(self.ov.get_window(), Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None)
        return st != Gdk.GrabStatus.SUCCESS

    def excl(self, group, key):
        self._busy = True
        for k, t in group.items(): t.set_active(k == key)
        self._busy = False

    def set_mode(self, t, k):
        if self._busy: return
        if not t.get_active(): self._busy = True; t.set_active(True); self._busy = False; return
        self.excl(self.mbtn, k); self.mode = k; self.ov.place_widgets()

    def set_source(self, t, k):
        if self._busy: return
        if not t.get_active(): self._busy = True; t.set_active(True); self._busy = False; return
        self.excl(self.sbtn, k); self.source = k; self.ov.sel = None; self.ov.hover = None; self.ov.place_widgets()
        if hasattr(self, 'bx'): self.bar_bg(*self.bar.get_size())

    def settings(self, btn):
        s = S.load(); shot, vid = dirs(); ptr = s.get('capture_pointer', False)
        def toggle_ptr(): S.update(capture_pointer=not ptr)
        def choose_dir():
            d = Gtk.FileChooserDialog(title='Opslaan in', action=Gtk.FileChooserAction.SELECT_FOLDER)
            d.add_buttons('Annuleren', Gtk.ResponseType.CANCEL, 'Kiezen', Gtk.ResponseType.OK); d.set_keep_above(True)
            d.set_current_folder(os.path.dirname(shot) if os.path.isdir(os.path.dirname(shot)) else FILES_HOME)
            if d.run() == Gtk.ResponseType.OK: S.update(capture_dir=d.get_filename())
            d.destroy()
        items = [(None, f'Opslaan in: {os.path.basename(shot)}' + ('' if s.get('capture_dir') else ' / Schermopnamen'), None),
                 ('folder-symbolic', 'Map wijzigen…', choose_dir)]
        if s.get('capture_dir'): items.append(('edit-undo-symbolic', 'Standaardmappen herstellen', lambda: S.update(capture_dir='')))
        if not WL: items += [None, ('object-select-symbolic' if ptr else None, 'Muisaanwijzer tonen (video)', toggle_ptr)]   # wf-recorder can't draw the pointer
        # Audio capture is not offered until its source selection is implemented.
        a = btn.get_allocation(); x, y = (self.bx, self.by) if WL else self.bar.get_window().get_origin()[1:]
        popmenu.PopMenu(items, x + a.x, y - 8, anchor='above', title='Schermopname', on_close=lambda: self.grab() and False)

    def key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.quit(); return True
        if e.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter): self.capture(); return True
        return False

    def rect(self):
        if self.source == 'full': return (0, 0, self.sw, self.sh)
        if self.source == 'window' and self.ov.hover: h = self.ov.hover; return (h['x'], h['y'], h['w'], h['h'])
        if self.source == 'region' and self.ov.sel and min(self.ov.sel[2:]) > 8: return tuple(int(v) for v in self.ov.sel)
        return None

    def capture(self):
        r = self.rect()
        if not r: return
        r = backend.clip_rect(r, self.sw, self.sh)
        if not r: return
        x, y, w, h = r
        shot, vid = dirs(); stamp = time.strftime('%Y-%m-%d %H.%M.%S') + f'.{time.time_ns() % 1000000000:09d}'
        if self.mode == 'shot':
            os.makedirs(shot, exist_ok=True); path = os.path.join(shot, f'Schermafbeelding {stamp}.png')
            self.frozen.new_subpixbuf(x, y, w, h).savev(path, 'png', [], [])
            if WL:
                try:
                    with open(path, 'rb') as image:
                        # wl-copy's clipboard owner forks and keeps inherited pipes open.
                        copied = subprocess.run(['wl-copy', '-t', 'image/png'], stdin=image,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                timeout=5).returncode == 0
                except (OSError, subprocess.SubprocessError):
                    copied = False
            else: subprocess.Popen(['sh', '-c', 'xclip -selection clipboard -t image/png -i "$0" >/dev/null 2>&1 &', path])   # xclip keeps owning the clipboard
            self.notify('Schermafbeelding gemaakt', 'Ook gekopieerd naar het klembord.' if not WL or copied else 'Opgeslagen; kopiëren naar het klembord is mislukt.', path, shot)
            self.quit(); return
        # video: even sizes for x264
        os.makedirs(vid, exist_ok=True); path = os.path.join(vid, f'Schermopname {stamp}.mp4')
        ff = backend.recording_command(path, r, WL, S.load().get('capture_pointer', False), self.origin)
        self.hide_all()
        def start_recording():
            subprocess.Popen([sys.executable, os.path.abspath(__file__), '--record', json.dumps(ff)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            Gtk.main_quit()
            return False
        # Keep dispatching Wayland events while the overlay unmaps.
        GLib.timeout_add(300, start_recording)

    def notify(self, title, body, image, folder):
        notify(title, body, image, folder)

    def hide_all(self):
        if not WL: Gdk.Display.get_default().get_default_seat().ungrab()
        self.bar.hide(); self.ov.hide()
        Gdk.Display.get_default().flush()

    def quit(self):
        self.hide_all(); Gtk.main_quit()

def notify(title, body, image, folder):
    """Real notification with thumbnail + 'Map tonen' action (waits for the click in a detached helper)."""
    files = os.path.join(C, 'files', 'run-files.sh')
    sh = ('a=$(timeout 900 notify-send --wait -a Schermopname -h "string:image-path:$1" -A "map=Map tonen" "$2" "$3"); '
          '[ "$a" = map ] && exec "$4" "$5"')
    subprocess.Popen(['sh', '-c', sh, 'x', image, title, body, files, folder], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    if sys.argv[1:2] == ['--record']:   # detached recorder: ffmpeg + state file for the shelf pill, notify when done
        ff = json.loads(sys.argv[2]); p = ff[-1]
        ok = backend.run_recording(ff)
        thumb = str(backend.runtime_dir() / 'osb-rec-thumb.png')
        if ok:
            try:
                subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-sseof', '-0.5', '-i', p, '-frames:v', '1', '-vf', 'scale=240:-1', thumb], timeout=30)
            except (OSError, subprocess.SubprocessError): pass
        notify('Schermopname opgeslagen' if ok else 'Schermopname mislukt', os.path.basename(p) if ok else f'Zie {backend.runtime_dir() / "osb-rec.log"}',
               thumb if ok else '', os.path.dirname(p)); sys.exit(0 if ok else 1)
    if backend.stop_recording(): sys.exit(0)     # Print / Ctrl+Shift+F5 / QS tile while recording = stop
    lock = backend.acquire_lock('osb-capture.lock')
    if lock is None: sys.exit(0)
    try:
        App(); Gtk.main()
    except (OSError, ValueError, GLib.Error, subprocess.SubprocessError) as error:
        print(f'capture: {error}', file=sys.stderr, flush=True)
        notify('Schermopname mislukt', 'Het scherm kon niet worden vastgelegd.', '', dirs()[0])
    finally:
        os.close(lock)
