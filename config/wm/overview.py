#!/usr/bin/env python3
"""ChromeOS-style Overview (mode 'overview') and Alt+Tab switcher (mode 'alttab').
Overview: fullscreen window, dimmed wallpaper, desks bar on top, window thumbnails grid.
Alt+Tab: centered rounded strip; grabs keyboard, Tab/Shift+Tab cycles, releasing Alt activates."""
import os, sys, subprocess, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'osb')); import rgba as RGBA   # Rev 29.2: real rounded corners
import winlist as WL
import layershell as LSH   # Rev 34g: on polder-comp the overview/switcher are layer surfaces; desks live in the compositor
WAY = WL.WLMODE
SHELF = 52
DNDFLAG = 0 if WAY else Gtk.TargetFlags.SAME_APP   # GTK3-Wayland can't prove 'same app' for its own drags (drop was refused)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify'))
import osbnotify as N
HERE = os.path.dirname(os.path.abspath(__file__)); CFG = os.path.join(HERE, '..')
P = N.palette(); MODE = sys.argv[1] if len(sys.argv) > 1 else 'overview'
PID = f'/tmp/osb-wm-{MODE}.pid'
if os.path.exists(PID):
    try: os.kill(int(open(PID).read()), 15); os.remove(PID); sys.exit(0)  # toggle
    except Exception: os.remove(PID)
open(PID, 'w').write(str(os.getpid()))

CSS = f'''
* {{ font-family: Roboto; }}
.desk {{ background: alpha({P['SURFACE']}, 0.85); color: {P['ON_SURFACE']}; border-radius: 12px; border: 2px solid transparent; padding: 6px; }}
.desk.current {{ border-color: {P['ACCENT']}; }}
.desk.drop {{ border-color: {P['ACCENT']}; background: alpha({P['ACCENT_CONTAINER']}, 0.95); }}
.desk label {{ font-size: 12px; font-weight: 500; }}
.newdesk {{ background: alpha({P['SURFACE']}, 0.85); color: {P['ON_SURFACE']}; border-radius: 12px; border: none; box-shadow: none; padding: 6px 14px; font-weight: 500; }}
.wincard {{ background: transparent; border: 2px solid transparent; border-radius: 16px; padding: 6px; }}
.wincard.sel {{ border-color: {P['ACCENT']}; background: alpha({P['ACCENT_CONTAINER']}, 0.35); }}
.wintitle {{ color: #ffffff; font-weight: 500; font-size: 13px; }}
.x {{ background: alpha({P['SURFACE']}, 0.9); border: none; box-shadow: none; border-radius: 14px; min-width: 28px; min-height: 28px; padding: 0; color: {P['ON_SURFACE']}; }}
.thumbph {{ background: {P['SURFACE_VARIANT']}; border-radius: 12px; }}
.strip {{ background: {P['SURFACE']}; border-radius: 24px; padding: 14px; }}
.strip .wintitle {{ color: {P['ON_SURFACE']}; }}
.empty {{ color: #ffffff; font-size: 16px; }}
'''

def wallpaper():
    wp = os.path.join(CFG, 'wallpaper.png')
    return wp if os.path.exists(wp) else os.path.join(CFG, 'wallpapers', 'polderheuvel.png')

def rounded_pixbuf(path, radius=12):
    """Return a Gtk.Image of path with rounded corners (alpha mask via ImageMagick)."""
    out = path.replace('.png', '-r.png')
    subprocess.run(['convert', path, '(', '+clone', '-alpha', 'extract', '-draw',
        f'fill black polygon 0,0 0,{radius} {radius},0 fill white circle {radius},{radius} {radius},0',
        '(', '+clone', '-flip', ')', '-compose', 'Multiply', '-composite',
        '(', '+clone', '-flop', ')', '-compose', 'Multiply', '-composite', ')',
        '-alpha', 'off', '-compose', 'CopyOpacity', '-composite', out])
    return Gtk.Image.new_from_file(out)

class Base(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL if WAY else Gtk.WindowType.POPUP); RGBA.enable(self)
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        prov = Gtk.CssProvider(); prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(scr, prov, 800)
        self.connect('key-press-event', self.on_key); self.connect('key-release-event', self.on_key_release)
        self.connect('destroy', self.quit)

    def grab(self):
        """Grab keyboard+pointer so we receive Tab/Alt release/Escape (retry until WM releases)."""
        if WAY: return   # exclusive keyboard on the layer surface; the compositor skips its bindings while we hold it
        seat = Gdk.Display.get_default().get_default_seat()
        def try_grab():
            st = seat.grab(self.get_window(), Gdk.SeatCapabilities.KEYBOARD | Gdk.SeatCapabilities.POINTER, True, None, None, None)
            return st != Gdk.GrabStatus.SUCCESS  # repeat until success
        GLib.timeout_add(30, try_grab)

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.quit()
    def on_key_release(self, w, e): pass

    def quit(self, *a):
        try: os.remove(PID)
        except Exception: pass
        Gtk.main_quit()

class Overview(Base):
    def __init__(self):
        super().__init__()
        bg = '/tmp/osb-wm/overview-bg.png'; os.makedirs('/tmp/osb-wm', exist_ok=True)
        subprocess.run(['convert', wallpaper(), '-resize', f'{self.sw}x{self.sh}!',
                        '-blur', '0x12', '-fill', 'black', '-colorize', '45%', bg])
        self.set_name('ov'); self.move(0, 0); self.set_size_request(self.sw, self.sh - 52)  # keep shelf visible
        if WAY: LSH.setup(self, 'polder-overview', layer='overlay', anchors=('left', 'right', 'top', 'bottom'), margins={'bottom': SHELF}, exclusive=-1, keyboard='exclusive')
        p = Gtk.CssProvider(); p.load_from_data(f"#ov {{ background-image: url('{bg}'); }}".encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, 900)
        if WAY and RGBA.active(self):   # the RGBA clear wipes the CSS background: paint the dimmed wallpaper ourselves
            from gi.repository import GdkPixbuf
            self._bgpb = GdkPixbuf.Pixbuf.new_from_file(bg)
            self.connect('draw', lambda w, cr: (Gdk.cairo_set_source_pixbuf(cr, self._bgpb, 0, 0), cr.paint(), False)[-1])
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24); root.set_margin_top(18); self.add(root)
        root.pack_start(self.desk_bar(), False, False, 0)
        wins = WL.windows()
        if not wins:
            l = Gtk.Label(label='Geen vensters op dit bureau'); l.get_style_context().add_class('empty')
            root.pack_start(l, True, True, 0)
        else:
            root.pack_start(self.grid(wins), True, True, 0)
        self.show_all(); self.grab()
        # click on empty backdrop exits
        self.connect('button-release-event', lambda w, e: self.quit() if e.button == 1 else None)

    def desk_bar(self):
        bar = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER); cur = WL.current_desk(); self.desk_evs = []
        for d in range(WL.desks()):
            ev = Gtk.EventBox(); box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.get_style_context().add_class('desk')
            if d == cur: box.get_style_context().add_class('current')
            mini = Gtk.Image.new_from_file(self.desk_mini(d)); box.pack_start(mini, False, False, 0)
            lr = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER); lr.pack_start(Gtk.Label(label=f'Bureau {d + 1}'), False, False, 0)
            if WL.desks() > 1 and (WAY or d == WL.desks() - 1):   # Rev 34h: remove desk (its windows go to the neighbour desk)
                xb = Gtk.Button(); xb.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); xb.get_style_context().add_class('x')
                xb.set_tooltip_text('Bureau verwijderen'); xb.connect('clicked', lambda *_, d=d: self.del_desk(d)); lr.pack_start(xb, False, False, 0)
            box.pack_start(lr, False, False, 0)
            ev.add(box); ev.connect('button-release-event', lambda w, e, d=d: self.switch(d)); self.desk_evs.append((ev, box))
            # drop target: move a dragged window to this desk
            ev.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new('osb-win', DNDFLAG, 0)], Gdk.DragAction.MOVE)
            ev.connect('drag-data-received', lambda w, c, x, y, data, i, t, d=d: self.move_to(int(data.get_text()), d))
            bar.pack_start(ev, False, False, 0)
        nb = Gtk.Button(label='+  Nieuw bureau'); nb.get_style_context().add_class('newdesk'); nb.set_valign(Gtk.Align.CENTER)
        nb.connect('clicked', self.new_desk); bar.pack_start(nb, False, False, 0)
        return bar

    def desk_mini(self, d):
        out = f'/tmp/osb-wm/desk{d}.png'
        if WAY:   # real miniature: wallpaper + that desk's windows at their positions (compositor thumbnails)
            from gi.repository import GdkPixbuf
            mw, mh = 128, 72; k = mw / self.sw
            base = GdkPixbuf.Pixbuf.new_from_file_at_scale(wallpaper(), mw, mh, False)
            for w in reversed([w for w in WL.desk_windows(d) if not w['hidden']]):
                x, y, ww, hh = w['geom']; tw, th = max(1, int(ww * k)), max(1, int(hh * k))
                tp = WL.thumb(w, tw, th)
                if not tp: continue
                t = GdkPixbuf.Pixbuf.new_from_file(tp); cx, cy = int(x * k), int(y * k)
                cw, ch = min(t.get_width(), mw - cx), min(t.get_height(), mh - cy)
                if cx < 0 or cy < 0 or cw <= 0 or ch <= 0: continue
                t.composite(base, cx, cy, cw, ch, cx, cy, 1, 1, GdkPixbuf.InterpType.BILINEAR, 255)
            base.savev(out, 'png', [], []); return out
        subprocess.run(['convert', wallpaper(), '-resize', '128x72!', out]); return out

    def grid(self, wins):
        n = len(wins); cols = min(n, 3 if n > 4 else max(1, min(n, 2 if n <= 4 else 3)))
        cols = {1: 1, 2: 2, 3: 3, 4: 2}.get(n, 3); rows = math.ceil(n / cols)
        avail_w, avail_h = self.sw - 160, self.sh - 52 - 200
        tw = min(460, avail_w // cols - 40); th = min(int(tw * 0.62), avail_h // rows - 60)
        g = Gtk.Grid(column_spacing=32, row_spacing=24, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        for i, w in enumerate(wins):
            g.attach(self.card(w, tw, th), i % cols, i // cols, 1, 1)
        return g

    def card(self, w, tw, th):
        ev = Gtk.EventBox(); box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.get_style_context().add_class('wincard')
        hdr = Gtk.Box(spacing=8)
        hdr.pack_start(Gtk.Image.new_from_icon_name(w['icon'], Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        t = Gtk.Label(label=w['title'] or w['app'], xalign=0); t.set_ellipsize(Pango.EllipsizeMode.END); t.set_max_width_chars(30)
        t.get_style_context().add_class('wintitle'); hdr.pack_start(t, True, True, 0)
        x = Gtk.Button(); x.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); x.get_style_context().add_class('x')
        x.set_tooltip_text('Sluiten'); x.connect('clicked', lambda *_: (WL.close(w['id']), self.quit())); hdr.pack_end(x, False, False, 0)
        box.pack_start(hdr, False, False, 0)
        tp = WL.thumb(w, tw, th)
        if tp: img = rounded_pixbuf(tp)
        else:
            img = Gtk.Box(); img.get_style_context().add_class('thumbph'); img.set_size_request(tw, th)
            ic = Gtk.Image.new_from_icon_name(w['icon'], Gtk.IconSize.DIALOG); ic.set_pixel_size(64); img.set_center_widget(ic)
        box.pack_start(img, False, False, 0); ev.add(box)
        ev.connect('enter-notify-event', lambda *_: box.get_style_context().add_class('sel'))
        ev.connect('leave-notify-event', lambda *_: box.get_style_context().remove_class('sel'))
        if WAY:   # GTK3's in-process Wayland DnD never asks for the data (drop -> leave -> cancelled), so drag by hand:
            # press on a card, move over a desk (it lights up), release = move the window there; a plain click = activate
            ev.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_MOTION_MASK)
            ev.connect('button-press-event', lambda wd, e: setattr(self, '_press', (w['id'], e.x_root, e.y_root)) if e.button == 1 else None)
            ev.connect('motion-notify-event', lambda wd, e: self.drag_hover(e))
            ev.connect('button-release-event', lambda wd, e: self.card_release(w['id'], e) if e.button == 1 else None)
            return ev
        ev.connect('button-release-event', lambda wd, e: self.pick(w['id']) if e.button == 1 else None)
        ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new('osb-win', DNDFLAG, 0)], Gdk.DragAction.MOVE)
        ev.connect('drag-data-get', lambda wd, c, data, i, t: data.set_text(str(w['id']), -1))
        return ev

    def pick(self, wid): WL.activate(wid); self.quit(); return True

    def desk_at(self, x, y):
        for d, (ev, box) in enumerate(self.desk_evs):
            ox, oy = ev.translate_coordinates(self, 0, 0); a = ev.get_allocation()
            if ox <= x < ox + a.width and oy <= y < oy + a.height: return d
        return None

    def drag_hover(self, e):
        p = getattr(self, '_press', None)
        if not p or not (e.state & Gdk.ModifierType.BUTTON1_MASK): return
        d = self.desk_at(e.x_root, e.y_root)
        for i, (ev, box) in enumerate(self.desk_evs): (box.get_style_context().add_class if i == d else box.get_style_context().remove_class)('drop')

    def card_release(self, wid, e):
        p = getattr(self, '_press', None); self._press = None
        if not p: return True
        d = self.desk_at(e.x_root, e.y_root)
        if d is not None: self.move_to(wid, d)
        elif abs(e.x_root - p[1]) < 10 and abs(e.y_root - p[2]) < 10: self.pick(wid)
        else:
            for ev, box in self.desk_evs: box.get_style_context().remove_class('drop')
        return True
    def switch(self, d):
        if WAY: WL.switch_desk(d)
        else: subprocess.run(['wmctrl', '-s', str(d)])
        self.quit(); return True
    def move_to(self, wid, d):
        if WAY: WL.move_to_desk(wid, d)
        else: subprocess.run(['wmctrl', '-i', '-r', hex(wid), '-t', str(d)])
        self.quit()
    def del_desk(self, d):
        if WAY: WL.wl_cmd(f'deldesk {d}')
        else: subprocess.run(['wmctrl', '-n', str(WL.desks() - 1)])   # xfwm4 only removes the last desk; its windows move left
        self.quit(); return True
    def new_desk(self, *a):
        if WAY: WL.new_desk(); self.quit(); return
        n = WL.desks(); subprocess.run(['wmctrl', '-n', str(n + 1)]); subprocess.run(['wmctrl', '-s', str(n)]); self.quit()

class AltTab(Base):
    def __init__(self):
        super().__init__()
        self.wins = WL.windows()
        if len(self.wins) == 0: self.quit(); return
        self.sel = 1 if len(self.wins) > 1 else 0
        if 'back' in sys.argv[2:]: self.sel = len(self.wins) - 1
        self.cards = []
        tw, th = 220, 140
        strip = Gtk.Box(spacing=12); strip.get_style_context().add_class('strip')
        for w in self.wins:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); box.get_style_context().add_class('wincard')
            hdr = Gtk.Box(spacing=6); hdr.pack_start(Gtk.Image.new_from_icon_name(w['icon'], Gtk.IconSize.MENU), False, False, 0)
            t = Gtk.Label(label=w['title'] or w['app'], xalign=0); t.set_ellipsize(Pango.EllipsizeMode.END); t.set_max_width_chars(22)
            t.get_style_context().add_class('wintitle'); hdr.pack_start(t, True, True, 0); box.pack_start(hdr, False, False, 0)
            tp = WL.thumb(w, tw, th)
            if tp: img = rounded_pixbuf(tp, 10)
            else:
                img = Gtk.Box(); img.get_style_context().add_class('thumbph'); img.set_size_request(tw, th)
                ic = Gtk.Image.new_from_icon_name(w['icon'], Gtk.IconSize.DIALOG); img.set_center_widget(ic)
            box.pack_start(img, False, False, 0); strip.pack_start(box, False, False, 0); self.cards.append(box)
        self.set_name('at'); self.add(strip); strip.show_all()
        if WAY:   # a GtkBox doesn't paint its CSS background here (window is cleared to transparent): render it ourselves
            strip.connect('draw', lambda w, cr: (Gtk.render_background(w.get_style_context(), cr, 0, 0, w.get_allocated_width(), w.get_allocated_height()), False)[-1])
        if WAY: LSH.setup(self, 'polder-alttab', layer='overlay', anchors=(), exclusive=-1, keyboard='exclusive')   # centred by the compositor
        W = strip.get_preferred_width()[1]; H = strip.get_preferred_height_for_width(W)[1]
        self.set_size_request(W, H); self.resize(W, H); self.show_all()
        x, y = (self.sw - W) // 2, (self.sh - 52 - H) // 2; self.move(x, y)
        if WAY:   # Alt may be released before we even mapped (python start-up): poll the real modifier state
            p = Gtk.CssProvider(); p.load_from_data(b"#at { background: transparent; background-image: none; }")
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, 900)
            self.update(); GLib.timeout_add(120, self.poll_alt); return
        bg = '/tmp/osb-wm/alttab-bg.png'
        # backdrop = actual screen region behind the strip (so rounded corners show windows, not black)
        if not RGBA.active(self): subprocess.run(['import', '-silent', '-window', 'root', '-crop', f'{W}x{H}+{x}+{y}', '+repage', bg], timeout=10)
        p = Gtk.CssProvider(); p.load_from_data(("#at { background: transparent; background-image: none; }" if RGBA.active(self) else f"#at {{ background-image: url('{bg}'); }}").encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, 900)
        self.update(); self.grab()

    def poll_alt(self):
        km = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        if km.get_modifier_state() & Gdk.ModifierType.MOD1_MASK: return True
        WL.activate(self.wins[self.sel]['id']); self.quit(); return False

    def update(self):
        for i, c in enumerate(self.cards):
            (c.get_style_context().add_class if i == self.sel else c.get_style_context().remove_class)('sel')

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.quit()
        elif e.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Right, Gdk.KEY_Left):
            back = e.keyval in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Left) or (e.state & Gdk.ModifierType.SHIFT_MASK)
            self.sel = (self.sel + (-1 if back else 1)) % len(self.cards); self.update()

    def on_key_release(self, w, e):
        if e.keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L):
            WL.activate(self.wins[self.sel]['id']); self.quit()

    def quit(self, *a):
        super().quit()

class SplitPick(Overview):
    """After snapping one window to a side, show the other windows on the other half (ChromeOS split view)."""
    def __init__(self, snapped_side):
        Base.__init__(self)
        import snap as SN
        self.other = 'right' if snapped_side == 'left' else 'left'
        x, y, w, h = SN.geom(self.other); self.sw = w  # grid() uses self.sw/self.sh
        self.snapped = SN.active()
        wins = [wn for wn in WL.windows() if wn['id'] != self.snapped]
        if not wins: self.quit(); return
        bg = f'/tmp/osb-wm/split-{self.other}.png'; os.makedirs('/tmp/osb-wm', exist_ok=True)
        subprocess.run(['convert', wallpaper(), '-crop', f'{w}x{h}+{x}+{y}', '+repage',
                        '-blur', '0x12', '-fill', 'black', '-colorize', '45%', bg], timeout=10)
        self.set_name('ov'); self.move(x, y); self.set_size_request(w, h)
        p = Gtk.CssProvider(); p.load_from_data(f"#ov {{ background-image: url('{bg}'); }}".encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), p, 900)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); root.set_margin_top(24); self.add(root)
        l = Gtk.Label(label='Kies een venster voor deze helft'); l.get_style_context().add_class('empty'); root.pack_start(l, False, False, 0)
        root.pack_start(self.grid(wins), True, True, 0)
        self.show_all(); self.grab()
        self.connect('button-release-event', lambda w, e: self.quit() if e.button == 1 else None)

    def pick(self, wid):
        subprocess.run([sys.executable, os.path.join(HERE, 'snap.py'), self.other, str(wid)], timeout=10); self.quit(); return True

if __name__ == '__main__':
    if MODE.startswith('split-'): SplitPick(MODE.split('-')[1])
    else: (AltTab if MODE == 'alttab' else Overview)()
    Gtk.main()
