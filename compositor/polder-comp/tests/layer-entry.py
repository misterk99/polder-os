#!/usr/bin/env python3
"""Rev 33 test client: a layer-shell panel (top layer, keyboard on_demand) with a text entry, to verify that clicking
a panel gives it keyboard focus in polder-comp. Prints every text change to stdout."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'config', 'osb'))
import gi; gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import layershell as LSH
w = Gtk.Window(title='layer-entry'); w.set_size_request(360, 60)
ok = LSH.setup(w, 'polder-test-entry', layer='top', anchors=('top', 'right'), margins={'top': 20, 'right': 20}, exclusive=0, keyboard='on_demand')
e = Gtk.Entry(placeholder_text='klik hier en typ'); e.set_margin_start(12); e.set_margin_end(12); e.set_margin_top(12); e.set_margin_bottom(12)
e.connect('changed', lambda en: print('text:', en.get_text(), flush=True)); w.add(e)
w.connect('destroy', Gtk.main_quit); w.show_all(); print('layer-shell:', ok, flush=True); Gtk.main()
