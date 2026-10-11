#!/usr/bin/env python3
"""Polder OS 'Instellingen' (ChromeOS Settings style, GTK3). Writes ~/.config/osb/settings.json;
osb-settingsd.py applies changes live. usage: instellingen.py [personalisatie|meldingen|agenda|toetsenbord|datum|over]"""
import os, sys, time, threading, uuid, subprocess, platform, datetime, signal
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify', 'calendar'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango, Gio
sys.path.insert(0, os.path.join(C, 'weather')); sys.path.insert(0, os.path.join(C, 'webapps'))
import osbsettings as S, osbnotify as N, feeds
PID = '/tmp/osb-settings.pid'
if os.path.exists(PID):   # single instance: raise the existing window (and switch section)
    try:
        os.kill(int(open(PID).read()), 0)
        if len(sys.argv) > 1: open('/tmp/osb-settings.section', 'w').write(sys.argv[1])
        subprocess.run(['wmctrl', '-a', 'Instellingen'], timeout=5); sys.exit(0)
    except (ProcessLookupError, ValueError): pass
open(PID, 'w').write(str(os.getpid()))

SECTIONS = [('personalisatie', 'preferences-desktop-wallpaper-symbolic', 'Personalisatie'),
            ('meldingen', 'preferences-system-notifications-symbolic', 'Meldingen'),
            ('agenda', 'x-office-calendar-symbolic', 'Agenda'),
            ('toetsenbord', 'input-keyboard-symbolic', 'Toetsenbord en taal'),
            ('datum', 'preferences-system-time-symbolic', 'Datum en tijd'),
            ('weer', 'weather-few-clouds-symbolic', 'Weer'),
            ('webapps', 'web-browser-symbolic', 'Webapps'),
            ('over', 'help-about-symbolic', 'Over Polder OS')]
FEED_COLORS = [('Blauw', '#0b57d0'), ('Groen', '#188038'), ('Rood', '#d93025'), ('Oranje', '#e8710a'), ('Paars', '#9334e6'), ('Grijs', '#5f6368')]

def css():
    P = N.palette()
    return f'''
* {{ font-family: Roboto; }}
#root, #content {{ background: {P['SURFACE']}; color: {P['ON_SURFACE']}; }}
#nav {{ background: {P['SURFACE']}; padding: 8px 12px 8px 0; }}
#nav row {{ border-radius: 0 24px 24px 0; padding: 10px 18px 10px 24px; color: {P['ON_SURFACE']}; background: transparent; }}
#nav row:hover {{ background: {P['SURFACE_VARIANT']}; }}
#nav row:selected, #nav row:selected label, #nav row:selected image {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; }}
.apptitle {{ font-size: 20px; padding: 16px 24px 8px 24px; }}
.h1 {{ font-size: 18px; font-weight: 500; margin: 4px 4px 4px 4px; }}
.card {{ background: {P['SURFACE']}; border: 1px solid {P['OUTLINE']}; border-radius: 16px; }}
.row {{ padding: 14px 18px; border-bottom: 1px solid {P['OUTLINE']}; }}
.row.last {{ border-bottom: none; }}
.rtitle {{ font-size: 14px; }}
.rsub {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
.err {{ font-size: 12px; color: #d93025; }}
.seg {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 18px; padding: 6px 16px; color: {P['ON_SURFACE']}; }}
.seg:checked {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; font-weight: 500; }}
.btn {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 18px; padding: 6px 16px; color: {P['ON_SURFACE']}; }}
.btn.primary {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; font-weight: 500; }}
.swatch {{ border-radius: 20px; min-width: 36px; min-height: 36px; padding: 0; border: 3px solid {P['SURFACE']}; box-shadow: none; }}
.swatch:checked {{ border: 3px solid {P['ON_SURFACE']}; }}
.wall {{ border-radius: 12px; padding: 3px; background: transparent; border: 3px solid transparent; box-shadow: none; }}
.wall:checked {{ border: 3px solid {P['ACCENT']}; background: transparent; }}
.wall label, .wall:checked label, .seg:checked label {{ color: {P['ON_SURFACE']}; }}
.seg:checked label {{ color: {P['ON_ACCENT_CONTAINER']}; }}
entry {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE']}; border: none; border-radius: 12px; padding: 6px 12px; min-height: 28px; }}
switch {{ border-radius: 14px; background: {P['SURFACE_VARIANT']}; border: 1px solid {P['OUTLINE']}; }}
switch:checked {{ background: {P['ACCENT']}; }}
switch slider {{ border-radius: 12px; background: {P['SURFACE']}; border: none; }}
combobox button {{ border-radius: 12px; background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; color: {P['ON_SURFACE']}; }}
.dotc {{ border-radius: 7px; min-width: 14px; min-height: 14px; }}
'''

def ago(ts):
    if not ts: return 'nooit'
    d = datetime.datetime.fromtimestamp(ts); return d.strftime('vandaag %H:%M' if d.date() == datetime.date.today() else '%d-%m-%Y %H:%M')

class App(Gtk.Window):
    def __init__(self, section):
        super().__init__(title='Instellingen'); self.set_wmclass('instellingen', 'Instellingen')
        self.set_default_size(1000, 640); self.set_icon_name('preferences-system'); self.set_name('root')
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.prov, 800)
        self.palm = 0; self.reload_css(); GLib.timeout_add(1000, self.tick)
        self.connect('destroy', self.quit)
        hb = Gtk.Box(); self.add(hb)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); left.set_size_request(260, -1)
        t = Gtk.Label(label='Instellingen', xalign=0); t.get_style_context().add_class('apptitle'); left.pack_start(t, False, False, 0)
        self.nav = Gtk.ListBox(); self.nav.set_name('nav'); left.pack_start(self.nav, True, True, 0)
        for key, icon, label in SECTIONS:
            r = Gtk.ListBoxRow(); r.key = key; b = Gtk.Box(spacing=16)
            b.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0); b.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            r.add(b); self.nav.add(r)
        self.nav.connect('row-selected', lambda lb, r: r and self.show(r.key))
        hb.pack_start(left, False, False, 0)
        self.sc = Gtk.ScrolledWindow(); self.sc.set_name('content'); self.sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        hb.pack_start(self.sc, True, True, 0)
        keys = [s[0] for s in SECTIONS]
        self.nav.select_row(self.nav.get_row_at_index(keys.index(section) if section in keys else 0))
        self.show_all()

    # ---------- infrastructure ----------
    def reload_css(self):
        p = os.path.join(C, 'palette.env'); m = os.path.getmtime(p)
        if m != self.palm: self.palm = m; self.prov.load_from_data(css().encode())

    def tick(self):
        self.reload_css()
        f = '/tmp/osb-settings.section'
        if os.path.exists(f):
            k = open(f).read().strip(); os.remove(f); keys = [s[0] for s in SECTIONS]
            if k in keys: self.nav.select_row(self.nav.get_row_at_index(keys.index(k)))
        if getattr(self, 'cur', '') == 'agenda' and not getattr(self, 'syncing', False):
            st = feeds.status()
            if st != getattr(self, 'last_status', None): self.last_status = st; self.show('agenda')
        return True

    def show(self, key):
        self.cur = key
        for c in self.sc.get_children(): c.destroy()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); outer.set_border_width(24)
        clamp = Gtk.Box(); clamp.pack_start(outer, True, True, 0); outer.set_size_request(640, -1)
        getattr(self, 'page_' + key)(outer); self.sc.add(clamp); clamp.show_all()

    def card(self, parent, title=None):
        if title: l = Gtk.Label(label=title, xalign=0); l.get_style_context().add_class('h1'); parent.pack_start(l, False, False, 0)
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); c.get_style_context().add_class('card'); parent.pack_start(c, False, False, 0); return c

    def row(self, card, title, sub=None, widget=None, last=False, err=False):
        r = Gtk.Box(spacing=12); r.get_style_context().add_class('row')
        if last: r.get_style_context().add_class('last')
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0); t.set_line_wrap(True); t.get_style_context().add_class('rtitle'); tb.pack_start(t, False, False, 0)
        if sub:
            s = Gtk.Label(label=sub, xalign=0); s.set_line_wrap(True); s.set_selectable(True); s.get_style_context().add_class('err' if err else 'rsub'); tb.pack_start(s, False, False, 0)
        r.pack_start(tb, True, True, 0)
        if widget: widget.set_valign(Gtk.Align.CENTER); r.pack_end(widget, False, False, 0)
        card.pack_start(r, False, False, 0); return r

    def switch(self, active, cb):
        sw = Gtk.Switch(); sw.set_active(active); sw.connect('notify::active', lambda w, p: cb(w.get_active())); return sw

    def combo(self, items, cur, cb):
        cb_ = Gtk.ComboBoxText()
        for k, label in items: cb_.append(str(k), label)
        cb_.set_active_id(str(cur)); cb_.connect('changed', lambda w: cb(w.get_active_id())); return cb_

    # ---------- pages ----------
    def page_personalisatie(self, o):
        s = S.load()
        c = self.card(o, 'Personalisatie')
        seg = Gtk.Box(spacing=6); group = []
        for k, label in (('light', 'Licht'), ('dark', 'Donker'), ('auto', 'Automatisch')):
            b = Gtk.ToggleButton(label=label); b.get_style_context().add_class('seg'); b.set_active(s['theme'] == k)
            b.connect('toggled', self.set_theme, k, group); group.append(b); seg.pack_start(b, False, False, 0)
        eff = 'licht' if S.effective_theme(s) == 'light' else 'donker'
        self.row(c, 'Thema', f'Automatisch: licht van 07:00 tot 19:00, daarna donker. Nu actief: {eff}.', seg)
        sw = Gtk.Box(spacing=8); sg = []
        for name in S.ACCENTS:
            b = Gtk.ToggleButton(); b.set_tooltip_text(name.capitalize()); b.get_style_context().add_class('swatch')
            cp = Gtk.CssProvider(); cp.load_from_data(f'.swatch {{ background: {S.ACCENTS[name][0]}; }}'.encode())
            b.get_style_context().add_provider(cp, 900); b.set_active(s['accent'] == name)
            b.connect('toggled', self.set_accent, name, sg); sg.append(b); sw.pack_start(b, False, False, 0)
        self.row(c, 'Accentkleur', s['accent'].capitalize(), sw, last=True)
        c2 = self.card(o, 'Achtergrond')
        fb = Gtk.FlowBox(); fb.set_selection_mode(Gtk.SelectionMode.NONE); fb.set_max_children_per_line(3); fb.set_border_width(12); wg = []
        tdir = os.path.join(S.CACHE, 'thumbs'); os.makedirs(tdir, exist_ok=True)
        for name in S.WALLPAPERS:
            th = S.wallpaper_thumb(name)
            if not th: continue
            b = Gtk.ToggleButton(); b.get_style_context().add_class('wall'); v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            v.pack_start(Gtk.Image.new_from_file(th), False, False, 0); v.pack_start(Gtk.Label(label=name.capitalize() + (' (donker: avond)' if os.path.exists(os.path.join(C, 'wallpapers', name + '-avond.png')) else '')), False, False, 0)
            b.add(v); b.set_active(s['wallpaper'] == name); b.connect('toggled', self.set_wall, name, wg); wg.append(b); fb.add(b)
        c2.pack_start(fb, False, False, 0)
        c = self.card(o, 'Schermvergrendeling')
        self.row(c, 'Automatisch vergrendelen', 'Na deze tijd zonder toetsenbord/muis. Handmatig: Super+L of Vergrendelen in Snelle instellingen.',
                 self.combo([(n, f'Na {n} minuten' if n else 'Nooit') for n in (5, 10, 15, 0)], S.load().get('lock_idle_min', 10), lambda v: S.update(lock_idle_min=int(v))), last=True)

    def exclusive(self, b, group):
        if getattr(self, '_busy', False): return False
        if not b.get_active():
            self._busy = True; b.set_active(True); self._busy = False; return False   # keep one selected
        self._busy = True
        for o in group:
            if o is not b: o.set_active(False)
        self._busy = False; return True

    def set_theme(self, b, k, g):
        if self.exclusive(b, g): S.update(theme=k)
    def set_accent(self, b, k, g):
        if self.exclusive(b, g): S.update(accent=k)
    def set_wall(self, b, k, g):
        if self.exclusive(b, g): S.update(wallpaper=k)
    def page_meldingen(self, o):
        s = S.load(); c = self.card(o, 'Meldingen')
        self.row(c, 'Pop-ups weergeven', 'Uit: er verschijnen geen pop-ups meer.', self.switch(s['notifications'], lambda v: S.update(notifications=v)))
        self.row(c, 'Geschiedenis bewaren als pop-ups uit staan', 'Meldingen blijven zichtbaar in Snelle instellingen.', self.switch(s['notif_history'], lambda v: S.update(notif_history=v)))
        def dnd(v):
            try: N.call('SetDnd', GLib.Variant('(b)', (v,)))
            except Exception as e: print('dnd', e)
        self.row(c, 'Niet storen', 'Zelfde schakelaar als in Snelle instellingen: pop-ups onderdrukt, geschiedenis blijft.', self.switch(N.load().get('dnd', False), dnd))
        self.row(c, 'Duur van pop-ups', 'Geldt voor meldingen die zelf geen duur opgeven.',
                 self.combo([(n, f'{n} seconden') for n in (3, 6, 10, 15)], s['popup_secs'], lambda v: S.update(popup_secs=int(v))), last=True)
        tb = Gtk.Button(label='Testmelding sturen'); tb.get_style_context().add_class('btn'); tb.set_halign(Gtk.Align.START)
        tb.connect('clicked', lambda *a: subprocess.Popen(['notify-send', '-a', 'Instellingen', 'Testmelding', 'Zo zien meldingen eruit.']))
        o.pack_start(tb, False, False, 0)

    def page_agenda(self, o):
        s = S.load(); st = feeds.status()
        c = self.card(o, 'Agenda-abonnementen (iCal / ICS)')
        if not s['feeds']: self.row(c, 'Nog geen agenda\'s', 'Voeg hieronder een openbare iCal-link toe (http, https of webcal).', last=True)
        for i, f in enumerate(s['feeds']):
            fs = st.get(f['id'], {})
            if fs.get('ok'): sub = f"Gesynchroniseerd {ago(fs.get('last_sync'))} · {fs.get('events', 0)} items in feed"; err = False
            elif fs.get('error'): sub = f"Fout bij laatste poging ({ago(fs.get('last_try'))}): {fs['error']}" + (f" · laatste geslaagde sync {ago(fs.get('last_sync'))}" if fs.get('last_sync') else ''); err = True
            else: sub = 'Nog niet gesynchroniseerd'; err = False
            rm = Gtk.Button.new_from_icon_name('user-trash-symbolic', Gtk.IconSize.MENU); rm.get_style_context().add_class('btn'); rm.set_tooltip_text('Verwijderen')
            rm.connect('clicked', self.remove_feed, f['id'])
            r = self.row(c, f['name'], f"{f['url']}\n{sub}", rm, last=i == len(s['feeds']) - 1, err=err)
            dot = Gtk.Box(); dot.get_style_context().add_class('dotc'); dot.set_valign(Gtk.Align.CENTER)
            cp = Gtk.CssProvider(); cp.load_from_data(f".dotc {{ background: {f['color']}; }}".encode()); dot.get_style_context().add_provider(cp, 900)
            r.pack_start(dot, False, False, 0); r.reorder_child(dot, 0)
        c2 = self.card(o, 'Agenda toevoegen')
        g = Gtk.Grid(column_spacing=8, row_spacing=8); g.set_border_width(16)
        self.f_name = Gtk.Entry(placeholder_text='Naam, bijv. Feestdagen'); self.f_url = Gtk.Entry(placeholder_text='https://… of webcal://… .ics'); self.f_url.set_hexpand(True)
        self.f_color = self.combo(FEED_COLORS and [(h, n) for n, h in FEED_COLORS], FEED_COLORS[0][1], lambda v: None)
        add = Gtk.Button(label='Toevoegen'); add.get_style_context().add_class('btn'); add.get_style_context().add_class('primary'); add.connect('clicked', self.add_feed)
        g.attach(self.f_name, 0, 0, 1, 1); g.attach(self.f_color, 1, 0, 1, 1); g.attach(self.f_url, 0, 1, 2, 1); g.attach(add, 2, 1, 1, 1)
        self.f_msg = Gtk.Label(xalign=0); self.f_msg.get_style_context().add_class('rsub'); g.attach(self.f_msg, 0, 2, 3, 1)
        c2.pack_start(g, False, False, 0)
        c3 = self.card(o, 'Synchronisatie')
        self.row(c3, 'Automatisch vernieuwen', None, self.combo([(m, f'Elke {m} minuten' if m < 60 else ('Elk uur' if m == 60 else f'Elke {m // 60} uur')) for m in (15, 30, 60, 180)],
                 s['feed_refresh_min'], lambda v: S.update(feed_refresh_min=int(v))))
        rb = Gtk.Button(label='Nu vernieuwen'); rb.get_style_context().add_class('btn'); rb.connect('clicked', self.refresh); rb.set_sensitive(bool(s['feeds']))
        self.sync_lbl = 'Bezig met vernieuwen…' if getattr(self, 'syncing', False) else ''
        self.row(c3, 'Nu vernieuwen', self.sync_lbl or 'Haalt alle agenda\'s direct opnieuw op.', rb, last=not os.path.exists(feeds.LOCAL))
        if os.path.exists(feeds.LOCAL):
            self.row(c3, 'Lokale agenda', feeds.LOCAL, last=True)

    def add_feed(self, *a):
        name, url = self.f_name.get_text().strip(), self.f_url.get_text().strip()
        err = feeds.valid_url(url)
        if err: self.f_msg.set_text(err); return
        self.refresh(only=feeds.add(name, url, self.f_color.get_active_id())['id'])

    def remove_feed(self, b, fid):
        s = S.load(); s['feeds'] = [f for f in s['feeds'] if f['id'] != fid]; S.save(s)
        st = feeds.status(); st.pop(fid, None); feeds._save_status(st)
        try: os.remove(os.path.join(feeds.DIR, fid + '.ics'))
        except OSError: pass
        self.show('agenda')

    def refresh(self, *a, only=None):
        self.syncing = True; self.show('agenda')
        def work():
            try: feeds.sync_all(only if isinstance(only, str) else None)
            finally: GLib.idle_add(done)
        def done(): self.syncing = False; self.last_status = feeds.status(); self.show('agenda')
        threading.Thread(target=work, daemon=True).start()

    def page_toetsenbord(self, o):
        s = S.load(); c = self.card(o, 'Toetsenbord en taal')
        cur = subprocess.run(['setxkbmap', '-query'], capture_output=True, text=True, timeout=5).stdout
        cur = ' '.join(l.split(':', 1)[1].strip() for l in cur.splitlines() if l.startswith(('layout', 'variant')))
        items = [(f'{l}:{v}', n) for l, v, n in S.LAYOUTS]
        def setl(k): l, v = k.split(':'); S.update(kbd_layout=l, kbd_variant=v)
        self.row(c, 'Toetsenbordindeling', f'Nu actief (setxkbmap): {cur}. De plank toont de indeling.', self.combo(items, f"{s['kbd_layout']}:{s.get('kbd_variant', '')}", setl))
        e = Gtk.Entry(placeholder_text='Typ hier om de indeling te testen'); e.set_size_request(260, -1)
        self.row(c, 'Testveld', None, e)
        self.row(c, 'Taal van de interface', 'Nederlands (Polder OS-onderdelen). Andere talen zijn nog niet beschikbaar.', last=True)

        c = self.card(o, 'Sneltoetsen')
        kb = Gtk.Button(label='Sneltoetsen bekijken'); kb.get_style_context().add_class('btn')
        kb.connect('clicked', lambda *a: subprocess.Popen([sys.executable, os.path.join(C, 'shortcuts', 'sneltoetsen.py')], start_new_session=True))
        self.row(c, 'Overzicht van alle sneltoetsen', 'Ook met Ctrl+Alt+/.', kb, last=True)
        c = self.card(o, 'Klembord')
        self.row(c, 'Klembordgeschiedenis', 'Super+V toont de laatste 10 gekopieerde items (tekst en afbeeldingen). Wachtwoorden uit wachtwoordmanagers worden overgeslagen.',
                 self.switch(S.load().get('clipboard_history', True), lambda v: S.update(clipboard_history=v)))
        cb = Gtk.Button(label='Geschiedenis wissen'); cb.get_style_context().add_class('btn')
        cb.connect('clicked', lambda *a: subprocess.run(['pkill', '-USR2', '-f', 'clip/clipd.py'], timeout=3))
        self.row(c, 'Klembordgeschiedenis wissen', 'Verwijdert alle opgeslagen items.', cb, last=True)

    def page_datum(self, o):
        s = S.load(); c = self.card(o, 'Datum en tijd')
        tz = os.environ.get('TZ') or (open('/etc/timezone').read().strip() if os.path.exists('/etc/timezone') else time.tzname[0])
        self.row(c, 'Huidige tijd', f"{datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} · tijdzone {tz} (systeemklok)")
        self.row(c, '24-uursnotatie gebruiken', 'Plank en agenda.', self.switch(s['clock24'], lambda v: S.update(clock24=v)))
        self.row(c, 'Datum op de plank tonen', 'Het datumvakje opent de agenda.', self.switch(s['show_date'], lambda v: S.update(show_date=v)), last=True)

    # Revision 25: Polder Weer location (Open-Meteo geocoding) -----------------------------------
    def page_weer(self, o):
        import weather as WX
        loc = WX.location(); w = WX.load(); c = self.card(o, 'Weer')
        cur = f"{loc['name']}" + (f", {loc['admin']}" if loc.get('admin') else '') + ('' if S.load().get('weather_loc') else ' (standaard)')
        if w:
            d = w['data']['current']; st = f"{round(d['temperature_2m'])}° {WX.describe(d['weather_code'], d['is_day'])[0].lower()} · bijgewerkt {time.strftime('%H:%M', time.localtime(w['fetched']))}"
        else: st = 'Geen actuele gegevens (offline of nog niet opgehaald); het weervakje op de plank is verborgen.'
        self.row(c, 'Locatie', cur); self.row(c, 'Status', st + ' · bron: Open-Meteo (KNMI/ECMWF), elke 30 min')
        e = Gtk.Entry(placeholder_text='Zoek een plaats, bijv. Utrecht'); e.set_hexpand(True); b = Gtk.Button(label='Zoeken')
        h = Gtk.Box(spacing=8); h.set_border_width(12); h.pack_start(e, True, True, 0); h.pack_start(b, False, False, 0); c.pack_start(h, False, False, 0)
        res = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); c.pack_start(res, False, False, 0)
        def pick(_b, r): S.update(weather_loc=r); GLib.timeout_add(4000, lambda: self.cur == 'weer' and self.show('weer'))
        def search(*a):
            for ch in res.get_children(): ch.destroy()
            try: rs = WX.search(e.get_text().strip())
            except Exception as ex: rs = None; self.row(res, 'Zoeken mislukt', str(ex), last=True, err=True)
            if rs == []: self.row(res, 'Geen plaatsen gevonden', None, last=True)
            for i, r in enumerate(rs or []):
                pb = Gtk.Button(label='Kiezen'); pb.connect('clicked', pick, r)
                self.row(res, r['name'], f"{r['admin']} · {r['lat']:.2f}, {r['lon']:.2f}", pb, last=i == len(rs) - 1)
            res.show_all()
        b.connect('clicked', search); e.connect('activate', search)

    # Revision 25: webapps -------------------------------------------------------------------------
    def page_webapps(self, o):
        import webapps as WA
        c = self.card(o, 'Website als app installeren')
        self.w_url = Gtk.Entry(placeholder_text='Webadres, bijv. music.youtube.com'); self.w_url.set_hexpand(True)
        self.w_name = Gtk.Entry(placeholder_text='Naam (optioneel)'); ib = Gtk.Button(label='Installeren'); ib.get_style_context().add_class('suggested-action')
        h = Gtk.Box(spacing=8); h.set_border_width(12); h.pack_start(self.w_url, True, True, 0); h.pack_start(self.w_name, False, False, 0); h.pack_start(ib, False, False, 0)
        c.pack_start(h, False, False, 0)
        self.w_msg = Gtk.Label(label=getattr(self, 'w_last', 'Opent in een eigen venster met eigen pictogram op de plank. Het pictogram komt van de website zelf.'), xalign=0, wrap=True)
        self.w_msg.get_style_context().add_class('rsub'); self.w_msg.set_margin_start(14); self.w_msg.set_margin_bottom(12); c.pack_start(self.w_msg, False, False, 0)
        def install(*a):
            url, name = self.w_url.get_text(), self.w_name.get_text().strip() or None; self.w_msg.set_text('Bezig met installeren…')
            def work():
                try: r = WA.install(url, name); msg = f"‘{r['name']}’ geïnstalleerd (pictogram: {r['icon_source'].split(':')[0]})."
                except Exception as ex: msg = f'Installeren mislukt: {ex}'
                def done(): self.w_last = msg; self.show('webapps')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        ib.connect('clicked', install); self.w_url.connect('activate', install)
        apps = WA.list_apps(); c2 = self.card(o, 'Geïnstalleerde webapps')
        if not apps: self.row(c2, 'Nog geen webapps', None, last=True)
        for i, a in enumerate(apps):
            r = Gtk.Box(spacing=12); r.get_style_context().add_class('row')
            try: r.pack_start(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(a['icon'], 32, 32, True)), False, False, 0)
            except Exception: pass
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); l = Gtk.Label(label=a['name'], xalign=0); v.pack_start(l, False, False, 0)
            l2 = Gtk.Label(label=a['url'], xalign=0); l2.get_style_context().add_class('rsub'); v.pack_start(l2, False, False, 0); r.pack_start(v, True, True, 0)
            ob = Gtk.Button(label='Openen'); ob.connect('clicked', lambda _b, a=a: Gio.DesktopAppInfo.new_from_filename(a['desktop']).launch([], None)); r.pack_start(ob, False, False, 0)
            rb = Gtk.Button(label='Verwijderen'); rb.connect('clicked', lambda _b, a=a: (WA.remove(a['id']), setattr(self, 'w_last', f"‘{a['name']}’ verwijderd."), self.show('webapps'))); r.pack_start(rb, False, False, 0)
            c2.pack_start(r, False, False, 0)
            if i < len(apps) - 1: c2.pack_start(Gtk.Separator(), False, False, 0)

    def page_over(self, o):
        c = self.card(o, 'Over Polder OS')
        mem = {l.split(':')[0]: int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith(('MemTotal', 'MemAvailable'))}
        deb = open('/etc/debian_version').read().strip() if os.path.exists('/etc/debian_version') else '?'
        pretty = next((l.split('=', 1)[1].strip().strip('"') for l in open('/etc/os-release') if l.startswith('PRETTY_NAME')), '')
        scr = Gdk.Screen.get_default()
        hdr = Gtk.Box(spacing=16); hdr.set_border_width(18)
        hdr.pack_start(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(C, 'brand', 'polderos-logo.png'), 64, 64, True)), False, False, 0)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        l = Gtk.Label(label=S.VERSION, xalign=0); l.get_style_context().add_class('h1'); tb.pack_start(l, False, False, 0)
        l2 = Gtk.Label(label='Een ChromeOS-achtige Linux-desktop, gebouwd op Debian', xalign=0); l2.get_style_context().add_class('rsub'); tb.pack_start(l2, False, False, 0)
        hdr.pack_start(tb, False, False, 0); c.pack_start(hdr, False, False, 0)
        self.row(c, 'Basis', f'{pretty} (debian_version {deb}) · ISO: NAME="Polder OS", ID=polderos, ID_LIKE=debian')
        self.row(c, 'Kernel', platform.release())
        self.row(c, 'Geheugen', f"{mem['MemTotal'] / 1048576:.1f} GB totaal · {mem['MemAvailable'] / 1048576:.1f} GB beschikbaar")
        self.row(c, 'Scherm', f'{scr.get_width()} × {scr.get_height()}')
        wb = Gtk.Button(label='Openen'); wb.connect('clicked', lambda *x: subprocess.Popen([sys.executable, os.path.join(C, 'welcome', 'welkom.py')], start_new_session=True))
        self.row(c, 'Welkom bij Polder OS', 'De rondleiding van de eerste keer opnieuw bekijken.', wb, last=True)

    def quit(self, *a):
        try: os.remove(PID)
        except OSError: pass
        Gtk.main_quit()

signal.signal(signal.SIGTERM, lambda *a: Gtk.main_quit())
App(sys.argv[1] if len(sys.argv) > 1 else 'personalisatie'); Gtk.main()
