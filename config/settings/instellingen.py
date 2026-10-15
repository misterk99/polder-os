#!/usr/bin/env python3
"""Polder OS 'Instellingen' (ChromeOS Settings style, GTK3). Writes ~/.config/osb/settings.json;
osb-settingsd.py applies changes live. usage: instellingen.py [personalisatie|meldingen|agenda|toetsenbord|taal|datum|over]"""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, sys, json, time, threading, uuid, subprocess, platform, datetime, signal, shutil
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
        if not os.environ.get('POLDER_COMP'): subprocess.run(['wmctrl', '-a', _('Settings')], timeout=5)
        sys.exit(0)
    except (ProcessLookupError, ValueError): pass
open(PID, 'w').write(str(os.getpid()))

SECTIONS = [('personalisatie', 'preferences-desktop-wallpaper-symbolic', _('Personalization')),
            ('beeldscherm', 'video-display-symbolic', _('Displays')),
            ('meldingen', 'preferences-system-notifications-symbolic', _('Notifications')),
            ('agenda', 'x-office-calendar-symbolic', _('Calendar')),
            ('toetsenbord', 'input-keyboard-symbolic', _('Keyboard')),
            ('taal', 'preferences-desktop-locale-symbolic', _('Language and region')),
            ('datum', 'preferences-system-time-symbolic', _('Date and time')),
            ('weer', 'weather-few-clouds-symbolic', _('Weather')),
            ('webapps', 'web-browser-symbolic', _('Web apps')),
            ('telefoon', 'phone-symbolic', _('Phone')),
            ('assistent', 'starred-symbolic', _('Assistant')),
            ('sync', 'emblem-synchronizing-symbolic', _('Sync')),
            ('safeharbor', 'document-revert-symbolic', _('SafeHarbor')),
            ('over', 'help-about-symbolic', _('About Polder OS'))]
FEED_COLORS = [(_('Blue'), '#0b57d0'), (_('Green'), '#188038'), (_('Red'), '#d93025'), (_('Orange'), '#e8710a'), (_('Purple'), '#9334e6'), (_('Gray'), '#5f6368')]

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
    d = datetime.datetime.fromtimestamp(ts); return d.strftime(_('today %H:%M') if d.date() == datetime.date.today() else '%d-%m-%Y %H:%M')

class App(Gtk.Window):
    def __init__(self, section):
        super().__init__(title=_('Settings')); self.set_wmclass('instellingen', _('Settings'))
        self.set_default_size(1000, 640); self.set_icon_name('preferences-system'); self.set_name('root')
        self.prov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.prov, 800)
        self.palm = 0; self.reload_css(); GLib.timeout_add(1000, self.tick)
        self.connect('destroy', self.quit)
        hb = Gtk.Box(); self.add(hb)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); left.set_size_request(260, -1)
        t = Gtk.Label(label=_('Settings'), xalign=0); t.get_style_context().add_class('apptitle'); left.pack_start(t, False, False, 0)
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
            self.keyboard_status.set_text(_('The layout could not be applied.') if state.get('error') else _('Active: ') + name)
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
            c = self.card(o, _('Displays'))
            b = Gtk.Button(label=_('Set up displays'))
            b.connect('clicked', lambda *a: subprocess.Popen(['xfce4-display-settings']))
            self.row(c, _('Resolution and scale'), _('Open the display settings.'), b, last=True)
            return
        import wayland_display as D
        try:
            monitors = D.outputs()
        except Exception:
            self.row(self.card(o, _('Displays')), _('Displays not available'), _('Try again after the display is connected.'), last=True)
            return
        forms = []
        for monitor in monitors:
            p = D.profile(monitor); forms.append(p)
            c = self.card(o, monitor.get('description') or monitor['name'])
            self.row(c, _('Use display'), monitor['name'], self.switch(p['enabled'], lambda v, p=p: p.update(enabled=v)))
            modes = monitor.get('modes', [])
            cur = next((str(i) for i, m in enumerate(modes) if m.get('current')), '0')
            items = [(str(i), f"{m['width']} × {m['height']}" + (f" · {m['refresh']:g} Hz" if m['refresh'] else '')) for i, m in enumerate(modes)]
            self.row(c, _('Resolution'), None, self.combo(items, cur, lambda v, p=p, modes=modes: p.update(mode=modes[int(v)])))
            scales = sorted(set([1, 1.25, 1.5, 1.75, 2, 2.5, 3, p['scale']]))
            self.row(c, _('Scale'), _('Size of text and controls.'), self.combo([(v, f'{v * 100:g}%') for v in scales], p['scale'], lambda v, p=p: p.update(scale=float(v))))
            transforms = [('normal', _('Landscape')), ('90', _('Portrait left')), ('180', _('Landscape flipped')), ('270', _('Portrait right'))]
            if p['transform'] not in dict(transforms): transforms.append((p['transform'], _('Mirrored')))
            self.row(c, _('Orientation'), None, self.combo(transforms, p['transform'], lambda v, p=p: p.update(transform=v)), last=len(monitors) == 1)
            if len(monitors) > 1:
                position = Gtk.Box(spacing=6)
                for axis in ('x', 'y'):
                    position.pack_start(Gtk.Label(label=axis.upper() + ':'), False, False, 0)
                    spin = Gtk.SpinButton.new_with_range(-32768, 32768, 1)
                    spin.set_value(p['position'][axis]); spin.set_width_chars(6)
                    spin.connect('value-changed', lambda w, p=p, axis=axis: p['position'].update({axis: w.get_value_as_int()}))
                    position.pack_start(spin, False, False, 0)
                self.row(c, _('Placement'), _('Position relative to the other displays.'), position, last=True)
        buttons = Gtk.Box(spacing=8)
        apply_button = Gtk.Button(label=_('Apply')); apply_button.get_style_context().add_class('btn')
        def begin(*a):
            apply_button.set_sensitive(False)
            def worker():
                try: token, error = D.begin_preview(forms), None
                except Exception as exc: token, error = None, str(exc)
                GLib.idle_add(self.display_preview, token, error)
            threading.Thread(target=worker, daemon=True).start()
        apply_button.connect('clicked', begin); buttons.pack_start(apply_button, False, False, 0)
        refresh = Gtk.Button(label=_('Refresh')); refresh.connect('clicked', lambda *a: self.show('beeldscherm'))
        buttons.pack_start(refresh, False, False, 0); o.pack_start(buttons, False, False, 0)
        hint = Gtk.Label(label=_('Confirm within 15 seconds. Without confirmation the previous settings are restored.'), xalign=0)
        hint.set_line_wrap(True); o.pack_start(hint, False, False, 0)

    def display_preview(self, token, error):
        import wayland_display as D
        if error:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.CLOSE, text=_('Display change not applied'))
            dialog.format_secondary_text(error); dialog.connect('response', lambda d, r: (d.destroy(), self.show('beeldscherm')))
            dialog.show(); return False
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, text=_('Keep these display settings?'))
        dialog.add_button(_('Restore'), Gtk.ResponseType.REJECT); dialog.add_button(_('Keep'), Gtk.ResponseType.ACCEPT)
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
            dialog.format_secondary_text(_('The previous settings will be restored in {left} seconds.').format(left=left))
            if state['token'] != token or state['status'] not in ('starting', 'preview'):
                closed[0] = True; dialog.destroy(); self.show('beeldscherm'); return False
            return True
        dialog.connect('response', response); dialog.show(); countdown(); GLib.timeout_add(200, countdown)
        return False

    def page_personalisatie(self, o):
        s = S.load()
        c = self.card(o, _('Personalization'))
        seg = Gtk.Box(spacing=6); group = []
        for k, label in (('light', _('Light')), ('dark', _('Dark')), ('auto', _('Automatic'))):
            b = Gtk.ToggleButton(label=label); b.get_style_context().add_class('seg'); b.set_active(s['theme'] == k)
            b.connect('toggled', self.set_theme, k, group); group.append(b); seg.pack_start(b, False, False, 0)
        eff = 'licht' if S.effective_theme(s) == 'light' else 'donker'
        self.row(c, _('Theme'), _('Automatic: light from 07:00 to 19:00, dark after that. Now active: {eff}.').format(eff=eff), seg)
        dyn = s.get('color_source') == 'wallpaper'
        seg2 = Gtk.Box(spacing=6); g2 = []
        for k, label in (('accent', _('Accent color')), ('wallpaper', _('Colors from wallpaper'))):
            b = Gtk.ToggleButton(label=label); b.get_style_context().add_class('seg'); b.set_active((k == 'wallpaper') == dyn)
            b.connect('toggled', self.set_source, k, g2); g2.append(b); seg2.pack_start(b, False, False, 0)
        self.row(c, _('Colors'), _('Colors from wallpaper: the system picks colors that match your wallpaper (light and dark).'), seg2)
        sw = Gtk.Box(spacing=8); sg = []
        seeds = S.dynamic_seeds(s['wallpaper']) if dyn else []
        items = [(str(i), h, _('Color {p0} from wallpaper').format(p0=i + 1)) for i, h in enumerate(seeds)] if dyn else [(n, S.ACCENTS[n][0], n.capitalize()) for n in S.ACCENTS]
        cur = str(min(int(s.get('dynamic_seed', 0)), max(len(seeds) - 1, 0))) if dyn else s['accent']
        for key, colour, tip in items:
            b = Gtk.ToggleButton(); b.set_tooltip_text(tip); b.get_style_context().add_class('swatch')
            cp = Gtk.CssProvider(); cp.load_from_data(f'.swatch {{ background: {colour}; }}'.encode())
            b.get_style_context().add_provider(cp, 900); b.set_active(key == cur)
            b.connect('toggled', self.set_seed if dyn else self.set_accent, key, sg); sg.append(b); sw.pack_start(b, False, False, 0)
        if dyn and not seeds:
            self.row(c, _('Color from wallpaper'), _('Not available (polder-dynamic-color is missing); the accent color is used.'))
        elif dyn:
            self.row(c, _('Color from wallpaper'), f'{len(seeds)} kleur{"en" if len(seeds) != 1 else ""} gevonden in {s["wallpaper"].capitalize()}', sw)
        else:
            self.row(c, _('Accent color'), s['accent'].capitalize(), sw)
        self.row(c, _('Reduce motion'), _('Reduce animations when opening windows and in apps.'),
                 self.switch(s.get('reduced_motion', False), lambda v: S.update(reduced_motion=v)), last=True)
        c2 = self.card(o, _('Wallpaper'))
        fb = Gtk.FlowBox(); fb.set_selection_mode(Gtk.SelectionMode.NONE); fb.set_max_children_per_line(3); fb.set_border_width(12); wg = []
        tdir = os.path.join(S.CACHE, 'thumbs'); os.makedirs(tdir, exist_ok=True)
        for name in S.WALLPAPERS:
            th = S.wallpaper_thumb(name)
            if not th: continue
            b = Gtk.ToggleButton(); b.get_style_context().add_class('wall'); v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            v.pack_start(Gtk.Image.new_from_file(th), False, False, 0); v.pack_start(Gtk.Label(label=name.capitalize() + (_(' (dark: evening)') if os.path.exists(os.path.join(C, 'wallpapers', name + '-avond.png')) else '')), False, False, 0)
            b.add(v); b.set_active(s['wallpaper'] == name); b.connect('toggled', self.set_wall, name, wg); wg.append(b); fb.add(b)
        c2.pack_start(fb, False, False, 0)
        c = self.card(o, _('Screen lock'))
        self.row(c, _('Lock automatically'), _('After this much time without keyboard/mouse input. Manually: Super+L or Lock in Quick Settings.'),
                 self.combo([(n, _('After {n} minutes').format(n=n) if n else _('Never')) for n in (5, 10, 15, 0)], S.load().get('lock_idle_min', 10), lambda v: S.update(lock_idle_min=int(v))), last=True)

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
        s = S.load(); c = self.card(o, _('Notifications'))
        self.row(c, _('Show pop-ups'), _('Off: no more pop-ups appear.'), self.switch(s['notifications'], lambda v: S.update(notifications=v)))
        self.row(c, _('Keep history when pop-ups are off'), _('Notifications stay visible in Quick Settings.'), self.switch(s['notif_history'], lambda v: S.update(notif_history=v)))
        def dnd(v):
            try: N.call('SetDnd', GLib.Variant('(b)', (v,)))
            except Exception as e: print('dnd', e)
        self.row(c, _('Do not disturb'), _('Same switch as in Quick Settings: pop-ups are suppressed, history is kept.'), self.switch(N.load().get('dnd', False), dnd))
        self.row(c, _('Pop-up duration'), _('Applies to notifications that do not set their own duration.'),
                 self.combo([(n, _('{n} seconds').format(n=n)) for n in (3, 6, 10, 15)], s['popup_secs'], lambda v: S.update(popup_secs=int(v))), last=True)
        tb = Gtk.Button(label=_('Send test notification')); tb.get_style_context().add_class('btn'); tb.set_halign(Gtk.Align.START)
        tb.connect('clicked', lambda *a: subprocess.Popen(['notify-send', '-a', _('Settings'), _('Test notification'), _('This is what notifications look like.')]))
        o.pack_start(tb, False, False, 0)

    def page_agenda(self, o):
        s = S.load(); st = feeds.status()
        c = self.card(o, _('Calendar subscriptions (iCal / ICS)'))
        if not s['feeds']: self.row(c, _('No calendars yet'), _('Add a public iCal link below (http, https or webcal).'), last=True)
        for i, f in enumerate(s['feeds']):
            fs = st.get(f['id'], {})
            if fs.get('ok'): sub = _('Synced {p0} · {p1} items in feed').format(p0=ago(fs.get('last_sync')), p1=fs.get('events', 0)); err = False
            elif fs.get('error'): sub = _('Error on last attempt ({p0}): {p1}').format(p0=ago(fs.get('last_try')), p1=fs['error']) + (_(' · last successful sync {p0}').format(p0=ago(fs.get('last_sync'))) if fs.get('last_sync') else ''); err = True
            else: sub = _('Not synced yet'); err = False
            rm = Gtk.Button.new_from_icon_name('user-trash-symbolic', Gtk.IconSize.MENU); rm.get_style_context().add_class('btn'); rm.set_tooltip_text(_('Remove'))
            rm.connect('clicked', self.remove_feed, f['id'])
            r = self.row(c, f['name'], f"{f['url']}\n{sub}", rm, last=i == len(s['feeds']) - 1, err=err)
            dot = Gtk.Box(); dot.get_style_context().add_class('dotc'); dot.set_valign(Gtk.Align.CENTER)
            cp = Gtk.CssProvider(); cp.load_from_data(f".dotc {{ background: {f['color']}; }}".encode()); dot.get_style_context().add_provider(cp, 900)
            r.pack_start(dot, False, False, 0); r.reorder_child(dot, 0)
        c2 = self.card(o, _('Add calendar'))
        g = Gtk.Grid(column_spacing=8, row_spacing=8); g.set_border_width(16)
        self.f_name = Gtk.Entry(placeholder_text=_('Name, e.g. Holidays')); self.f_url = Gtk.Entry(placeholder_text='https://… of webcal://… .ics'); self.f_url.set_hexpand(True)
        self.f_color = self.combo(FEED_COLORS and [(h, n) for n, h in FEED_COLORS], FEED_COLORS[0][1], lambda v: None)
        add = Gtk.Button(label=_('Add')); add.get_style_context().add_class('btn'); add.get_style_context().add_class('primary'); add.connect('clicked', self.add_feed)
        g.attach(self.f_name, 0, 0, 1, 1); g.attach(self.f_color, 1, 0, 1, 1); g.attach(self.f_url, 0, 1, 2, 1); g.attach(add, 2, 1, 1, 1)
        self.f_msg = Gtk.Label(xalign=0); self.f_msg.get_style_context().add_class('rsub'); g.attach(self.f_msg, 0, 2, 3, 1)
        c2.pack_start(g, False, False, 0)
        c3 = self.card(o, _('Synchronization'))
        self.row(c3, _('Refresh automatically'), None, self.combo([(m, _('Every {m} minutes').format(m=m) if m < 60 else (_('Every hour') if m == 60 else _('Every {p0} hours').format(p0=m // 60))) for m in (15, 30, 60, 180)],
                 s['feed_refresh_min'], lambda v: S.update(feed_refresh_min=int(v))))
        rb = Gtk.Button(label=_('Refresh now')); rb.get_style_context().add_class('btn'); rb.connect('clicked', self.refresh); rb.set_sensitive(bool(s['feeds']))
        self.sync_lbl = _('Refreshing…') if getattr(self, 'syncing', False) else ''
        self.row(c3, _('Refresh now'), self.sync_lbl or _('Fetches all calendars again right away.'), rb, last=not os.path.exists(feeds.LOCAL))
        if os.path.exists(feeds.LOCAL):
            self.row(c3, _('Local calendar'), feeds.LOCAL, last=True)

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
        s = S.load(); c = self.card(o, _('Keyboard'))
        if os.environ.get('POLDER_COMP'):
            cur = _('Changes apply immediately to connected keyboards.')
        else:
            cur = subprocess.run(['setxkbmap', '-query'], capture_output=True, text=True, timeout=5).stdout
            cur = _('Active: ') + ' '.join(l.split(':', 1)[1].strip() for l in cur.splitlines() if l.startswith(('layout', 'variant')))
        items = [(f'{l}:{v}', n) for l, v, n in S.LAYOUTS]
        def setl(k): l, v = k.split(':'); S.update(kbd_layout=l, kbd_variant=v)
        self.row(c, _('Keyboard layout'), cur, self.combo(items, f"{s['kbd_layout']}:{s.get('kbd_variant', '')}", setl))
        self.keyboard_status = Gtk.Label(xalign=0)
        if os.environ.get('POLDER_COMP'): c.pack_start(self.keyboard_status, False, False, 8)
        e = Gtk.Entry(placeholder_text=_('Type here to test the layout')); e.set_size_request(260, -1)
        self.row(c, _('Test field'), None, e, last=True)

        c = self.card(o, _('Keyboard shortcuts'))
        kb = Gtk.Button(label=_('View keyboard shortcuts')); kb.get_style_context().add_class('btn')
        kb.connect('clicked', lambda *a: subprocess.Popen([sys.executable, os.path.join(C, 'shortcuts', 'sneltoetsen.py')], start_new_session=True))
        self.row(c, _('Overview of all keyboard shortcuts'), _('Also with Ctrl+Alt+/.'), kb, last=True)
        c = self.card(o, _('Clipboard'))
        self.row(c, _('Clipboard history'), _('Super+V shows the last 10 copied items (text and images). Passwords from password managers are skipped.'),
                 self.switch(S.load().get('clipboard_history', True), lambda v: S.update(clipboard_history=v)))
        cb = Gtk.Button(label=_('Clear history')); cb.get_style_context().add_class('btn')
        cb.connect('clicked', lambda *a: __import__('shellipc').send('clip-clear') or subprocess.run(['pkill', '-USR2', '-f', 'clip/clipd.py'], timeout=3) or subprocess.run(['pkill', '-USR2', '-x', 'polder-clipd'], timeout=3))
        self.row(c, _('Clear clipboard history'), _('Removes all stored items.'), cb, last=True)

    def page_taal(self, o):   # Polder OS i18n: Nederlands / English (gettext domain 'polder')
        import polder_i18n as I
        c = self.card(o, _('Language and region'))
        sysname = dict((k, n) for k, n, _l in I.LANGUAGES)[I.system_language()]
        items = [('system', _('Follow system language ({name})').format(name=sysname))] + [(k, n) for k, n, _l in I.LANGUAGES]
        cur = I.chosen_language() or 'system'
        def setlang(k):
            if k == cur: return
            I.set_language(None if k == 'system' else k)
            done = I.restart_components()
            st = os.path.join(os.environ.get('OSB_RUNDIR', '/tmp'), 'osb-settings.langnote')
            open(st, 'w').write('live' if done else 'relogin')
            try: os.remove(PID)
            except OSError: pass
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), 'taal'])   # rebuild this window in the new language
        self.row(c, _('Language of Polder OS'), _('Applies to all Polder OS components. By default Polder OS follows the system language.'),
                 self.combo(items, cur, setlang))
        note_f = os.path.join(os.environ.get('OSB_RUNDIR', '/tmp'), 'osb-settings.langnote')
        note = open(note_f).read() if os.path.exists(note_f) else ''
        if note:
            os.remove(note_f)
            if note == 'live':
                self.row(c, _('Language changed'), _('Shelf, launcher and notifications have been restarted in the new language. Apps that are already open use it after you reopen them.'))
            else:
                lo = Gtk.Button(label=_('Sign out')); lo.get_style_context().add_class('btn')
                lo.connect('clicked', lambda *a: subprocess.Popen(['sh', '-c', 'loginctl terminate-session "$XDG_SESSION_ID"']))
                self.row(c, _('Sign in again'), _('Sign out and sign in again to use the new language everywhere.'), lo)
        sb = Gtk.Button(label=_('Set for the whole system')); sb.get_style_context().add_class('btn')
        self.sys_note = getattr(self, 'sys_note', None)
        def sysset(*a):
            ok, msg = I.set_system_locale(I.LANG)
            self.sys_note = _('System language set; the login screen and boot menu use it from the next start.') if ok else _('Could not set the system language: ') + (msg or '?')
            self.show('taal')
        sb.connect('clicked', sysset)
        self.row(c, _('Login screen and boot menu'), self.sys_note or _('Also use this language for the login screen, the boot menu (SafeHarbor) and new users. Asks for your password.'), sb, last=True)

    def page_datum(self, o):
        s = S.load(); c = self.card(o, _('Date and time'))
        tz = os.environ.get('TZ') or (open('/etc/timezone').read().strip() if os.path.exists('/etc/timezone') else time.tzname[0])
        self.row(c, _('Current time'), _('{p0} · time zone {tz} (system clock)').format(p0=datetime.datetime.now().strftime('%d-%m-%Y %H:%M'), tz=tz))
        self.row(c, _('Use 24-hour format'), _('Shelf and calendar.'), self.switch(s['clock24'], lambda v: S.update(clock24=v)))
        self.row(c, _('Show date on the shelf'), _('The date box opens the calendar.'), self.switch(s['show_date'], lambda v: S.update(show_date=v)), last=True)

    # Revision 25: Polder Weer location (Open-Meteo geocoding) -----------------------------------
    def page_weer(self, o):
        import weather as WX
        loc = WX.location(); w = WX.load(); c = self.card(o, _('Weather'))
        cur = f"{loc['name']}" + (f", {loc['admin']}" if loc.get('admin') else '') + ('' if S.load().get('weather_loc') else _(' (default)'))
        if w:
            d = w['data']['current']; st = _('{p0}° {p1} · updated {p2}').format(p0=round(d['temperature_2m']), p1=WX.describe(d['weather_code'], d['is_day'])[0].lower(), p2=time.strftime('%H:%M', time.localtime(w['fetched'])))
        else: st = _('No current data (offline or not fetched yet); the weather box on the shelf is hidden.')
        self.row(c, _('Location'), cur); self.row(c, _('Status'), st + _(' · source: Open-Meteo (KNMI/ECMWF), every 30 min'))
        e = Gtk.Entry(placeholder_text=_('Search for a place, e.g. Utrecht')); e.set_hexpand(True); b = Gtk.Button(label=_('Search'))
        h = Gtk.Box(spacing=8); h.set_border_width(12); h.pack_start(e, True, True, 0); h.pack_start(b, False, False, 0); c.pack_start(h, False, False, 0)
        res = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); c.pack_start(res, False, False, 0)
        def pick(_b, r): S.update(weather_loc=r); GLib.timeout_add(4000, lambda: self.cur == 'weer' and self.show('weer'))
        def search(*a):
            for ch in res.get_children(): ch.destroy()
            try: rs = WX.search(e.get_text().strip())
            except Exception as ex: rs = None; self.row(res, _('Search failed'), str(ex), last=True, err=True)
            if rs == []: self.row(res, _('No places found'), None, last=True)
            for i, r in enumerate(rs or []):
                pb = Gtk.Button(label=_('Choose')); pb.connect('clicked', pick, r)
                self.row(res, r['name'], f"{r['admin']} · {r['lat']:.2f}, {r['lon']:.2f}", pb, last=i == len(rs) - 1)
            res.show_all()
        b.connect('clicked', search); e.connect('activate', search)

    # Revision 25: webapps -------------------------------------------------------------------------
    def page_webapps(self, o):
        import webapps as WA
        c = self.card(o, _('Install website as app'))
        self.w_url = Gtk.Entry(placeholder_text=_('Web address, e.g. music.youtube.com')); self.w_url.set_hexpand(True)
        self.w_name = Gtk.Entry(placeholder_text=_('Name (optional)')); ib = Gtk.Button(label=_('Install')); ib.get_style_context().add_class('suggested-action')
        h = Gtk.Box(spacing=8); h.set_border_width(12); h.pack_start(self.w_url, True, True, 0); h.pack_start(self.w_name, False, False, 0); h.pack_start(ib, False, False, 0)
        c.pack_start(h, False, False, 0)
        self.w_msg = Gtk.Label(label=getattr(self, 'w_last', _('Opens in its own window with its own icon on the shelf. The icon comes from the website itself.')), xalign=0, wrap=True)
        self.w_msg.get_style_context().add_class('rsub'); self.w_msg.set_margin_start(14); self.w_msg.set_margin_bottom(12); c.pack_start(self.w_msg, False, False, 0)
        def install(*a):
            url, name = self.w_url.get_text(), self.w_name.get_text().strip() or None; self.w_msg.set_text(_('Installing…'))
            def work():
                try: r = WA.install(url, name); msg = _('‘{p0}’ installed (icon: {p1}).').format(p0=r['name'], p1=r['icon_source'].split(':')[0])
                except Exception as ex: msg = _('Installation failed: {ex}').format(ex=ex)
                def done(): self.w_last = msg; self.show('webapps')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        ib.connect('clicked', install); self.w_url.connect('activate', install)
        apps = WA.list_apps(); c2 = self.card(o, _('Installed web apps'))
        if not apps: self.row(c2, _('No web apps yet'), None, last=True)
        for i, a in enumerate(apps):
            r = Gtk.Box(spacing=12); r.get_style_context().add_class('row')
            try: r.pack_start(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(a['icon'], 32, 32, True)), False, False, 0)
            except Exception: pass
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); l = Gtk.Label(label=a['name'], xalign=0); v.pack_start(l, False, False, 0)
            l2 = Gtk.Label(label=a['url'], xalign=0); l2.get_style_context().add_class('rsub'); v.pack_start(l2, False, False, 0); r.pack_start(v, True, True, 0)
            ob = Gtk.Button(label=_('Open')); ob.connect('clicked', lambda _b, a=a: Gio.DesktopAppInfo.new_from_filename(a['desktop']).launch([], None)); r.pack_start(ob, False, False, 0)
            rb = Gtk.Button(label=_('Remove')); rb.connect('clicked', lambda _b, a=a: (WA.remove(a['id']), setattr(self, 'w_last', _('‘{p0}’ removed.').format(p0=a['name'])), self.show('webapps'))); r.pack_start(rb, False, False, 0)
            c2.pack_start(r, False, False, 0)
            if i < len(apps) - 1: c2.pack_start(Gtk.Separator(), False, False, 0)

    # Revision 28: Telefoon (KDE Connect) ----------------------------------------------------------
    def page_telefoon(self, o):
        import phone as PH
        c = self.card(o, _('Phone'))
        if not PH.available():
            self.row(c, _('KDE Connect is not installed'), _('Install the kdeconnect package (included in the Polder OS ISO).'), last=True, err=True); return
        if not PH.running(): PH.start()
        rb = Gtk.Button(label=_('Refresh')); rb.connect('clicked', lambda *a: (PH.refresh(), GLib.timeout_add(1500, lambda: self.cur == 'telefoon' and self.show('telefoon'))))
        self.row(c, _('Pair phone'), _('Install the "KDE Connect" app on your Android phone or iPhone and make sure both are on the same Wi‑Fi network.'), rb, last=True)
        devs = PH.devices() if PH.running() else []
        paired = [d for d in devs if d['paired']]; others = [d for d in devs if not d['paired'] and d['reachable']]
        for d in paired:
            pc = self.card(o, d['name'])
            st = (_('Connected') if d['reachable'] else _('Unreachable')) + (_(' · battery {p0}%').format(p0=d['battery']) + (_(' (charging)') if d['charging'] else '') if d['reachable'] and d['battery'] not in (None, -1) else '')
            ub = Gtk.Button(label=_('Unpair')); ub.connect('clicked', lambda _b, i=d['id']: (PH.unpair(i), self.show('telefoon')))
            self.row(pc, _('Status'), st, ub)
            for name, title, sub in PH.PLUGINS:
                on = PH.plugin_enabled(d['id'], name)
                if on is None: continue
                self.row(pc, title, sub, self.switch(on, lambda v, i=d['id'], n=name: PH.set_plugin(i, n, v)))
            fb = Gtk.Button(label=_('Ring')); fb.set_sensitive(d['reachable']); fb.connect('clicked', lambda _b, i=d['id']: PH.ring(i))
            self.row(pc, _('Find phone'), _('Your phone rings, even when it is on silent.'), fb, last=True)
        c2 = self.card(o, _('Available devices'))
        if not PH.running(): self.row(c2, _('KDE Connect service is not running'), _('Could not start kdeconnectd.'), last=True, err=True)
        elif not others: self.row(c2, _('No devices found'), _('Open KDE Connect on your phone. Firewall: ports 1714–1764 (TCP/UDP) must be open.'), last=True)
        for k, d in enumerate(others):
            if d['pair_requested']:
                b = Gtk.Button(label=_('Accept')); b.connect('clicked', lambda _b, i=d['id']: (PH.accept(i), self.show('telefoon')))
                sub = _('Pairing request · check that this code is also shown on your phone: {p0}').format(p0=d['verification']) if d['verification'] else _('Pairing request received')
            else:
                b = Gtk.Button(label=_('Pair')); b.connect('clicked', lambda _b, i=d['id']: (PH.pair(i), GLib.timeout_add(1500, lambda: self.show('telefoon'))))
                sub = _('Ready to pair') + (_(' · code {p0}').format(p0=d['verification']) if d['verification'] else '')
            self.row(c2, d['name'], sub, b, last=k == len(others) - 1)

    def page_assistent(self, o):   # Revision 29: Polder Assistent (optional cloud LLM)
        sys.path.insert(0, os.path.join(C, 'assistant')); import llm as L
        s = S.load(); prov = s.get('assistant_provider', 'none'); models = dict(s.get('assistant_model') or {})
        c = self.card(o, _('Polder Assistant'))
        self.row(c, _('Open'), _('Super+A. Local commands (theme, volume, Wi‑Fi, apps, weather, files…) always work, without a key and without internet.'), last=True)
        c2 = self.card(o, _('AI service (optional)'))
        items = [('none', _('None (local only)'))] + [(k, v[0]) for k, v in L.PROVIDERS.items()]
        def setp(v): S.update(assistant_provider=v); self.show('assistent')
        self.row(c2, _('Service'), _('Free-form questions go to this service; the AI can perform the same system actions (it asks first before locking or turning Wi‑Fi/Bluetooth off).'), self.combo(items, prov, setp), last=prov == 'none')
        if prov == 'none':
            self.row(c2, _('Local model'), _('A local model (e.g. via Ollama) is not supported yet.'), last=True); return
        key = L.get_key(prov)
        ke = Gtk.Entry(); ke.set_visibility(False); ke.set_width_chars(28); ke.set_placeholder_text(_('Paste API key')); ke.set_text(key)
        where = _('GNOME keyring') if L._secret_ok() else _('~/.config/osb/assistant-keys (only you can read it)')
        self.row(c2, _('API key'), (_('Set') if key else _('Not set yet')) + _(' · stored in {where}').format(where=where), ke)
        me = Gtk.Entry(); me.set_width_chars(24); me.set_text(models.get(prov) or L.PROVIDERS[prov][1])
        self.row(c2, _('Model'), _('Default: {p0}').format(p0=L.PROVIDERS[prov][1]), me)
        bb = Gtk.Box(spacing=8); sb = Gtk.Button(label=_('Save')); sb.get_style_context().add_class('btn'); sb.get_style_context().add_class('primary')
        tb = Gtk.Button(label=_('Test')); tb.get_style_context().add_class('btn'); bb.pack_start(sb, False, False, 0); bb.pack_start(tb, False, False, 0)
        self.a_status = getattr(self, 'a_status', ('', False))
        self.row(c2, _('Connection'), self.a_status[0] or _('Test makes one small real API call.'), bb, last=True, err=self.a_status[1])
        def save(*a, rerender=True):
            k = ke.get_text().strip(); models[prov] = me.get_text().strip() or L.PROVIDERS[prov][1]
            S.update(assistant_model=models); w = L.set_key(prov, k)
            self.a_status = ((_('Key stored in ') + ('sleutelbos' if w == 'sleutelbos' else 'bestand')) if k else _('Key removed'), False)
            if rerender: self.show('assistent')
        def test(*a):
            save(rerender=False); tb.set_sensitive(False); tb.set_label(_('Testing…'))
            def work():
                ok, msg = L.test(prov, models[prov], L.get_key(prov)) if L.get_key(prov) else (False, _('No key entered.'))
                def done(): self.a_status = (('✓ ' if ok else '✗ ') + msg, not ok); self.cur == 'assistent' and self.show('assistent')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        sb.connect('clicked', save); tb.connect('clicked', test)

    def page_sync(self, o):   # Revision 30: Polder Sync
        sys.path.insert(0, os.path.join(C, 'sync')); import polder_sync as Y
        s = S.load(); c = Y.cfg(); st = Y.load_state()
        k = self.card(o, _('Polder Sync'))
        self.row(k, _('Synchronize'), _('Theme, accent, wallpaper, notifications, lock, clock, keyboard, pinned apps, web apps, weather location, calendar links, assistant service and Store apps. Never: API keys, passphrase, clipboard.'),
                 self.switch(c['enabled'], lambda v: (S.update(sync_enabled=v), self.show('sync'))))
        if getattr(self, 'sync_busy', False): status = _('Syncing…'); err = False
        elif st.get('last_error'): status = _('Error: ') + st['last_error']; err = True
        else: status = (_('Last: {p0} · {p1}').format(p0=ago(st.get('last_sync')), p1=st.get('last_result', '')) if st.get('last_sync') else _('Never synced')); err = False
        bb = Gtk.Box(spacing=8)
        nb = Gtk.Button(label=_('Sync now')); nb.get_style_context().add_class('btn'); nb.get_style_context().add_class('primary')
        rb = Gtk.Button(label=_('Restore from another PC')); rb.get_style_context().add_class('btn')
        for b in (nb, rb): b.set_sensitive(not getattr(self, 'sync_busy', False)); bb.pack_start(b, False, False, 0)
        self.row(k, _('Status'), status, bb, last=True, err=err)
        def run(restore):
            if restore:
                d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                      text=_('Take over settings from your other PC?'))
                d.format_secondary_text(_('All synced settings will be replaced by the stored version. A backup is made first.'))
                r = d.run(); d.destroy()
                if r != Gtk.ResponseType.OK: return
            self.sync_busy = True; self.show('sync')
            def work():
                Y.sync_safe(restore)
                def done(): self.sync_busy = False; self.cur == 'sync' and self.show('sync')
                GLib.idle_add(done)
            threading.Thread(target=work, daemon=True).start()
        nb.connect('clicked', lambda *a: run(False)); rb.connect('clicked', lambda *a: run(True))

        k2 = self.card(o, _('Storage'))
        self.row(k2, _('Where'), _('A folder (Nextcloud, Dropbox, rclone mount, USB) or a private git repo (GitHub).'),
                 self.combo([('folder', _('Folder')), ('git', _('Git / GitHub'))], c['backend'], lambda v: (S.update(sync_backend=v), self.show('sync'))))
        if c['backend'] == 'folder':
            fb = Gtk.Button(label=_('Choose…')); fb.get_style_context().add_class('btn')
            def pick(*a):
                d = Gtk.FileChooserDialog(title=_('Choose sync folder'), transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
                d.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Choose'), Gtk.ResponseType.OK)
                if d.run() == Gtk.ResponseType.OK: S.update(sync_folder=d.get_filename())
                d.destroy(); self.show('sync')
            fb.connect('clicked', pick)
            self.row(k2, _('Folder'), (c['folder'] or _('No folder chosen yet')) + _(' · files go into the polder-sync/ subfolder'), fb, last=True)
        else:
            ue = Gtk.Entry(); ue.set_width_chars(30); ue.set_text(c['git_url']); ue.set_placeholder_text('https://github.com/naam/polder-sync.git')
            ue.connect('activate', lambda e: (S.update(sync_git_url=e.get_text().strip()), self.show('sync')))
            ue.connect('focus-out-event', lambda e, ev: S.update(sync_git_url=e.get_text().strip()) and False)
            self.row(k2, _('Repository URL'), _('Use a PRIVATE repo. Enter = save.'), ue)
            gh = shutil.which('gh')
            authed = gh and subprocess.run(['gh', 'auth', 'status'], capture_output=True, timeout=10).returncode == 0
            gb = Gtk.Box(spacing=8)
            lb = Gtk.Button(label=_('Sign in to GitHub')); lb.get_style_context().add_class('btn')
            lb.connect('clicked', lambda *a: subprocess.Popen(['xfce4-terminal', '--title', _('GitHub sign-in'), '-x', 'sh', '-c',
                       'gh auth login --web -h github.com -p https && gh auth setup-git; echo; echo "$1"; read x', 'sh', _('Done, you can close this window.')]))
            cb = Gtk.Button(label=_('Create private repo')); cb.get_style_context().add_class('btn'); cb.set_sensitive(bool(authed))
            def create(*a):
                r = subprocess.run(['gh', 'repo', 'create', 'polder-sync', '--private', '--description', _('Polder OS settings (Polder Sync)')], capture_output=True, text=True, timeout=60)
                login = subprocess.run(['gh', 'api', 'user', '-q', '.login'], capture_output=True, text=True, timeout=30).stdout.strip()
                if login and (r.returncode == 0 or 'already exists' in r.stderr): S.update(sync_git_url=f'https://github.com/{login}/polder-sync.git')
                else: self.sync_note = _('Creating repo failed: ') + r.stderr.strip()[-200:]
                self.show('sync')
            cb.connect('clicked', create)
            for b in (lb, cb): gb.pack_start(b, False, False, 0)
            sub = (_('Signed in to GitHub (gh).') if authed else _('Sign in through your browser with a code (GitHub device login).')) if gh else _('GitHub CLI (gh) is not installed.')
            if getattr(self, 'sync_note', ''): sub += ' ' + self.sync_note
            self.row(k2, _('GitHub'), sub, gb if gh else None, last=True)

        k3 = self.card(o, _('Encryption'))
        self.row(k3, _('Encrypt with passphrase'), _('Everything is encrypted on this PC (scrypt + AES/Fernet) before it reaches the folder or repo. Without the passphrase nobody can read it, not even you.'),
                 self.switch(c['encrypt'], lambda v: (S.update(sync_encrypt=v), self.show('sync'))), last=not c['encrypt'])
        if c['encrypt']:
            pe = Gtk.Entry(); pe.set_visibility(False); pe.set_width_chars(22); pe.set_placeholder_text(_('Passphrase')); pe.set_text(Y.get_pass())
            sb = Gtk.Button(label=_('Save')); sb.get_style_context().add_class('btn')
            box = Gtk.Box(spacing=8); box.pack_start(pe, False, False, 0); box.pack_start(sb, False, False, 0)
            sb.connect('clicked', lambda *a: (Y.set_pass(pe.get_text()), self.show('sync')))
            self.row(k3, _('Passphrase'), (_('Set') if Y.get_pass() else _('Not set yet')) + _(' · use the same passphrase on every PC. It is never synced.'), box, last=True)

        miss = Y.missing_store_apps()
        if miss:
            k4 = self.card(o, _('Apps from your other PC'))
            ib = Gtk.Button(label=_('Install')); ib.get_style_context().add_class('btn')
            debs = [a['id'] for a in miss if a.get('source') != 'Flathub']; flats = [a['id'] for a in miss if a.get('source') == 'Flathub']
            cmd = ' && '.join(([f"pkexec apt-get install -y {' '.join(debs)}"] if debs else []) + ([f"pkexec flatpak install --system -y flathub {' '.join(flats)}"] if flats else []))
            ib.connect('clicked', lambda *a: subprocess.Popen(['xfce4-terminal', '--title', _('Restore apps'), '-x', 'sh', '-c', cmd + '; echo; echo "$1"; read x', 'sh', _('Done.')]))
            self.row(k4, _('{p0} app(s) not installed yet').format(p0=len(miss)), ', '.join(a.get('name', a['id']) for a in miss), ib, last=True)
        import glob as _g
        nb2 = len(_g.glob(os.path.join(Y.BACKUPS, '*.json')))
        k5 = self.card(o, _('Backups'))
        ob = Gtk.Button(label=_('Open folder')); ob.get_style_context().add_class('btn'); ob.connect('clicked', lambda *a: subprocess.Popen(['xdg-open', Y.BACKUPS]))
        self.row(k5, _('{nb2} backup(s)').format(nb2=nb2), _('Before every sync that overwrites something, your old state is kept (last 10). For each setting the newest change wins.'), ob if nb2 else None, last=True)

    def page_safeharbor(self, o):   # Polder SafeHarbor: herstelpunten (btrfs + snapper), see docs/safeharbor.md
        st = getattr(self, 'sh_status', None)
        if st is None:
            c = self.card(o, _('SafeHarbor')); self.row(c, _('Getting status…'), None, last=True)
            def work():
                st = self.sh_call('status') or {'available': False, 'reason': _('SafeHarbor is not installed on this system.')}
                GLib.idle_add(lambda: (setattr(self, 'sh_status', st), self.cur == 'safeharbor' and self.show('safeharbor')))
            threading.Thread(target=work, daemon=True).start(); return
        self.sh_status = None   # refresh on the next visit
        c = self.card(o, _('SafeHarbor'))
        ob = Gtk.Button(label=_('Open')); ob.get_style_context().add_class('btn')
        ob.connect('clicked', lambda *a: subprocess.Popen(['polder-safeharbor'], start_new_session=True))
        if not st.get('available'):
            self.row(c, _('Not available'), st.get('reason') or '', None)
            self.row(c, _('What is SafeHarbor?'), _('Polder OS automatically creates a restore point before every update, so you can go back with one click. For this, Polder OS must be installed on a btrfs disk with the SafeHarbor layout.'), last=True)
            return
        snaps = st.get('snapshots') or []
        last = snaps[-1] if snaps else None
        if st.get('failed_boot'): self.row(c, _('The previous boot did not succeed'), _('Open SafeHarbor to restore an earlier version.'), err=True)
        if st.get('booted_snapshot') is not None:
            self.row(c, _('You are using an earlier version (restore point {p0})').format(p0=st['booted_snapshot']), _('Read-only. Open SafeHarbor to make it your permanent version.'), err=True)
        self.row(c, _('Restore points'), (_('{p0} kept · latest: {p1} ({p2})').format(p0=len(snaps), p1=last['description'], p2=last['date'][:16]) if last else _('No restore points yet.')), ob)
        def auto(v):
            threading.Thread(target=lambda: (self.sh_call('set-auto', 'on' if v else 'off'), GLib.idle_add(lambda: self.show('safeharbor'))), daemon=True).start()
        self.row(c, _('Restore point before every update'), _('Also for automatic updates and Polder updates.'), self.switch(bool(st.get('auto', True)), auto))
        ret = int(st.get('retention') or 10)
        opts = sorted({3, 5, 10, 20, 30, ret})
        def retention(v):
            threading.Thread(target=lambda: (self.sh_call('set-retention', v), GLib.idle_add(lambda: self.show('safeharbor'))), daemon=True).start()
        self.row(c, _('Number of restore points to keep'), _('Older points are cleaned up automatically.'), self.combo([(n, _('{n} restore points').format(n=n)) for n in opts], ret, retention), last=True)

    def sh_call(self, *args):
        cmd = (os.environ.get('POLDER_SAFEHARBOR_HELPER') or 'pkexec /usr/libexec/polder-safeharbor-helper').split()
        if not os.environ.get('POLDER_SAFEHARBOR_HELPER') and not os.path.exists('/usr/libexec/polder-safeharbor-helper'): return None
        try:
            r = subprocess.run(cmd + [str(a) for a in args], capture_output=True, text=True, timeout=60)
            return json.loads(r.stdout) if r.returncode == 0 else None
        except Exception: return None

    def page_over(self, o):
        c = self.card(o, _('About Polder OS'))
        mem = {l.split(':')[0]: int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith(('MemTotal', 'MemAvailable'))}
        deb = open('/etc/debian_version').read().strip() if os.path.exists('/etc/debian_version') else '?'
        pretty = next((l.split('=', 1)[1].strip().strip('"') for l in open('/etc/os-release') if l.startswith('PRETTY_NAME')), '')
        scr = Gdk.Screen.get_default()
        hdr = Gtk.Box(spacing=16); hdr.set_border_width(18)
        hdr.pack_start(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(C, 'brand', 'polderos-logo.png'), 64, 64, True)), False, False, 0)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        l = Gtk.Label(label=S.VERSION, xalign=0); l.get_style_context().add_class('h1'); tb.pack_start(l, False, False, 0)
        l2 = Gtk.Label(label=_('A ChromeOS-like Linux desktop, built on Debian'), xalign=0); l2.get_style_context().add_class('rsub'); tb.pack_start(l2, False, False, 0)
        hdr.pack_start(tb, False, False, 0); c.pack_start(hdr, False, False, 0)
        self.row(c, _('Base'), f'{pretty} (debian_version {deb}) · ISO: NAME="Polder OS", ID=polderos, ID_LIKE=debian')
        self.row(c, _('Kernel'), platform.release())
        self.row(c, _('Memory'), _('{p0:.1f} GB total · {p1:.1f} GB available').format(p0=mem['MemTotal'] / 1048576, p1=mem['MemAvailable'] / 1048576))
        self.row(c, _('Display'), f'{scr.get_width()} × {scr.get_height()}')
        wb = Gtk.Button(label=_('Open')); wb.connect('clicked', lambda *x: subprocess.Popen([sys.executable, os.path.join(C, 'welcome', 'welkom.py')], start_new_session=True))
        self.row(c, _('Welcome to Polder OS'), _('Watch the first-run tour again.'), wb, last=True)
        self.updates_card(o)

    def updates_card(self, o):   # Revision 26: automatic updates
        import updates as U
        c = self.card(o, _('Updates'))
        en = U.auto_enabled()
        if en is None: self.row(c, _('Automatic updates'), _('unattended-upgrades is not set up on this system (it is in the Polder OS ISO).'))
        else:
            def toggle(v):
                def work():
                    ok = U.set_auto(v); GLib.idle_add(lambda: (setattr(self, 'upd_msg', None if ok else _('Change failed (no permission).')), self.show('over')))
                threading.Thread(target=work, daemon=True).start()
            self.row(c, _('Automatic updates'), _('Install security and stable updates at night (unattended-upgrades) and update Flatpak apps daily.'), self.switch(en, toggle))
        lu = U.last_update()
        self.row(c, _('Last updated'), time.strftime('%d-%m-%Y %H:%M', time.localtime(lu[0])) + _(' (source: {p0})').format(p0=lu[1]) if lu else _('Never (no update history found)'))
        rb = U.reboot_required()
        if rb: self.row(c, _('Restart required'), _('Updates have been installed; restart to use them.'), err=True)
        nb = Gtk.Button(label=_('Check now'))
        def check(*a):
            self.upd_msg = _('Checking…'); self.show('over')
            def done(r):
                parts = []
                if r['apt'] is not None: parts.append(_('{p0} Debian update(s)').format(p0=r['apt']))
                if r['flatpak'] is not None: parts.append(_('{p0} Flatpak update(s)').format(p0=r['flatpak']))
                msg = ', '.join(parts) or _('Check failed')
                if r['error'] and r['apt'] is None: msg += f" · {r['error'][:90]}"
                GLib.idle_add(lambda: (setattr(self, 'upd_msg', msg + ' · ' + time.strftime('%H:%M')), self.cur == 'over' and self.show('over')))
            U.check(done)
        nb.connect('clicked', check)
        self.row(c, _('Check for updates'), getattr(self, 'upd_msg', None) or _('Via PackageKit (Debian) and Flatpak.'), nb)
        sb = Gtk.Button(label=_('Open')); sb.connect('clicked', lambda *a: subprocess.Popen([sys.executable, os.path.join(C, 'store', 'store.py'), 'updates'], start_new_session=True))
        self.row(c, _('Updates in Polder Store'), _('View and install available updates.'), sb, last=True)

    def quit(self, *a):
        try: os.remove(PID)
        except OSError: pass
        Gtk.main_quit()

signal.signal(signal.SIGTERM, lambda *a: Gtk.main_quit())
App(sys.argv[1] if len(sys.argv) > 1 else 'personalisatie'); Gtk.main()
