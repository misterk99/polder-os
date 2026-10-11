#!/usr/bin/env python3
"""Polder OS clipboard history (ChromeOS Super+V). Resident: watches CLIPBOARD (GTK owner-change / XFIXES),
records text + images (max 10, ~/.cache/osb/clipboard/), skips content flagged by password managers
(x-kde-passwordManagerHint=secret / x-kde-passwordManagerHint). SIGUSR1 toggles the popup; SIGUSR2 clears.
Choosing an item: we take CLIPBOARD ownership with that item (this process stays alive, so paste keeps working),
re-focus the previous window and send Ctrl+V (Ctrl+Shift+V for terminals)."""
import os, sys, json, time, signal, subprocess, hashlib, html
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0'); gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango, GdkX11
import osbsettings as S, osbnotify as N
DIR = os.path.join(S.CACHE, 'clipboard'); IDX = os.path.join(DIR, 'history.json'); MAX = 10; PID = '/tmp/osb-clipd.pid'
SECRET = {'x-kde-passwordManagerHint', 'x-kde-passwordmanagerhint'}
TERMS = {'xfce4-terminal', 'gnome-terminal-server', 'xterm', 'uxterm', 'konsole', 'terminator', 'alacritty', 'kitty'}

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#ccard {{ background: {P['SURFACE']}; border-radius: 16px; border: 1px solid {P['SURFACE_VARIANT']}; padding: 10px; color: {P['ON_SURFACE']}; }}
.chead {{ font-weight: 500; font-size: 13px; padding: 2px 6px 6px 6px; }}
.clear {{ background: transparent; border: none; box-shadow: none; color: {P['ACCENT']}; font-weight: 500; padding: 2px 8px; border-radius: 12px; }}
.clear:hover {{ background: {P['SURFACE_VARIANT']}; }}
list {{ background: transparent; }}
row {{ background: transparent; border-radius: 12px; padding: 6px 8px; color: {P['ON_SURFACE']}; }}
row:hover {{ background: {P['SURFACE_VARIANT']}; }}
row:selected, row:selected label {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.ctext {{ font-size: 13px; }}
.cnum {{ font-size: 11px; color: {P['ON_SURFACE_VARIANT']}; min-width: 14px; }}
.cdel {{ background: transparent; border: none; box-shadow: none; padding: 2px; border-radius: 12px; min-width: 24px; min-height: 24px; color: {P['ON_SURFACE_VARIANT']}; }}
.cdel:hover {{ background: {P['OUTLINE']}; }}
.cempty {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 13px; padding: 14px; }}
'''

class Clip(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Klembord')
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG); self.set_resizable(False); self.set_name('cwin')
        os.makedirs(DIR, exist_ok=True)
        try: self.hist = json.load(open(IDX))
        except Exception: self.hist = []
        scr = Gdk.Screen.get_default(); self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.prov, 800)
        self.bgp = Gtk.CssProvider(); self.get_style_context().add_provider(self.bgp, 900); self.palm = None
        self.cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD); self.cb.connect('owner-change', self.on_owner); self.ours = None
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); self.card.set_name('ccard'); self.add(self.card)
        self.connect('key-press-event', self.on_key); self.connect('focus-out-event', lambda *a: GLib.timeout_add(120, self.maybe_hide))
        self.connect('button-press-event', self.on_press); self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, self.toggle)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR2, lambda *a: (self.clear(), True)[1])
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, lambda *a: Gtk.main_quit() or False)

    # ----- recording -----
    def save(self):
        json.dump(self.hist, open(IDX + '.tmp', 'w')); os.replace(IDX + '.tmp', IDX)
        keep = {h['img'] for h in self.hist if h.get('img')}
        for f in os.listdir(DIR):
            if f.endswith('.png') and os.path.join(DIR, f) not in keep: os.remove(os.path.join(DIR, f))

    def record(self, item):
        self.hist = [h for h in self.hist if h['key'] != item['key']]; self.hist.insert(0, item)
        self.hist = self.hist[:MAX]; self.save(); print('recorded', item['kind'], item.get('text', '')[:30], flush=True)

    def on_owner(self, cb, ev):
        if self.ours: return   # we just set it ourselves
        if not S.load().get('clipboard_history', True): return
        cb.request_targets(self.got_targets)

    def got_targets(self, cb, atoms, *a):
        names = {a.name() for a in (atoms or [])}
        if names & SECRET: print('skipped: password-manager hint', flush=True); return
        if any(n.startswith('image/') for n in names): cb.request_image(self.got_image)
        elif names & {'UTF8_STRING', 'STRING', 'TEXT', 'text/plain', 'text/plain;charset=utf-8'}: cb.request_text(self.got_text)

    def got_text(self, cb, text, *a):
        if not text or not text.strip() or len(text) > 100000: return
        self.record({'kind': 'text', 'text': text, 'key': 't' + hashlib.md5(text.encode()).hexdigest(), 't': time.time()})

    def got_image(self, cb, pb, *a):
        if pb is None: return
        key = 'i' + hashlib.md5(pb.get_pixels()[:65536] + bytes(f'{pb.get_width()}x{pb.get_height()}', 'ascii')).hexdigest()
        path = os.path.join(DIR, key + '.png'); pb.savev(path, 'png', [], [])
        self.record({'kind': 'image', 'img': path, 'w': pb.get_width(), 'h': pb.get_height(), 'key': key, 't': time.time()})

    def clear(self):
        self.hist = []; self.save()
        if self.get_visible(): self.build()

    # ----- popup -----
    def toggle(self, *a):
        if self.get_mapped(): self.hide_c()
        elif S.load().get('clipboard_history', True): self.show_c()
        return True

    def build(self):
        for c in self.card.get_children(): c.destroy()
        hd = Gtk.Box(); l = Gtk.Label(label='Klembord', xalign=0); l.get_style_context().add_class('chead'); hd.pack_start(l, True, True, 0)
        if self.hist:
            b = Gtk.Button(label='Alles wissen'); b.get_style_context().add_class('clear'); b.connect('clicked', lambda *a: self.clear()); hd.pack_end(b, False, False, 0)
        self.card.pack_start(hd, False, False, 0)
        self.list = Gtk.ListBox(); self.list.connect('row-activated', lambda lb, r: self.choose(r.idx)); self.card.pack_start(self.list, False, False, 0)
        if not self.hist:
            e = Gtk.Label(label='Nog niets gekopieerd.\nKopieer tekst of een afbeelding om die hier terug te vinden.', justify=Gtk.Justification.CENTER)
            e.get_style_context().add_class('cempty'); self.card.pack_start(e, False, False, 0)
        for i, h in enumerate(self.hist):
            r = Gtk.ListBoxRow(); r.idx = i; bx = Gtk.Box(spacing=10)
            n = Gtk.Label(label=str(i + 1)); n.get_style_context().add_class('cnum'); bx.pack_start(n, False, False, 0)
            if h['kind'] == 'image' and os.path.exists(h['img']):
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(h['img'], 160, 56, True); bx.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
                s = Gtk.Label(label=f"Afbeelding {h['w']}×{h['h']}", xalign=0); s.get_style_context().add_class('cnum'); bx.pack_start(s, True, True, 0)
            else:
                t = ' '.join(h.get('text', '').split()); l = Gtk.Label(label=t, xalign=0); l.set_ellipsize(Pango.EllipsizeMode.END)
                l.set_max_width_chars(34); l.get_style_context().add_class('ctext'); bx.pack_start(l, True, True, 0)
            d = Gtk.Button(); d.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); d.get_style_context().add_class('cdel')
            d.set_tooltip_text('Verwijderen'); d.connect('clicked', lambda _b, i=i: self.delete(i)); bx.pack_end(d, False, False, 0)
            r.add(bx); self.list.add(r)
        self.card.show_all()
        if self.hist: self.list.select_row(self.list.get_row_at_index(0))

    def delete(self, i):
        del self.hist[i]; self.save(); self.build(); self.place(); return True

    def place(self):
        w, h = 340, self.card.get_preferred_size()[1].height
        scr = Gdk.Screen.get_default(); sw, sh = scr.get_width(), scr.get_height()
        ptr = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
        x = max(8, min(ptr[1] - w // 2, sw - w - 8)); y = ptr[2] + 16
        if y + h > sh - 60: y = max(8, ptr[2] - h - 16)
        self.hide(); bg = '/tmp/osb-clip-bg.png'
        try: subprocess.run(['import', '-silent', '-window', 'root', '-crop', f'{w}x{h}+{x}+{y}', '+repage', bg], timeout=5, capture_output=True)
        except subprocess.TimeoutExpired: pass
        self.bgp.load_from_data(f"#cwin {{ background-image: url('{bg}?{time.time()}'); background-color: transparent; }}".encode().replace(b"?" + str(time.time()).encode(), b''))
        self.bgp.load_from_data(f"#cwin {{ background-image: url('{bg}'); background-color: transparent; }}".encode())
        self.set_size_request(w, h); self.resize(w, h); self.move(x, y); self.show()

    def show_c(self):
        pal = os.path.join(C, 'palette.env')
        if os.path.getmtime(pal) != self.palm: self.palm = os.path.getmtime(pal); self.prov.load_from_data(css().encode())
        out = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True, timeout=3).stdout.strip()
        self.prev = int(out) if out.isdigit() else None
        self.build(); self.place(); self.present_with_time(GdkX11.x11_get_server_time(self.get_window()))
        GLib.timeout_add(150, self.grab)

    def grab(self):
        if self.get_visible(): Gdk.Display.get_default().get_default_seat().grab(self.get_window(), Gdk.SeatCapabilities.ALL_POINTING, True, None, None, None, None)
        return False

    def hide_c(self):
        Gdk.Display.get_default().get_default_seat().ungrab(); self.hide()

    def maybe_hide(self):
        if self.get_visible() and not self.is_active(): self.hide_c()
        return False

    def on_press(self, w, e):
        win = self.get_window(); ox, oy = win.get_origin()[1:]
        if not (ox <= e.x_root < ox + win.get_width() and oy <= e.y_root < oy + win.get_height()): self.hide_c()
        return False

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.hide_c(); return True
        if Gdk.KEY_1 <= e.keyval <= Gdk.KEY_9 and e.keyval - Gdk.KEY_1 < len(self.hist): self.choose(e.keyval - Gdk.KEY_1); return True
        if e.keyval == Gdk.KEY_Delete and self.hist:
            r = self.list.get_selected_row(); r and self.delete(r.idx); return True
        return False

    def choose(self, i):
        h = self.hist[i]; self.ours = True
        if h['kind'] == 'image': self.cb.set_image(GdkPixbuf.Pixbuf.new_from_file(h['img']))
        else: self.cb.set_text(h['text'], -1)
        self.cb.store()
        self.hist.insert(0, self.hist.pop(i)); self.save()
        GLib.timeout_add(300, lambda: setattr(self, 'ours', None) or False)
        self.hide_c(); GLib.timeout_add(120, self.paste)

    def paste(self):
        if not self.prev: return False
        subprocess.run(['xdotool', 'windowactivate', '--sync', str(self.prev)], timeout=3, capture_output=True)
        cls = subprocess.run(['xprop', '-id', str(self.prev), 'WM_CLASS'], capture_output=True, text=True, timeout=3).stdout.lower()
        keys = 'ctrl+shift+v' if any(f'"{t}"' in cls for t in TERMS) else 'ctrl+v'
        subprocess.run(['xdotool', 'key', '--clearmodifiers', keys], timeout=3); print('pasted', keys, flush=True); return False

if __name__ == '__main__':
    try: os.kill(int(open(PID).read()), 0); print('already running'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    Clip(); Gtk.main()
