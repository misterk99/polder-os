"""Rounded ChromeOS-style context menu (Polder OS). No compositor: the window's background is a grab of the
screen area underneath, so the rounded card's corners show what's really behind it (no black edges).
PopMenu(items, x, y, anchor='above'|'below', on_close=None); items = [(icon or None, label, callback or None)] or None = separator."""
import os, sys, subprocess, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify'))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'osb')); import rgba as RGBA   # Rev 29.2: real rounded corners
import osbnotify as N
import layershell as LSH   # Rev 33: on polder-comp the menu is an overlay layer surface

_prov = None
def _style():
    global _prov
    P = N.palette()
    css = f'''
#pmcard {{ background: {P['SURFACE']}; border-radius: 14px; border: 1px solid {P['SURFACE_VARIANT']}; padding: 6px 0; font-family: Roboto; }}
.pmitem {{ background: transparent; border: none; box-shadow: none; border-radius: 0; padding: 7px 16px; color: {P['ON_SURFACE']}; }}
.pmitem:hover {{ background: {P['SURFACE_VARIANT']}; }}
.pmitem:disabled label {{ color: {P['ON_SURFACE_VARIANT']}; }}
.pmitem image {{ color: {P['ON_SURFACE_VARIANT']}; }}
.pmtitle {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 12px; font-weight: 500; padding: 4px 16px 6px 16px; }}
.pmsep {{ background: {P['SURFACE_VARIANT']}; min-height: 1px; margin: 4px 0; }}
'''
    scr = Gdk.Screen.get_default()
    if _prov is None: _prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, _prov, 950)
    _prov.load_from_data(css.encode())

class PopMenu(Gtk.Window):
    def __init__(self, items, x, y, anchor='above', title=None, on_close=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL if LSH.wayland() else Gtk.WindowType.POPUP); _style(); self.on_close = on_close; self.closed = False
        self.set_name('pmwin'); RGBA.enable(self)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); card.set_name('pmcard'); card.set_size_request(210, -1)
        self.add(card)
        if title:
            t = Gtk.Label(label=title, xalign=0); t.get_style_context().add_class('pmtitle'); card.pack_start(t, False, False, 0)
        for it in items:
            if it is None:
                s = Gtk.Box(); s.get_style_context().add_class('pmsep'); card.pack_start(s, False, False, 0); continue
            icon, label, cb = it
            b = Gtk.Button(); b.get_style_context().add_class('pmitem'); bx = Gtk.Box(spacing=12)
            if icon: im = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU); im.set_pixel_size(16)
            else: im = Gtk.Box(); im.set_size_request(16, 16)   # aligned empty slot (no broken-icon glyph)
            bx.pack_start(im, False, False, 0)
            bx.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0); b.add(bx)
            if cb: b.connect('clicked', lambda _b, cb=cb: (self.close(), cb()))
            else: b.set_sensitive(False)
            card.pack_start(b, False, False, 0)
        card.show_all(); w, h = card.get_preferred_size()[1].width, card.get_preferred_size()[1].height
        scr = Gdk.Screen.get_default(); sw, sh = scr.get_width(), scr.get_height()
        if anchor == 'above': y = y - h
        x = max(6, min(x, sw - w - 6)); y = max(6, min(y, sh - h - 6))
        bg = f'/tmp/osb-pm-{os.getpid()}.png'
        try: RGBA.active(self) or subprocess.run(['import', '-silent', '-window', 'root', '-crop', f'{w}x{h}+{x}+{y}', '+repage', bg], timeout=5, capture_output=True)
        except subprocess.TimeoutExpired: pass
        self.bgp = Gtk.CssProvider(); self.bgp.load_from_data(b'#pmwin { background: transparent; background-image: none; }' if RGBA.active(self) else f"#pmwin {{ background-image: url('{bg}'); background-color: {N.palette()['SURFACE']}; }}".encode())
        self.get_style_context().add_provider(self.bgp, 960)
        if LSH.setup(self, 'polder-menu', layer='overlay', anchors=('left', 'top'), margins={'left': x, 'top': y}, exclusive=0, keyboard='on_demand'):
            # no seat grab on Wayland: close when focus moves elsewhere (another window/panel clicked) or on Escape
            self.resize(w, h); self.show_all(); self.connect('focus-out-event', lambda *a: GLib.timeout_add(80, self.close) and False)
        else:
            self.move(x, y); self.resize(w, h); self.show_all(); GLib.timeout_add(60, self.grab)
        self.connect('button-press-event', self.on_press); self.connect('key-press-event', self.on_key)

    def grab(self):
        if self.closed: return False
        st = Gdk.Display.get_default().get_default_seat().grab(self.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        return st != Gdk.GrabStatus.SUCCESS and not self.closed

    def on_press(self, w, e):
        win = self.get_window(); ox, oy = win.get_origin()[1:]
        if not (ox <= e.x_root < ox + win.get_width() and oy <= e.y_root < oy + win.get_height()): self.close()
        return False

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.close(); return True
        return False

    def close(self):
        if self.closed: return False
        self.closed = True; Gdk.Display.get_default().get_default_seat().ungrab(); self.destroy()
        if self.on_close: GLib.idle_add(self.on_close)
