#!/usr/bin/env python3
"""Polder OS 'Instellingen' (ChromeOS Settings style, GTK3). Writes ~/.config/osb/settings.json;
osb-settingsd.py applies changes live. usage: instellingen.py [personalisatie|meldingen|agenda|toetsenbord|datum|over]"""
import os, sys, time, threading, uuid, subprocess, platform, datetime, signal, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify', 'calendar'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango, Gio
GLib.set_prgname('polder-settings')
sys.path.insert(0, os.path.join(C, 'weather')); sys.path.insert(0, os.path.join(C, 'webapps'))
import osbsettings as S, osbnotify as N, feeds
PID = os.path.join(os.environ.get('OSB_RUNDIR', '/tmp'), 'osb-settings.pid')
SECTION = os.path.join(os.environ.get('OSB_RUNDIR', '/tmp'), 'osb-settings.section')
if os.path.exists(PID):   # single instance: raise the existing window (and switch section)
    try:
        os.kill(int(open(PID).read()), 0)
        open(SECTION, 'w').write(sys.argv[1] if len(sys.argv) > 1 else '')
        if not os.environ.get('POLDER_COMP'): subprocess.run(['wmctrl', '-a', 'Instellingen'], timeout=5)
        sys.exit(0)
    except (ProcessLookupError, ValueError): pass
open(PID, 'w').write(str(os.getpid()))

SECTIONS = [('personalisatie', 'preferences-desktop-wallpaper-symbolic', 'Personalisatie'),
            ('beeldscherm', 'video-display-symbolic', 'Beeldschermen'),
            ('meldingen', 'preferences-system-notifications-symbolic', 'Meldingen'),
            ('agenda', 'x-office-calendar-symbolic', 'Agenda'),
            ('toetsenbord', 'input-keyboard-symbolic', 'Toetsenbord en taal'),
            ('datum', 'preferences-system-time-symbolic', 'Datum en tijd'),
            ('weer', 'weather-few-clouds-symbolic', 'Weer'),
            ('webapps', 'web-browser-symbolic', 'Webapps'),
            ('telefoon', 'phone-symbolic', 'Telefoon'),
            ('assistent', 'starred-symbolic', 'Assistent'),
            ('sync', 'emblem-synchronizing-symbolic', 'Sync'),
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
        self.nav = Gtk.ListBox(); self.nav.set_name('nav')
        nav_scroll = Gtk.ScrolledWindow(); nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_scroll.add(self.nav); left.pack_start(nav_scroll, True, True, 0)
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
        f = SECTION
        if os.path.exists(f):
            k = open(f).read().strip(); os.remove(f); keys = [s[0] for s in SECTIONS]
            if k in keys: self.nav.select_row(self.nav.get_row_at_index(keys.index(k)))
            self.present()
            if os.environ.get('POLDER_COMP'):
                try:
                    import wayland_control
                    wayland_control.command('focus-app polder-settings')
                except OSError: pass
        if getattr(self, 'cur', '') == 'agenda' and not getattr(self, 'syncing', False):
            st = feeds.status()
            if st != getattr(self, 'last_status', None): self.last_status = st; self.show('agenda')
        if getattr(self, 'cur', '') == 'toetsenbord' and os.environ.get('POLDER_COMP'):
            import wayland_control
            state = wayland_control.keyboard_state()
            name = next((label for l, v, label in S.LAYOUTS if (l, v) == (state.get('layout'), state.get('variant'))), state.get('layout', ''))
            self.keyboard_status.set_text('Indeling kon niet worden toegepast.' if state.get('error') else 'Actief: ' + name)
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
    def page_beeldscherm(self, o):
        if not os.environ.get('POLDER_COMP'):
            c = self.card(o, 'Beeldschermen')
            b = Gtk.Button(label='Beeldschermen instellen')
            b.connect('clicked', lambda *a: subprocess.Popen(['xfce4-display-settings']))
            self.row(c, 'Resolutie en schaal', 'Open de beeldscherminstellingen.', b, last=True)
            return
        import wayland_display as D
        try:
            monitors = D.outputs()
        except Exception:
            self.row(self.card(o, 'Beeldschermen'), 'Beeldschermen niet beschikbaar', 'Probeer het opnieuw nadat het scherm is aangesloten.', last=True)
            return
        forms = []
        for monitor in monitors:
            p = D.profile(monitor); forms.append(p)
            c = self.card(o, monitor.get('description') or monitor['name'])
            self.row(c, 'Beeldscherm gebruiken', monitor['name'], self.switch(p['enabled'], lambda v, p=p: p.update(enabled=v)))
            modes = monitor.get('modes', [])
            cur = next((str(i) for i, m in enumerate(modes) if m.get('current')), '0')
            items = [(str(i), f"{m['width']} × {m['height']}" + (f" · {m['refresh']:g} Hz" if m['refresh'] else '')) for i, m in enumerate(modes)]
            self.row(c, 'Resolutie', None, self.combo(items, cur, lambda v, p=p, modes=modes: p.update(mode=modes[int(v)])))
            scales = sorted(set([1, 1.25, 1.5, 1.75, 2, 2.5, 3, p['scale']]))
            self.row(c, 'Schaal', 'Grootte van tekst en bedieningselementen.', self.combo([(v, f'{v * 100:g}%') for v in scales], p['scale'], lambda v, p=p: p.update(scale=float(v))))
            transforms = [('normal', 'Liggend'), ('90', 'Staand links'), ('180', 'Liggend omgekeerd'), ('270', 'Staand rechts')]
            if p['transform'] not in dict(transforms): transforms.append((p['transform'], 'Gespiegeld'))
            self.row(c, 'Oriëntatie', None, self.combo(transforms, p['transform'], lambda v, p=p: p.update(transform=v)), last=len(monitors) == 1)
            if len(monitors) > 1:
                position = Gtk.Box(spacing=6)
                for axis in ('x', 'y'):
                    position.pack_start(Gtk.Label(label=axis.upper() + ':'), False, False, 0)
                    spin = Gtk.SpinButton.new_with_range(-32768, 32768, 1)
                    spin.set_value(p['position'][axis]); spin.set_width_chars(6)
                    spin.connect('value-changed', lambda w, p=p, axis=axis: p['position'].update({axis: w.get_value_as_int()}))
                    position.pack_start(spin, False, False, 0)
                self.row(c, 'Plaatsing', 'Positie ten opzichte van de andere beeldschermen.', position, last=True)
        buttons = Gtk.Box(spacing=8)
        apply_button = Gtk.Button(label='Toepassen'); apply_button.get_style_context().add_class('btn')
        def begin(*a):
            apply_button.set_sensitive(False)
            def worker():
                try: token, error = D.begin_preview(forms), None
                except Exception as exc: token, error = None, str(exc)
                GLib.idle_add(self.display_preview, token, error)
            threading.Thread(target=worker, daemon=True).start()
        apply_button.connect('clicked', begin); buttons.pack_start(apply_button, False, False, 0)
        refresh = Gtk.Button(label='Vernieuwen'); refresh.connect('clicked', lambda *a: self.show('beeldscherm'))
        buttons.pack_start(refresh, False, False, 0); o.pack_start(buttons, False, False, 0)
        hint = Gtk.Label(label='Bevestig binnen 15 seconden. Zonder bevestiging worden de vorige instellingen hersteld.', xalign=0)
        hint.set_line_wrap(True); o.pack_start(hint, False, False, 0)

    def display_preview(self, token, error):
        import wayland_display as D
        if error:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.CLOSE, text='Beeldschermwijziging niet toegepast')
            dialog.format_secondary_text(error); dialog.connect('response', lambda d, r: (d.destroy(), self.show('beeldscherm')))
            dialog.show(); return False
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, text='Deze beeldscherminstellingen behouden?')
        dialog.add_button('Herstellen', Gtk.ResponseType.REJECT); dialog.add_button('Behouden', Gtk.ResponseType.ACCEPT)
        closed = [False]
        def response(d, result):
            if closed[0]: return
            closed[0] = True
            try: D.decide(token, result == Gtk.ResponseType.ACCEPT)
            except RuntimeError: pass  # The independent watchdog may already have restored the display.
            d.destroy(); GLib.timeout_add(300, lambda: (self.show('beeldscherm'), False)[1])
        def countdown():
            if closed[0]: return False
            state = D.read_state()
            left = max(0, int(state['deadline'] - time.monotonic()) + 1)
            dialog.format_secondary_text(f'De vorige instellingen worden over {left} seconden hersteld.')
            if state['token'] != token or state['status'] not in ('starting', 'preview'):
                closed[0] = True; dialog.destroy(); self.show('beeldscherm'); return False
            return True
        dialog.connect('response', response); dialog.show(); countdown(); GLib.timeout_add(200, countdown)
        return False

    def page_personalisatie(self, o):
        s = S.load()
        c = self.card(o, 'Personalisatie')
        seg = Gtk.Box(spacing=6); group = []
        for k, label in (('light', 'Licht'), ('dark', 'Donker'), ('auto', 'Automatisch')):
            b = Gtk.ToggleButton(label=label); b.get_style_context().add_class('seg'); b.set_active(s['theme'] == k)
            b.connect('toggled', self.set_theme, k, group); group.append(b); seg.pack_start(b, False, False, 0)
        eff = 'licht' if S.effective_theme(s) == 'light' else 'donker'
        self.row(c, 'Thema', f'Automatisch: licht van 07:00 tot 19:00, daarna donker. Nu actief: {eff}.', seg)
        dyn = s.get('color_source') == 'wallpaper'
        seg2 = Gtk.Box(spacing=6); g2 = []
        for k, label in (('accent', 'Accentkleur'), ('wallpaper', 'Kleuren uit achtergrond')):
            b = Gtk.ToggleButton(label=label); b.get_style_context().add_class('seg'); b.set_active((k == 'wallpaper') == dyn)
            b.connect('toggled', self.set_source, k, g2); g2.append(b); seg2.pack_start(b, False, False, 0)
        self.row(c, 'Kleuren', 'Kleuren uit achtergrond: het systeem kiest kleuren die passen bij je achtergrond (licht en donker).', seg2)
        sw = Gtk.Box(spacing=8); sg = []
        seeds = S.dynamic_seeds(s['wallpaper']) if dyn else []
        items = [(str(i), h, f'Kleur {i + 1} uit achtergrond') for i, h in enumerate(seeds)] if dyn else [(n, S.ACCENTS[n][0], n.capitalize()) for n in S.ACCENTS]
        cur = str(min(int(s.get('dynamic_seed', 0)), max(len(seeds) - 1, 0))) if dyn else s['accent']
        for key, colour, tip in items:
            b = Gtk.ToggleButton(); b.set_tooltip_text(tip); b.get_style_context().add_class('swatch')
            cp = Gtk.CssProvider(); cp.load_from_data(f'.swatch {{ background: {colour}; }}'.encode())
            b.get_style_context().add_provider(cp, 900); b.set_active(key == cur)
            b.connect('toggled', self.set_seed if dyn else self.set_accent, key, sg); sg.append(b); sw.pack_start(b, False, False, 0)
        if dyn and not seeds:
            self.row(c, 'Kleur uit achtergrond', 'Niet beschikbaar (polder-dynamic-color ontbreekt); de accentkleur wordt gebruikt.')
        elif dyn:
            self.row(c, 'Kleur uit achtergrond', f'{len(seeds)} kleur{"en" if len(seeds) != 1 else ""} gevonden in {s["wallpaper"].capitalize()}', sw)
        else:
            self.row(c, 'Accentkleur', s['accent'].capitalize(), sw)
        self.row(c, 'Minder beweging', 'Verminder animaties bij het openen van vensters en in apps.',
                 self.switch(s.get('reduced_motion', False), lambda v: S.update(reduced_motion=v)), last=True)
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
        if self.exclusive(b, g):
            S.update(wallpaper=k, dynamic_seed=0)
            if S.load().get('color_source') == 'wallpaper': GLib.idle_add(self.show, 'personalisatie')   # new seed swatches
    def set_source(self, b, k, g):
        if self.exclusive(b, g): S.update(color_source=k); GLib.idle_add(self.show, 'personalisatie')
    def set_seed(self, b, k, g):
        if self.exclusive(b, g): S.update(dynamic_seed=int(k))
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
        if os.environ.get('POLDER_COMP'):
            cur = 'Wijzigingen gelden direct voor aangesloten toetsenborden.'
        else:
            cur = subprocess.run(['setxkbmap', '-query'], capture_output=True, text=True, timeout=5).stdout
            cur = 'Actief: ' + ' '.join(l.split(':', 1)[1].strip() for l in cur.splitlines() if l.startswith(('layout', 'variant')))
        items = [(f'{l}:{v}', n) for l, v, n in S.LAYOUTS]
        def setl(k): l, v = k.split(':'); S.update(kbd_layout=l, kbd_variant=v)
        self.row(c, 'Toetsenbordindeling', cur, self.combo(items, f"{s['kbd_layout']}:{s.get('kbd_variant', '')}", setl))
        self.keyboard_status = Gtk.Label(xalign=0)
        if os.environ.get('POLDER_COMP'): c.pack_start(self.keyboard_status, False, False, 8)
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
        cb.connect('clicked', lambda *a: __import__('shellipc').send('clip-clear') or subprocess.run(['pkill', '-USR2', '-f', 'clip/clipd.py'], timeout=3))
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

    # Revision 28: Telefoon (KDE Connect) ----------------------------------------------------------
    def page_telefoon(self, o):
        import phone as PH
        c = self.card(o, 'Telefoon')
        if not PH.available():
            self.row(c, 'KDE Connect is niet geïnstalleerd', 'Installeer het pakket kdeconnect (zit in de Polder OS ISO).', last=True, err=True); return
        if not PH.running(): PH.start()
        rb = Gtk.Button(label='Vernieuwen'); rb.connect('clicked', lambda *a: (PH.refresh(), GLib.timeout_add(1500, lambda: self.cur == 'telefoon' and self.show('telefoon'))))
        self.row(c, 'Telefoon koppelen', 'Installeer de app "KDE Connect" op je Android-telefoon of iPhone en zorg dat beide op hetzelfde wifi-netwerk zitten.', rb, last=True)
        devs = PH.devices() if PH.running() else []
        paired = [d for d in devs if d['paired']]; others = [d for d in devs if not d['paired'] and d['reachable']]
        for d in paired:
            pc = self.card(o, d['name'])
            st = ('Verbonden' if d['reachable'] else 'Niet bereikbaar') + (f" · batterij {d['battery']}%" + (' (laadt op)' if d['charging'] else '') if d['reachable'] and d['battery'] not in (None, -1) else '')
            ub = Gtk.Button(label='Ontkoppelen'); ub.connect('clicked', lambda _b, i=d['id']: (PH.unpair(i), self.show('telefoon')))
            self.row(pc, 'Status', st, ub)
            for name, title, sub in PH.PLUGINS:
                on = PH.plugin_enabled(d['id'], name)
                if on is None: continue
                self.row(pc, title, sub, self.switch(on, lambda v, i=d['id'], n=name: PH.set_plugin(i, n, v)))
            fb = Gtk.Button(label='Laten overgaan'); fb.set_sensitive(d['reachable']); fb.connect('clicked', lambda _b, i=d['id']: PH.ring(i))
            self.row(pc, 'Telefoon zoeken', 'Je telefoon gaat over, ook als hij op stil staat.', fb, last=True)
        c2 = self.card(o, 'Beschikbare apparaten')
        if not PH.running(): self.row(c2, 'KDE Connect-dienst draait niet', 'Kon kdeconnectd niet starten.', last=True, err=True)
        elif not others: self.row(c2, 'Geen apparaten gevonden', 'Open KDE Connect op je telefoon. Firewall: poorten 1714–1764 (TCP/UDP) moeten open staan.', last=True)
        for k, d in enumerate(others):
            if d['pair_requested']:
                b = Gtk.Button(label='Accepteren'); b.connect('clicked', lambda _b, i=d['id']: (PH.accept(i), self.show('telefoon')))
                sub = f"Koppelverzoek · controleer dat deze code ook op je telefoon staat: {d['verification']}" if d['verification'] else 'Koppelverzoek ontvangen'
            else:
                b = Gtk.Button(label='Koppelen'); b.connect('clicked', lambda _b, i=d['id']: (PH.pair(i), GLib.timeout_add(1500, lambda: self.show('telefoon'))))
                sub = 'Klaar om te koppelen' + (f" · code {d['verification']}" if d['verification'] else '')
            self.row(c2, d['name'], sub, b, last=k == len(others) - 1)

    def page_assistent(self, o):   # Revision 29: Polder Assistent (optional cloud LLM)
        sys.path.insert(0, os.path.join(C, 'assistant')); import llm as L
        s = S.load(); prov = s.get('assistant_provider', 'none'); models = dict(s.get('assistant_model') or {})
        c = self.card(o, 'Polder Assistent')
        self.row(c, 'Openen', 'Super+A. Lokale opdrachten (thema, volume, wifi, apps, weer, bestanden…) werken altijd, zonder sleutel en zonder internet.', last=True)
        c2 = self.card(o, 'AI-dienst (optioneel)')
        items = [('none', 'Geen (alleen lokaal)')] + [(k, v[0]) for k, v in L.PROVIDERS.items()]
        def setp(v): S.update(assistant_provider=v); self.show('assistent')
        self.row(c2, 'Dienst', 'Vrije vragen gaan naar deze dienst; de AI kan dezelfde systeemacties uitvoeren (vraagt eerst bij vergrendelen of wifi/bluetooth uit).', self.combo(items, prov, setp), last=prov == 'none')
        if prov == 'none':
            self.row(c2, 'Lokaal model', 'Een lokaal model (bv. via Ollama) wordt nog niet ondersteund.', last=True); return
        key = L.get_key(prov)
        ke = Gtk.Entry(); ke.set_visibility(False); ke.set_width_chars(28); ke.set_placeholder_text('API-sleutel plakken'); ke.set_text(key)
        where = 'GNOME-sleutelbos' if L._secret_ok() else '~/.config/osb/assistant-keys (alleen jij kunt het lezen)'
        self.row(c2, 'API-sleutel', ('Ingesteld' if key else 'Nog niet ingesteld') + f' · opgeslagen in {where}', ke)
        me = Gtk.Entry(); me.set_width_chars(24); me.set_text(models.get(prov) or L.PROVIDERS[prov][1])
        self.row(c2, 'Model', f'Standaard: {L.PROVIDERS[prov][1]}', me)
        bb = Gtk.Box(spacing=8); sb = Gtk.Button(label='Opslaan'); sb.get_style_context().add_class('btn'); sb.get_style_context().add_class('primary')
        tb = Gtk.Button(label='Testen'); tb.get_style_context().add_class('btn'); bb.pack_start(sb, False, False, 0); bb.pack_start(tb, False, False, 0)
        self.a_status = getattr(self, 'a_status', ('', False))
        self.row(c2, 'Verbinding', self.a_status[0] or 'Test doet één kleine echte API-aanroep.', bb, last=True, err=self.a_status[1])
        def save(*a, rerender=True):
            k = ke.get_text().strip(); models[prov] = me.get_text().strip() or L.PROVIDERS[prov][1]
            S.update(assistant_model=models); w = L.set_key(prov, k)
            self.a_status = (('Sleutel opgeslagen in ' + ('sleutelbos' if w == 'sleutelbos' else 'bestand')) if k else 'Sleutel verwijderd', False)
            if rerender: self.show('assistent')
        def test(*a):
            save(rerender=False); tb.set_sensitive(False); tb.set_label('Testen…')
            def work():
                ok, msg = L.test(prov, models[prov], L.get_key(prov)) if L.get_key(prov) else (False, 'Geen sleutel ingevuld.')
                def done(): self.a_status = (('✓ ' if ok else '✗ ') + msg, not ok); self.cur == 'assistent' and self.show('assistent')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        sb.connect('clicked', save); tb.connect('clicked', test)

    def page_sync(self, o):   # Revision 30: Polder Sync
        sys.path.insert(0, os.path.join(C, 'sync')); import polder_sync as Y
        s = S.load(); c = Y.cfg(); st = Y.load_state()
        k = self.card(o, 'Polder Sync')
        self.row(k, 'Synchroniseren', 'Thema, accent, achtergrond, meldingen, vergrendelen, klok, toetsenbord, vastgezette apps, webapps, weer-locatie, agenda-links, assistent-dienst en Store-apps. Nooit: API-sleutels, wachtzin, klembord.',
                 self.switch(c['enabled'], lambda v: (S.update(sync_enabled=v), self.show('sync'))))
        if getattr(self, 'sync_busy', False): status = 'Bezig met synchroniseren…'; err = False
        elif st.get('last_error'): status = 'Fout: ' + st['last_error']; err = True
        else: status = (f"Laatst: {ago(st.get('last_sync'))} · {st.get('last_result', '')}" if st.get('last_sync') else 'Nog nooit gesynchroniseerd'); err = False
        bb = Gtk.Box(spacing=8)
        nb = Gtk.Button(label='Nu synchroniseren'); nb.get_style_context().add_class('btn'); nb.get_style_context().add_class('primary')
        rb = Gtk.Button(label='Herstel van andere pc'); rb.get_style_context().add_class('btn')
        for b in (nb, rb): b.set_sensitive(not getattr(self, 'sync_busy', False)); bb.pack_start(b, False, False, 0)
        self.row(k, 'Status', status, bb, last=True, err=err)
        def run(restore):
            if restore:
                d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                      text='Instellingen van je andere pc overnemen?')
                d.format_secondary_text('Alle gesynchroniseerde instellingen worden vervangen door de opgeslagen versie. Er wordt eerst een back-up gemaakt.')
                r = d.run(); d.destroy()
                if r != Gtk.ResponseType.OK: return
            self.sync_busy = True; self.show('sync')
            def work():
                Y.sync_safe(restore)
                def done(): self.sync_busy = False; self.cur == 'sync' and self.show('sync')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        nb.connect('clicked', lambda *a: run(False)); rb.connect('clicked', lambda *a: run(True))

        k2 = self.card(o, 'Opslag')
        self.row(k2, 'Waar', 'Een map (Nextcloud, Dropbox, rclone-koppeling, USB) of een privé git-repo (GitHub).',
                 self.combo([('folder', 'Map'), ('git', 'Git / GitHub')], c['backend'], lambda v: (S.update(sync_backend=v), self.show('sync'))))
        if c['backend'] == 'folder':
            fb = Gtk.Button(label='Kiezen…'); fb.get_style_context().add_class('btn')
            def pick(*a):
                d = Gtk.FileChooserDialog(title='Sync-map kiezen', transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
                d.add_buttons('Annuleren', Gtk.ResponseType.CANCEL, 'Kiezen', Gtk.ResponseType.OK)
                if d.run() == Gtk.ResponseType.OK: S.update(sync_folder=d.get_filename())
                d.destroy(); self.show('sync')
            fb.connect('clicked', pick)
            self.row(k2, 'Map', (c['folder'] or 'Nog geen map gekozen') + ' · bestanden komen in de submap polder-sync/', fb, last=True)
        else:
            ue = Gtk.Entry(); ue.set_width_chars(30); ue.set_text(c['git_url']); ue.set_placeholder_text('https://github.com/naam/polder-sync.git')
            ue.connect('activate', lambda e: (S.update(sync_git_url=e.get_text().strip()), self.show('sync')))
            ue.connect('focus-out-event', lambda e, ev: S.update(sync_git_url=e.get_text().strip()) and False)
            self.row(k2, 'Repository-URL', 'Gebruik een PRIVÉ repo. Enter = opslaan.', ue)
            gh = shutil.which('gh')
            authed = gh and subprocess.run(['gh', 'auth', 'status'], capture_output=True, timeout=10).returncode == 0
            gb = Gtk.Box(spacing=8)
            lb = Gtk.Button(label='Inloggen bij GitHub'); lb.get_style_context().add_class('btn')
            lb.connect('clicked', lambda *a: subprocess.Popen(['xfce4-terminal', '--title', 'GitHub inloggen', '-x', 'sh', '-c',
                       'gh auth login --web -h github.com -p https && gh auth setup-git; echo; echo "Klaar, je kunt dit venster sluiten."; read x']))
            cb = Gtk.Button(label='Privé-repo maken'); cb.get_style_context().add_class('btn'); cb.set_sensitive(bool(authed))
            def create(*a):
                r = subprocess.run(['gh', 'repo', 'create', 'polder-sync', '--private', '--description', 'Polder OS instellingen (Polder Sync)'], capture_output=True, text=True, timeout=60)
                login = subprocess.run(['gh', 'api', 'user', '-q', '.login'], capture_output=True, text=True, timeout=30).stdout.strip()
                if login and (r.returncode == 0 or 'already exists' in r.stderr): S.update(sync_git_url=f'https://github.com/{login}/polder-sync.git')
                else: self.sync_note = 'Repo maken mislukt: ' + r.stderr.strip()[-200:]
                self.show('sync')
            cb.connect('clicked', create)
            for b in (lb, cb): gb.pack_start(b, False, False, 0)
            sub = ('Ingelogd bij GitHub (gh).' if authed else 'Log in via je browser met een code (GitHub device-login).') if gh else 'GitHub CLI (gh) is niet geïnstalleerd.'
            if getattr(self, 'sync_note', ''): sub += ' ' + self.sync_note
            self.row(k2, 'GitHub', sub, gb if gh else None, last=True)

        k3 = self.card(o, 'Versleuteling')
        self.row(k3, 'Versleutelen met wachtzin', 'Alles wordt op deze pc versleuteld (scrypt + AES/Fernet) voordat het de map of repo bereikt. Zonder wachtzin kan niemand het lezen, ook jij niet.',
                 self.switch(c['encrypt'], lambda v: (S.update(sync_encrypt=v), self.show('sync'))), last=not c['encrypt'])
        if c['encrypt']:
            pe = Gtk.Entry(); pe.set_visibility(False); pe.set_width_chars(22); pe.set_placeholder_text('Wachtzin'); pe.set_text(Y.get_pass())
            sb = Gtk.Button(label='Opslaan'); sb.get_style_context().add_class('btn')
            box = Gtk.Box(spacing=8); box.pack_start(pe, False, False, 0); box.pack_start(sb, False, False, 0)
            sb.connect('clicked', lambda *a: (Y.set_pass(pe.get_text()), self.show('sync')))
            self.row(k3, 'Wachtzin', ('Ingesteld' if Y.get_pass() else 'Nog niet ingesteld') + ' · gebruik op elke pc dezelfde wachtzin. Wordt nooit gesynchroniseerd.', box, last=True)

        miss = Y.missing_store_apps()
        if miss:
            k4 = self.card(o, 'Apps van je andere pc')
            ib = Gtk.Button(label='Installeren'); ib.get_style_context().add_class('btn')
            debs = [a['id'] for a in miss if a.get('source') != 'Flathub']; flats = [a['id'] for a in miss if a.get('source') == 'Flathub']
            cmd = ' && '.join(([f"pkexec apt-get install -y {' '.join(debs)}"] if debs else []) + ([f"pkexec flatpak install --system -y flathub {' '.join(flats)}"] if flats else []))
            ib.connect('clicked', lambda *a: subprocess.Popen(['xfce4-terminal', '--title', 'Apps herstellen', '-x', 'sh', '-c', cmd + '; echo; echo Klaar.; read x']))
            self.row(k4, f'{len(miss)} app(s) nog niet geïnstalleerd', ', '.join(a.get('name', a['id']) for a in miss), ib, last=True)
        import glob as _g
        nb2 = len(_g.glob(os.path.join(Y.BACKUPS, '*.json')))
        k5 = self.card(o, 'Back-ups')
        ob = Gtk.Button(label='Map openen'); ob.get_style_context().add_class('btn'); ob.connect('clicked', lambda *a: subprocess.Popen(['xdg-open', Y.BACKUPS]))
        self.row(k5, f'{nb2} back-up(s)', 'Voor elke synchronisatie die iets overschrijft, wordt je oude toestand bewaard (laatste 10). Per instelling wint de nieuwste wijziging.', ob if nb2 else None, last=True)

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
        self.updates_card(o)

    def updates_card(self, o):   # Revision 26: automatic updates
        import updates as U
        c = self.card(o, 'Updates')
        en = U.auto_enabled()
        if en is None: self.row(c, 'Automatische updates', 'unattended-upgrades is niet ingesteld op dit systeem (wel in de Polder OS ISO).')
        else:
            def toggle(v):
                def work():
                    ok = U.set_auto(v); GLib.idle_add(lambda: (setattr(self, 'upd_msg', None if ok else 'Wijzigen mislukt (geen toestemming).'), self.show('over')))
                threading.Thread(target=work, daemon=True).start()
            self.row(c, 'Automatische updates', 'Beveiligings- en stabiele updates \'s nachts installeren (unattended-upgrades) en Flatpak-apps dagelijks bijwerken.', self.switch(en, toggle))
        lu = U.last_update()
        self.row(c, 'Laatst bijgewerkt', time.strftime('%d-%m-%Y %H:%M', time.localtime(lu[0])) + f' (bron: {lu[1]})' if lu else 'Nog nooit (geen updategeschiedenis gevonden)')
        rb = U.reboot_required()
        if rb: self.row(c, 'Opnieuw opstarten vereist', 'Updates zijn geïnstalleerd; start opnieuw op om ze te gebruiken.', err=True)
        nb = Gtk.Button(label='Nu controleren')
        def check(*a):
            self.upd_msg = 'Controleren…'; self.show('over')
            def done(r):
                parts = []
                if r['apt'] is not None: parts.append(f"{r['apt']} Debian-update(s)")
                if r['flatpak'] is not None: parts.append(f"{r['flatpak']} Flatpak-update(s)")
                msg = ', '.join(parts) or 'Controleren mislukt'
                if r['error'] and r['apt'] is None: msg += f" · {r['error'][:90]}"
                GLib.idle_add(lambda: (setattr(self, 'upd_msg', msg + ' · ' + time.strftime('%H:%M')), self.cur == 'over' and self.show('over')))
            U.check(done)
        nb.connect('clicked', check)
        self.row(c, 'Controleren op updates', getattr(self, 'upd_msg', None) or 'Via PackageKit (Debian) en Flatpak.', nb)
        sb = Gtk.Button(label='Openen'); sb.connect('clicked', lambda *a: subprocess.Popen([sys.executable, os.path.join(C, 'store', 'store.py'), 'updates'], start_new_session=True))
        self.row(c, 'Updates in Polder Store', 'Bekijk en installeer beschikbare updates.', sb, last=True)

    def quit(self, *a):
        try: os.remove(PID)
        except OSError: pass
        Gtk.main_quit()

signal.signal(signal.SIGTERM, lambda *a: Gtk.main_quit())
App(sys.argv[1] if len(sys.argv) > 1 else 'personalisatie'); Gtk.main()
