#!/usr/bin/env python3
"""Polder OS 'Sneltoetsen' overview (ChromeOS keyboard shortcut viewer). Runs only while open; toggled by Ctrl+Alt+/,
launcher search ('sneltoetsen') and Instellingen > Toetsenbord. Content comes from wm/shortcut_table.py (the table
keyd.py binds from), live xfwm4 bindings, and in-popup keys verified against their handlers."""
import os, sys, signal, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify', 'wm'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango
import osbnotify as N, shortcut_table as T
PID = '/tmp/osb-sneltoetsen.pid'; W, H = 780, 540
NAMES = {'Super_L': 'Super', 'bracketleft': '[', 'bracketright': ']', 'equal': '=', 'minus': '-', 'slash': '/', 'Print': 'Print Screen',
         'Escape': 'Esc', 'Return': 'Enter', 'Delete': 'Delete', 'space': 'Spatie', 'Up': '↑', 'Down': '↓', 'Left': '←', 'Right': '→',
         'Home': 'Home', 'End': 'End', 'Tab': 'Tab'}

def entries():
    out = []
    for sc in T.KEYD:
        keys = tuple(sc['mods']) + (sc['sym'],)
        for g in (sc['group'],) + tuple(sc.get('also', ())):
            out.append(dict(group=g, desc=sc['desc'], keys=keys, src='keyd'))
    for g, d, keys in T.xfwm4_live(): out.append(dict(group=g, desc=d, keys=keys, src='xfwm4'))
    for e in T.INAPP:
        f, tok = e['check']
        try: ok = tok in open(os.path.join(C, f)).read()
        except OSError: ok = False
        if ok: out.append(dict(group=e['group'], desc=e['desc'], keys=e['keys'], alt=e.get('alt'), src='app'))
        else: print('niet getoond (handler mist):', e['desc'], flush=True)
    return out

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#card {{ background: {P['SURFACE']}; border-radius: 24px; border: 1px solid {P['OUTLINE']}; color: {P['ON_SURFACE']}; }}
#nav {{ background: transparent; padding: 12px 8px; }}
#nav row {{ border-radius: 20px; padding: 9px 16px; margin: 1px 0; color: {P['ON_SURFACE']}; }}
#nav row:hover {{ background: {P['SURFACE_VARIANT']}; }}
#nav row:selected, #nav row:selected label {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.title {{ font-size: 18px; font-weight: 500; padding: 18px 20px 6px 22px; }}
#search {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 20px; padding: 6px 14px; color: {P['ON_SURFACE']}; caret-color: {P['ACCENT']}; }}
list {{ background: transparent; }}
.srow {{ padding: 9px 12px; border-bottom: 1px solid {P['SURFACE_VARIANT']}; }}
.sdesc {{ font-size: 14px; }}
.ghead {{ font-size: 12px; font-weight: 500; color: {P['ACCENT']}; padding: 12px 12px 2px 12px; }}
.kchip {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border-radius: 8px; padding: 3px 9px; font-size: 12px; font-weight: 500;
          border-bottom: 2px solid {P['OUTLINE']}; min-width: 14px; }}
.plus {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 12px; }}
.src {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 11px; }}
.empty {{ color: {P['ON_SURFACE_VARIANT']}; padding: 30px; }}
.close {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; min-width: 32px; min-height: 32px; color: {P['ON_SURFACE_VARIANT']}; }}
.close:hover {{ background: {P['SURFACE_VARIANT']}; }}
'''

def chip(k):
    b = Gtk.Box(spacing=4); b.get_style_context().add_class('kchip'); b.set_valign(Gtk.Align.CENTER)
    if k in ('Super', 'Super_L'):   # ChromeOS shows the launcher symbol for Super/Search
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(C, 'brand', 'polderos-logo-64.png'), 14, 14, True)
            b.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
        except Exception: pass
        b.pack_start(Gtk.Label(label='Super'), False, False, 0)
    else:
        b.pack_start(Gtk.Label(label=NAMES.get(k, k.upper() if len(k) == 1 else k)), False, False, 0)
    return b

class Viewer(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Sneltoetsen')
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True); self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_name('swin'); self.set_resizable(False); self.set_size_request(W, H)
        scr = Gdk.Screen.get_default(); sw, sh = scr.get_width(), scr.get_height(); x, y = (sw - W) // 2, (sh - 52 - H) // 2
        bg = '/tmp/osb-sneltoetsen-bg.png'   # rounded corners show the real screen behind (no compositor)
        try: subprocess.run(['import', '-silent', '-window', 'root', '-crop', f'{W}x{H}+{x}+{y}', '+repage', bg], timeout=5, capture_output=True)
        except subprocess.TimeoutExpired: pass
        p = Gtk.CssProvider(); p.load_from_data((css() + f"#swin {{ background-image: url('{bg}'); background-color: transparent; }}").encode())
        Gtk.StyleContext.add_provider_for_screen(scr, p, 850); self.move(x, y)
        self.data = entries()
        card = Gtk.Box(); card.set_name('card'); self.add(card)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); left.set_size_request(220, -1)
        t = Gtk.Label(label='Sneltoetsen', xalign=0); t.get_style_context().add_class('title'); left.pack_start(t, False, False, 0)
        self.nav = Gtk.ListBox(); self.nav.set_name('nav')
        for g in T.GROUPS:
            r = Gtk.ListBoxRow(); r.g = g; r.add(Gtk.Label(label=g, xalign=0)); self.nav.add(r)
        self.nav.connect('row-selected', lambda lb, r: r and self.show_group(r.g)); left.pack_start(self.nav, True, True, 0)
        card.pack_start(left, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); right.set_border_width(16)
        top = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(); self.search.set_name('search'); self.search.set_placeholder_text('Sneltoetsen zoeken'); self.search.set_hexpand(True)
        self.search.connect('search-changed', self.on_search); top.pack_start(self.search, True, True, 0)
        x_ = Gtk.Button(); x_.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); x_.get_style_context().add_class('close')
        x_.connect('clicked', lambda *a: Gtk.main_quit()); top.pack_start(x_, False, False, 0); right.pack_start(top, False, False, 0)
        sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.list = Gtk.ListBox(); self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        sc.add(self.list); right.pack_start(sc, True, True, 0); card.pack_start(right, True, True, 0)
        self.connect('key-press-event', self.on_key); self.connect('destroy', Gtk.main_quit)
        self.show_all(); self.nav.select_row(self.nav.get_row_at_index(0)); self.search.grab_focus()
        GLib.timeout_add(150, lambda: self.present() or False)

    def row(self, e, show_group=False):
        r = Gtk.ListBoxRow(); r.set_activatable(False); b = Gtk.Box(spacing=12); b.get_style_context().add_class('srow')
        d = Gtk.Label(label=e['desc'], xalign=0); d.set_ellipsize(Pango.EllipsizeMode.END); d.get_style_context().add_class('sdesc')
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.pack_start(d, False, False, 0)
        if show_group: s = Gtk.Label(label=e['group'], xalign=0); s.get_style_context().add_class('src'); v.pack_start(s, False, False, 0)
        b.pack_start(v, True, True, 0)
        keys = Gtk.Box(spacing=4)
        for i, k in enumerate(e['keys']):
            if i: p = Gtk.Label(label='+'); p.get_style_context().add_class('plus'); keys.pack_start(p, False, False, 0)
            keys.pack_start(chip(k), False, False, 0)
        if e.get('alt'):
            p = Gtk.Label(label='t/m' if e['keys'] == ('1',) else 'of'); p.get_style_context().add_class('plus'); keys.pack_start(p, False, False, 0)
            for k in e['alt']: keys.pack_start(chip(k), False, False, 0)
        b.pack_end(keys, False, False, 0); r.add(b); return r

    def fill(self, items, grouped=False):
        for c in self.list.get_children(): c.destroy()
        if not items:
            l = Gtk.Label(label='Geen sneltoetsen gevonden'); l.get_style_context().add_class('empty'); self.list.add(l)
        for e in items: self.list.add(self.row(e, show_group=grouped))
        self.list.show_all()

    def show_group(self, g):
        if self.search.get_text(): self.search.set_text('')
        self.fill([e for e in self.data if e['group'] == g])

    def on_search(self, *a):
        q = self.search.get_text().strip().lower()
        if not q:
            r = self.nav.get_selected_row(); self.fill([e for e in self.data if e['group'] == (r.g if r else T.GROUPS[0])]); return
        seen, items = set(), []
        for e in self.data:
            hay = (e['desc'] + ' ' + ' '.join(NAMES.get(k, k) for k in e['keys']) + ' ' + e['group']).lower()
            if all(w in hay for w in q.split()) and (e['desc'], e['keys']) not in seen: seen.add((e['desc'], e['keys'])); items.append(e)
        self.fill(items, grouped=True)

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: Gtk.main_quit(); return True
        return False

if __name__ == '__main__':
    try:   # toggle: second invocation closes the open viewer
        os.kill(int(open(PID).read()), signal.SIGTERM); os.remove(PID); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try: Viewer(); Gtk.main()
    finally:
        try: os.remove(PID)
        except OSError: pass
