#!/usr/bin/env python3
"""'Welkom bij Polder OS' first-run tour (Revision 24). Runs on first login (settings 'welcome_done' false) and on demand
(Instellingen > Over, launcher 'welkom'). All changes go through the same code paths as Instellingen:
osbsettings.update() (osb-settingsd applies them live), feeds.valid_url/add/sync, shortcut_table.KEYD."""
import os, sys, threading, subprocess, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify', 'calendar', 'wm'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango
import osbsettings as S, osbnotify as N, feeds, shortcut_table as T
PID = '/tmp/osb-welkom.pid'
STEPS = ['welkom', 'wifi', 'thema', 'achtergrond', 'agenda', 'sneltoetsen', 'klaar']
KEYNAMES = {'Super_L': 'Super', 'bracketleft': '[', 'bracketright': ']', 'equal': '=', 'minus': '-', 'slash': '/', 'Print': 'Print Screen'}

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#win {{ background: {P['SURFACE']}; color: {P['ON_SURFACE']}; }}
.h1 {{ font-size: 26px; font-weight: 500; }}
.lead {{ font-size: 14px; color: {P['ON_SURFACE_VARIANT']}; }}
.sub {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
.ok {{ color: #188038; font-weight: 500; }} .err {{ color: #d93025; }}
.primary {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; border: none; box-shadow: none; border-radius: 20px; padding: 8px 24px; font-weight: 500; }}
.primary label {{ color: {P['ON_ACCENT']}; }}
.text {{ background: transparent; color: {P['ACCENT']}; border: none; box-shadow: none; border-radius: 20px; padding: 8px 18px; font-weight: 500; }}
.text:hover {{ background: {P['SURFACE_VARIANT']}; }}
.seg {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border: none; box-shadow: none; border-radius: 18px; padding: 8px 20px; }}
.seg:checked, .seg:checked label {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.swatch {{ border-radius: 18px; min-width: 36px; min-height: 36px; border: 3px solid transparent; box-shadow: none; }}
.swatch:checked {{ border-color: {P['ON_SURFACE']}; }}
.wall {{ background: transparent; border: 3px solid transparent; border-radius: 14px; padding: 4px; box-shadow: none; }}
.wall:checked {{ border-color: {P['ACCENT']}; }}
.wall label {{ color: {P['ON_SURFACE']}; }}
.dot {{ background: {P['OUTLINE']}; border-radius: 4px; min-width: 8px; min-height: 8px; }}
.dot.on {{ background: {P['ACCENT']}; min-width: 22px; }}
entry {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border: none; box-shadow: none; border-radius: 12px; padding: 8px 12px; }}
.card {{ background: {P['SURFACE_VARIANT']}; border-radius: 16px; padding: 10px 14px; }}
.kchip {{ background: {P['SURFACE']}; color: {P['ON_SURFACE']}; border-radius: 8px; padding: 3px 10px; font-size: 12px; font-weight: 500; border-bottom: 2px solid {P['OUTLINE']}; }}
list, list row {{ background: transparent; }}
list row {{ border-radius: 12px; padding: 6px 10px; }}
list row:selected {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
'''

def label(text, cls=None, wrap=True, xalign=0.0):
    l = Gtk.Label(label=text, xalign=xalign, wrap=wrap, max_width_chars=70, justify=Gtk.Justification.CENTER if xalign == 0.5 else Gtk.Justification.LEFT)
    if cls: l.get_style_context().add_class(cls)
    return l

class Welkom(Gtk.Window):
    def __init__(self):
        super().__init__(title='Welkom bij Polder OS'); self.set_name('win'); self.set_wmclass('polder-welkom', 'Polder Welkom')
        self.set_default_size(780, 540); self.set_resizable(False); self.set_decorated(False); self.set_position(Gtk.WindowPosition.CENTER)
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.prov, 900)
        self.pal_m = None; self.restyle(); GLib.timeout_add(400, self.restyle)   # live preview: follow palette.env
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); v.set_border_width(32); self.add(v)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=180); v.pack_start(self.stack, True, True, 0)
        for st in STEPS: self.stack.add_named(getattr(self, 'p_' + st)(), st)
        bar = Gtk.Box(spacing=8); v.pack_end(bar, False, False, 0)
        self.dots = []
        for _ in STEPS:
            d = Gtk.Box(); d.get_style_context().add_class('dot'); d.set_valign(Gtk.Align.CENTER); self.dots.append(d); bar.pack_start(d, False, False, 0)
        self.next = Gtk.Button(label='Volgende'); self.next.get_style_context().add_class('primary'); self.next.connect('clicked', lambda *a: self.go(1))
        self.back = Gtk.Button(label='Terug'); self.back.get_style_context().add_class('text'); self.back.connect('clicked', lambda *a: self.go(-1))
        self.skip = Gtk.Button(label='Overslaan'); self.skip.get_style_context().add_class('text'); self.skip.connect('clicked', lambda *a: self.finish())
        bar.pack_end(self.next, False, False, 0); bar.pack_end(self.back, False, False, 0); bar.pack_end(self.skip, False, False, 0)
        self.i = 0; self.connect('key-press-event', self.on_key); self.connect('destroy', self.quit)
        self.show_all(); self.go(0)

    def restyle(self):
        try: m = os.path.getmtime(os.path.join(C, 'palette.env'))
        except OSError: return True
        if m != self.pal_m: self.pal_m = m; self.prov.load_from_data(css().encode())
        return True

    def go(self, d):
        if self.i + d >= len(STEPS): self.finish(); return
        self.i = max(0, self.i + d); self.stack.set_visible_child_name(STEPS[self.i])
        for k, dot in enumerate(self.dots):
            (dot.get_style_context().add_class if k == self.i else dot.get_style_context().remove_class)('on')
        last = self.i == len(STEPS) - 1
        self.next.set_label('Aan de slag' if last else 'Volgende'); self.back.set_visible(self.i > 0); self.skip.set_visible(not last)

    def on_key(self, w, e):
        if e.keyval == Gdk.KEY_Escape: self.finish()

    def finish(self):
        S.update(welcome_done=True); self.destroy()

    def quit(self, *a):
        try: os.remove(PID)
        except OSError: pass
        Gtk.main_quit()

    def page(self, title, lead):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        b.pack_start(label(title, 'h1'), False, False, 0); b.pack_start(label(lead, 'lead'), False, False, 0)
        return b

    # 1 -------------------------------------------------------------------------------------------
    def p_welkom(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER)
        b.pack_start(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(C, 'brand', 'polderos-logo.png'), 72, 72, True)), False, False, 0)
        b.pack_start(label('Welkom bij Polder OS', 'h1', xalign=0.5), False, False, 0)
        b.pack_start(label('Een ChromeOS-achtige desktop op Debian. In een paar stappen zetten we alles voor je klaar.', 'lead', xalign=0.5), False, False, 0)
        th = S.wallpaper_thumb('polderheuvel', 400, 225)
        if th:
            pb = GdkPixbuf.Pixbuf.new_from_file(th); img = Gtk.Image.new_from_pixbuf(pb); b.pack_start(img, False, False, 6)
        return b

    # 2 -------------------------------------------------------------------------------------------
    def p_wifi(self):
        b = self.page('Verbinding maken met wifi', 'Kies een netwerk. Je kunt dit later wijzigen via Snelle instellingen.')
        dev = None
        if shutil.which('nmcli'):
            out = subprocess.run(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device'], capture_output=True, text=True, timeout=10).stdout
            dev = next((l.split(':')[0] for l in out.splitlines() if l.split(':')[1:2] == ['wifi']), None)
        if not dev:
            why = 'NetworkManager (nmcli) is niet geïnstalleerd.' if not shutil.which('nmcli') else 'NetworkManager ziet geen wifi-apparaat.'
            c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); c.get_style_context().add_class('card')
            c.pack_start(label('Geen wifi-adapter gevonden'), False, False, 0); c.pack_start(label(why + ' Een kabelverbinding werkt automatisch; je kunt deze stap overslaan.', 'sub'), False, False, 0)
            b.pack_start(c, False, False, 8); return b
        self.wdev = dev
        lb = Gtk.ListBox(); sw = Gtk.ScrolledWindow(); sw.set_min_content_height(220); sw.add(lb); b.pack_start(sw, True, True, 4)
        out = subprocess.run(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list', 'ifname', dev], capture_output=True, text=True, timeout=20).stdout
        seen = set()
        for l in out.splitlines():
            p = l.split(':')
            if len(p) < 4 or not p[1] or p[1] in seen: continue
            seen.add(p[1]); r = Gtk.Box(spacing=10); r.ssid = p[1]
            r.pack_start(label(('✓ ' if p[0] == '*' else '') + p[1]), True, True, 0); r.pack_start(label(f'{p[2]}% · {p[3] or "open"}', 'sub'), False, False, 0); lb.add(r)
        pw = Gtk.Entry(placeholder_text='Wachtwoord', visibility=False); msg = label('', 'sub')
        cb = Gtk.Button(label='Verbinden'); cb.get_style_context().add_class('primary')
        def connect(*a):
            row = lb.get_selected_row()
            if not row: msg.set_text('Kies eerst een netwerk.'); return
            ssid = row.get_child().ssid; msg.set_text(f'Verbinden met {ssid}…')
            def work():
                cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid, 'ifname', dev] + (['password', pw.get_text()] if pw.get_text() else [])
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                GLib.idle_add(msg.set_text, 'Verbonden met ' + ssid if r.returncode == 0 else 'Mislukt: ' + (r.stderr or r.stdout).strip()[:120])
            threading.Thread(target=work, daemon=True).start()
        cb.connect('clicked', connect)
        h = Gtk.Box(spacing=8); h.pack_start(pw, True, True, 0); h.pack_start(cb, False, False, 0); b.pack_start(h, False, False, 0); b.pack_start(msg, False, False, 0)
        if not seen: b.pack_start(label('Geen netwerken in de buurt gevonden.', 'sub'), False, False, 0)
        return b

    # 3 -------------------------------------------------------------------------------------------
    def exclusive(self, b, group):
        if getattr(self, '_busy', False): return False
        if not b.get_active(): self._busy = True; b.set_active(True); self._busy = False; return False
        self._busy = True
        for o in group:
            if o is not b: o.set_active(False)
        self._busy = False; return True

    def p_thema(self):
        b = self.page('Kies je stijl', 'Licht, donker of automatisch (licht van 07:00 tot 19:00). Je ziet het meteen op je hele bureaublad.')
        s = S.load(); seg = Gtk.Box(spacing=8); g = []
        for k, lab in (('light', 'Licht'), ('dark', 'Donker'), ('auto', 'Automatisch')):
            t = Gtk.ToggleButton(label=lab); t.get_style_context().add_class('seg'); t.set_active(s['theme'] == k)
            t.connect('toggled', lambda w, k=k: self.exclusive(w, g) and S.update(theme=k)); g.append(t); seg.pack_start(t, False, False, 0)
        b.pack_start(label('Thema', 'sub'), False, False, 8); b.pack_start(seg, False, False, 0)
        sw = Gtk.Box(spacing=10); ag = []
        for name in S.ACCENTS:
            t = Gtk.ToggleButton(); t.set_tooltip_text(name.capitalize()); t.get_style_context().add_class('swatch')
            cp = Gtk.CssProvider(); cp.load_from_data(f'.swatch {{ background: {S.ACCENTS[name][0]}; }}'.encode()); t.get_style_context().add_provider(cp, 950)
            t.set_active(s['accent'] == name); t.connect('toggled', lambda w, n=name: self.exclusive(w, ag) and S.update(accent=n)); ag.append(t); sw.pack_start(t, False, False, 0)
        b.pack_start(label('Accentkleur', 'sub'), False, False, 12); b.pack_start(sw, False, False, 0)
        return b

    # 4 -------------------------------------------------------------------------------------------
    def p_achtergrond(self):
        b = self.page('Kies een achtergrond', 'Polderheuvel krijgt in het donkere thema automatisch de avondvariant.')
        fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=6, row_spacing=6); g = []; s = S.load()
        for name in S.WALLPAPERS:
            th = S.wallpaper_thumb(name)
            if not th: continue
            t = Gtk.ToggleButton(); t.get_style_context().add_class('wall'); vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vb.pack_start(Gtk.Image.new_from_file(th), False, False, 0); vb.pack_start(Gtk.Label(label=name.capitalize()), False, False, 0); t.add(vb)
            t.set_active(s['wallpaper'] == name); t.connect('toggled', lambda w, n=name: self.exclusive(w, g) and S.update(wallpaper=n)); g.append(t); fb.add(t)
        b.pack_start(fb, False, False, 6); return b

    # 5 -------------------------------------------------------------------------------------------
    def p_agenda(self):
        b = self.page('Agenda koppelen (optioneel)', 'Plak een iCal-link (https:// of webcal://), bijvoorbeeld van Google Agenda, Outlook of een feestdagenkalender. '
                      'De afspraken verschijnen in de kalender als je op de datum op de plank klikt.')
        self.a_name = Gtk.Entry(placeholder_text='Naam (bijv. Feestdagen)'); self.a_url = Gtk.Entry(placeholder_text='https://… of webcal://….ics')
        add = Gtk.Button(label='Toevoegen'); add.get_style_context().add_class('primary'); self.a_msg = label('', 'sub')
        add.connect('clicked', self.add_feed); self.a_url.connect('activate', self.add_feed)
        h = Gtk.Box(spacing=8); h.pack_start(self.a_url, True, True, 0); h.pack_start(add, False, False, 0)
        b.pack_start(self.a_name, False, False, 6); b.pack_start(h, False, False, 0); b.pack_start(self.a_msg, False, False, 4)
        n = len(S.load()['feeds'])
        if n: b.pack_start(label(f'Al gekoppeld: {n} agenda(\'s). Beheer ze in Instellingen › Agenda.', 'sub'), False, False, 0)
        return b

    def add_feed(self, *a):
        url = self.a_url.get_text().strip(); err = feeds.valid_url(url)
        ctx = self.a_msg.get_style_context(); ctx.remove_class('ok'); ctx.remove_class('err')
        if err: ctx.add_class('err'); self.a_msg.set_text(err); return
        f = feeds.add(self.a_name.get_text().strip() or 'Agenda', url); self.a_msg.set_text('Ophalen…')
        def work():
            st = feeds.sync(f)
            def done():
                if st.get('ok'):
                    ctx.add_class('ok'); self.a_msg.set_text(f"Gekoppeld: {st.get('events', 0)} evenementen" + (f" uit ‘{st['calname']}’" if st.get('calname') else ''))
                    self.a_url.set_text('')
                else:   # keep honest: the feed stays in settings so the user can fix it in Instellingen
                    ctx.add_class('err'); self.a_msg.set_text('Synchroniseren mislukt: ' + str(st.get('error')) + ' (staat in Instellingen › Agenda)')
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    # 6 -------------------------------------------------------------------------------------------
    def p_sneltoetsen(self):
        b = self.page('Handige sneltoetsen', 'Alle sneltoetsen zie je met Ctrl + Alt + /.')
        pop = [sc for sc in T.KEYD if sc['group'] == 'Populair' or 'Populair' in sc.get('also', ())][:6]
        grid = Gtk.Grid(column_spacing=16, row_spacing=8); grid.set_margin_top(8)
        for r, sc in enumerate(pop):
            grid.attach(label(sc['desc']), 0, r, 1, 1)
            keys = Gtk.Box(spacing=4, halign=Gtk.Align.END)
            for k in tuple(sc['mods']) + (sc['sym'],):
                c = Gtk.Label(label=KEYNAMES.get(k, k.upper() if len(k) == 1 else k)); c.get_style_context().add_class('kchip'); keys.pack_start(c, False, False, 0)
            grid.attach(keys, 1, r, 1, 1)
        b.pack_start(grid, False, False, 0); return b

    # 7 -------------------------------------------------------------------------------------------
    def p_klaar(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        b.pack_start(Gtk.Image.new_from_icon_name('emblem-ok-symbolic', Gtk.IconSize.DIALOG), False, False, 0)
        b.pack_start(label('Je bent klaar!', 'h1', xalign=0.5), False, False, 0)
        b.pack_start(label('Tik op Super of klik op het Polder OS-logo linksonder om apps te openen. '
                           'Nieuwe apps vind je in de Polder Store. Deze rondleiding staat in Instellingen › Over.', 'lead', xalign=0.5), False, False, 0)
        return b

if __name__ == '__main__':
    if os.path.exists(PID):
        try: os.kill(int(open(PID).read()), 0); sys.exit(0)      # already open
        except (OSError, ValueError): pass
    if '--first-run' in sys.argv and S.load().get('welcome_done'): sys.exit(0)
    open(PID, 'w').write(str(os.getpid())); Welkom(); Gtk.main()
