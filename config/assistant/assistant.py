#!/usr/bin/env python3
"""Polder Assistent panel (Rev 29). Super+A toggles it (polder-shell module 'assistant'; standalone fallback:
assistant.py --show, SIGUSR1 toggles). Local intents first (offline, no key); anything else goes to the cloud LLM
if one is configured in Instellingen > Assistent, else an honest 'not understood' with examples."""
import os, sys, signal, threading, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in (HERE, os.path.join(C, 'osb'), os.path.join(C, 'notify')): sys.path.insert(0, d)
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0'); gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkX11, Pango
import osbnotify as N, actions as A, intents as I, llm as L
W, H, SHELF = 560, 460, 62
PIDF = '/tmp/osb-assistant.pid'
EXAMPLES = ['Zet donker thema aan', 'Volume op 30%', 'Wat voor weer is het?', 'Open terminal', 'Zoek bestand factuur', 'Maak een screenshot']

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#abox {{ background: {P['SURFACE']}; border-radius: 24px; padding: 16px; color: {P['ON_SURFACE']}; }}
#ahead {{ font-size: 16px; font-weight: 500; }}
.asub {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
#aentry {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 22px; padding: 8px 16px; min-height: 28px; color: {P['ON_SURFACE']}; font-size: 15px; caret-color: {P['ACCENT']}; }}
.bub {{ border-radius: 18px; padding: 10px 14px; font-size: 14px; }}
.bub.me {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.bub.ai {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; }}
.bub.act {{ background: transparent; border: 1px solid {P['OUTLINE']}; color: {P['ON_SURFACE_VARIANT']}; font-size: 12px; }}
.chip {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 12px; color: {P['ON_SURFACE']}; font-size: 12px; }}
.chip:hover {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.btn {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 14px; color: {P['ON_SURFACE']}; }}
.btn.primary {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; }}
scrolledwindow, viewport {{ background: transparent; }}
'''

class Assistant(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title='Polder Assistent')
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True); self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG); self.set_name('awin'); self.set_resizable(False)
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        self.x, self.y = (self.sw - W) // 2, self.sh - SHELF - H
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.prov, 800)
        self.bgprov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.bgprov, 900)
        self.palm = self.wpm = None; self.history = []; self.busy = False; self.modal = False
        self.set_size_request(W, H)
        vis = scr.get_rgba_visual()   # Rev 29.1: real ARGB window -> compositor shows true transparent corners over any window
        self.argb = bool(vis and scr.is_composited())
        if vis: self.set_visual(vis)
        self.set_app_paintable(True); self.connect('draw', self.on_draw)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); box.set_name('abox'); self.add(box)
        hd = Gtk.Box(spacing=8); ic = Gtk.Image.new_from_icon_name('starred-symbolic', Gtk.IconSize.LARGE_TOOLBAR); hd.pack_start(ic, False, False, 0)
        t = Gtk.Label(label='Polder Assistent', xalign=0); t.set_name('ahead'); hd.pack_start(t, False, False, 0)
        self.mode = Gtk.Label(xalign=1); self.mode.get_style_context().add_class('asub'); hd.pack_end(self.mode, False, False, 0)
        box.pack_start(hd, False, False, 0)
        self.sc = Gtk.ScrolledWindow(); self.sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.conv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.conv.set_valign(Gtk.Align.END)
        self.sc.add(self.conv); box.pack_start(self.sc, True, True, 0)
        self.entry = Gtk.Entry(); self.entry.set_name('aentry'); self.entry.set_placeholder_text('Vraag of zeg iets… (bv. "zet wifi uit")')
        self.entry.connect('activate', self.on_send); box.pack_start(self.entry, False, False, 0)
        self.connect('key-press-event', lambda w, e: e.keyval == Gdk.KEY_Escape and self.hide_a())
        self.connect('delete-event', lambda *a: self.hide_a() or True)
        self.connect('focus-out-event', lambda *a: GLib.timeout_add(200, self.maybe_hide))
        box.show_all(); self.welcome()
        GLib.timeout_add(1000, lambda: (self.get_visible() and self.refresh_style()) or True)   # live theme/wallpaper switch

    def refresh_style(self):
        pal = os.path.join(C, 'palette.env'); wp = os.path.join(C, 'wallpaper.png')
        if os.path.getmtime(pal) != self.palm: self.palm = os.path.getmtime(pal); self.prov.load_from_data(css().encode())
        if self.argb: self.bgprov.load_from_data(b'#awin { background: transparent; }')
        elif os.path.exists(wp) and os.path.getmtime(wp) != self.wpm:   # no compositor: fall back to wallpaper backdrop   # wallpaper backdrop = rounded corners without compositor
            self.wpm = os.path.getmtime(wp); out = f'/tmp/osb-assistant-bg-{int(self.wpm)}.png'
            subprocess.run(['convert', wp, '-crop', f'{W}x{H}+{self.x}+{self.y}', '+repage', out], timeout=10)
            self.bgprov.load_from_data(f"#awin {{ background-image: url('{out}'); background-color: transparent; }}".encode())
        cfg = L.config()
        self.mode.set_text(f'{L.PROVIDERS[cfg[0]][0]} · {cfg[1]}' if cfg and cfg[2] else 'Lokaal · geen sleutel')

    def on_draw(self, w, cr):
        import cairo
        if self.argb:
            cr.set_operator(cairo.OPERATOR_SOURCE); cr.set_source_rgba(0, 0, 0, 0); cr.paint(); cr.set_operator(cairo.OPERATOR_OVER)
        return False   # children (#abox: rounded background, radius 24) draw on top

    def welcome(self):
        for c in self.conv.get_children(): c.destroy()
        self.history = []
        self.bubble('ai', 'Hoi! Ik kan je computer bedienen: thema, volume, helderheid, wifi, bluetooth, niet storen, apps, agenda, weer, bestanden zoeken, vergrendelen en schermafbeeldingen.')
        fb = Gtk.FlowBox(); fb.set_selection_mode(Gtk.SelectionMode.NONE); fb.set_max_children_per_line(3)
        for ex in EXAMPLES:
            b = Gtk.Button(label=ex); b.get_style_context().add_class('chip'); b.connect('clicked', lambda _b, t=ex: self.ask(t)); fb.add(b)
        self.conv.pack_start(fb, False, False, 0); fb.show_all()

    def bubble(self, kind, text):
        l = Gtk.Label(label=text, xalign=0); l.set_line_wrap(True); l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR); l.set_max_width_chars(52)
        l.get_style_context().add_class('bub'); l.get_style_context().add_class(kind)
        l.set_halign(Gtk.Align.END if kind == 'me' else Gtk.Align.START)
        self.conv.pack_start(l, False, False, 0); l.show(); GLib.idle_add(self.scroll); return l

    def scroll(self):
        a = self.sc.get_vadjustment(); a.set_value(a.get_upper()); return False

    def toggle(self, *a):
        self.hide_a() if self.get_mapped() else self.show_a(); return True

    def show_a(self):
        scr = self.get_screen(); comp = scr.is_composited() and scr.get_rgba_visual() is not None
        if comp != self.argb: self.argb = comp; self.wpm = None
        self.refresh_style(); self.move(self.x, self.y); self.show()
        self.present_with_time(GdkX11.x11_get_server_time(self.get_window())); self.entry.grab_focus()

    def hide_a(self): self.hide(); return True
    def maybe_hide(self):
        if self.get_visible() and not self.is_active() and not self.modal and not self.busy: self.hide_a()
        return False

    def on_send(self, *a):
        t = self.entry.get_text().strip()
        if t and not self.busy: self.entry.set_text(''); self.ask(t)

    def ask(self, text):
        self.bubble('me', text)
        if text.lower() in ('wis', 'nieuw', 'clear', 'reset'): self.welcome(); return
        hit = I.parse(text)
        if hit: self.local(*hit); return
        cfg = L.config()
        if cfg and cfg[2]: self.cloud(text, cfg); return
        self.bubble('ai', 'Dat begrijp ik lokaal niet. Probeer bv. "volume op 50", "open firefox" of "zoek bestand notities". '
                          'Voor vrije vragen: stel een OpenAI-, Gemini- of Claude-sleutel in via Instellingen › Assistent.')

    def confirm(self, q):
        self.modal = True
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=q)
        d.add_buttons('Annuleren', 0, 'Ja', 1); d.set_keep_above(True); r = d.run(); d.destroy(); self.modal = False; self.present(); return r == 1

    def local(self, name, args):
        q = A.needs_confirm(name, args)
        if q and not self.confirm(q): self.bubble('act', 'Geannuleerd.'); return
        if name in ('screenshot', 'lock_screen', 'open_calendar', 'open_app', 'open_path'): self.hide_a()   # 0.30 VM: panel stayed above newly opened apps
        self.busy = True
        def work():
            r = A.run(name, args); GLib.idle_add(self.done_local, r)
        threading.Thread(target=work, daemon=True).start()
    def done_local(self, r): self.busy = False; self.bubble('ai', r); return False

    def cloud(self, text, cfg):
        self.busy = True; self.history.append({'role': 'user', 'content': text})
        lbl = self.bubble('ai', '…'); buf = ['']
        def on_text(ch):
            buf[0] += ch; GLib.idle_add(lbl.set_text, buf[0]); GLib.idle_add(self.scroll)
        def on_tool(name, args):
            q = A.needs_confirm(name, args)
            if q:
                ev = threading.Event(); ok = [False]
                GLib.idle_add(lambda: (ok.__setitem__(0, self.confirm(q)), ev.set()) and False); ev.wait()
                if not ok[0]: GLib.idle_add(self.bubble, 'act', f'✗ {name} geweigerd'); return 'De gebruiker heeft deze actie geweigerd.'
            r = A.run(name, args); GLib.idle_add(self.bubble, 'act', f'⚙ {name}: {r}'); return r
        def work():
            try: out = L.chat(self.history, on_text, on_tool, cfg); err = None
            except L.LLMError as e: out, err = '', str(e)
            except Exception as e: out, err = '', f'{type(e).__name__}: {e}'
            GLib.idle_add(self.done_cloud, lbl, out, err)
        threading.Thread(target=work, daemon=True).start()
    def done_cloud(self, lbl, out, err):
        self.busy = False
        if err: lbl.set_text(f'{L.PROVIDERS[L.config()[0]][0]} gaf een fout: {err}\nControleer je sleutel in Instellingen › Assistent.'); self.history.pop()
        else:
            if not out: lbl.set_text('Klaar.')
            self.history.append({'role': 'assistant', 'content': out or 'Klaar.'})
        return False

if __name__ == '__main__':
    try: os.kill(int(open(PIDF).read()), signal.SIGUSR1); sys.exit(0)
    except (OSError, ValueError): pass
    open(PIDF, 'w').write(str(os.getpid()))
    w = Assistant(); GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, w.toggle)
    if '--show' in sys.argv: w.show_a()
    Gtk.main()
