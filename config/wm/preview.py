#!/usr/bin/env python3
"""Snap preview: rounded accent-container rectangle for side left|right|max; runs until killed.
Rounded corners without compositor: window background = wallpaper crop, inner box is the rounded fill."""
import os, sys, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify'))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk
import osbnotify as N
P = N.palette(); CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
side = sys.argv[1]; M = 8; SW, WA = 1366, 716
x, y, w, h = {'left': (M, M, SW // 2 - 2 * M, WA - 2 * M), 'right': (SW // 2 + M, M, SW // 2 - 2 * M, WA - 2 * M),
              'max': (M, M, SW - 2 * M, WA - 2 * M)}[side]
bg = f'/tmp/osb-wm/preview-{side}.png'; os.makedirs('/tmp/osb-wm', exist_ok=True)
if not os.path.exists(bg):
    subprocess.run(['convert', os.path.join(CFG, 'wallpaper.png'), '-crop', f'{w}x{h}+{x}+{y}', '+repage', bg], timeout=10)
css = f"""#pv {{ background-image: url('{bg}'); }}
#fill {{ background: alpha({P['ACCENT_CONTAINER']}, 0.9); border: 3px solid {P['ACCENT']}; border-radius: 20px; }}"""
prov = Gtk.CssProvider(); prov.load_from_data(css.encode())
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, 900)
win = Gtk.Window(type=Gtk.WindowType.POPUP); win.set_name('pv'); win.move(x, y); win.set_size_request(w, h)
box = Gtk.Box(); box.set_name('fill'); win.add(box); win.show_all()
win.connect('destroy', Gtk.main_quit); Gtk.main()
