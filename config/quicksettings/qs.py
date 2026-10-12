#!/usr/bin/env python3
"""ChromeOS-style Quick Settings panel (GTK3). Toggle: run again -> closes existing (pidfile)."""
import os, sys, signal, shutil, subprocess, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify'))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'osb')); import rgba as RGBA   # Rev 29.2: real rounded corners
import osbnotify as N
try:
    from importlib.machinery import SourceFileLoader
    ND = SourceFileLoader('ndaemon', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify', 'osb-notifyd.py')).load_module()
except Exception as e:
    ND = None; print('notify module', e)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb')); import layershell as LSH   # Rev 32d
PID = os.path.join(LSH.rundir(), 'osb-qs.pid')
W, H, MARGIN_R, SHELF = 420, 0, 10, 62
GAP = 8; TOP_MARGIN = 10

# toggle behaviour
if os.path.exists(PID):
    try: os.kill(int(open(PID).read()), signal.SIGTERM); os.remove(PID); sys.exit(0)
    except Exception: os.remove(PID)
open(PID, 'w').write(str(os.getpid()))
# mutually exclusive with the calendar popup
if os.path.exists('/tmp/osb-cal.pid'):
    try: os.kill(int(open('/tmp/osb-cal.pid').read()), signal.SIGTERM)
    except Exception: pass

def have(c): return shutil.which(c) is not None
def run(*a): subprocess.Popen(a, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def battery():
    import glob
    b = glob.glob('/sys/class/power_supply/BAT*')
    if b: return open(b[0] + '/capacity').read().strip() + '%'
    return None   # no battery -> show nothing

def wifi_state():
    if have('nmcli'):
        o = subprocess.run(['nmcli', 'radio', 'wifi'], capture_output=True, text=True).stdout.strip()
        return o == 'enabled', 'Verbonden' if o == 'enabled' else 'Uit', False
    return True, 'Thuisnetwerk (demo)', True

sys.path.insert(0, os.path.join(HERE, '..', 'osb')); import osbsettings as OSBS, mpris
SET = OSBS.load()
SETTINGS_APP = os.path.join(HERE, '..', 'settings', 'instellingen.py')
def kbd_name():
    return next((n for l, v, n in OSBS.LAYOUTS if l == SET['kbd_layout'] and v == SET.get('kbd_variant', '')), SET['kbd_layout'].upper())
# tiles: (key, icon, title, subtitle, active, wide) -- only tiles that really do something in this session
TILES = []
if have('nmcli'): TILES.append(('wifi', 'network-wireless-signal-excellent-symbolic', 'Wifi', None, True, True))
if have('bluetoothctl'): TILES.append(('bt', 'bluetooth-active-symbolic', 'Bluetooth', None, False, True))
TILES += [
    ('night', 'daytime-sunset-symbolic', 'Nachtlicht', 'Aan' if SET['night_light'] else 'Uit', SET['night_light'], True),
    ('dark', 'weather-clear-night-symbolic', 'Donker thema', {'auto': 'Automatisch', 'dark': 'Aan', 'light': 'Uit'}[SET['theme']], OSBS.effective_theme(SET) == 'dark', True),
    ('kbd', 'input-keyboard-symbolic', 'Toetsenbord', kbd_name(), False, True),
    ('cap', 'camera-photo-symbolic', 'Schermopname', 'Screenshot of video', False, True),
    ('dnd', 'notifications-disabled-symbolic', 'Niet storen', None, N.load().get('dnd', False), True),
]
# Revision 28: 'Telefoon' tile only when a phone is paired (KDE Connect); battery % from the daemon, never invented
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb')); import phone as PH
    _ph = next((d for d in PH.devices() if d['paired']), None) if PH.running() else None
except Exception: _ph = None
if _ph:
    TILES.append(('phone', 'phone-symbolic', _ph['name'], (f"{_ph['battery']}%" if _ph['reachable'] and _ph['battery'] not in (None, -1) else ('Verbonden' if _ph['reachable'] else 'Niet bereikbaar')), _ph['reachable'], True))
PAGES = [TILES]

class QS(Gtk.Window):
    dialog_open = False
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG); self.set_name('qswin'); RGBA.enable(self)
        scr = Gdk.Screen.get_default(); sw, sh = scr.get_width(), scr.get_height()  # fine for X11 single monitor
        self.x, self.y = sw - W - MARGIN_R, sh - SHELF - H
        self.set_size_request(W, -1); self.set_resizable(False)
        if not LSH.setup(self, 'polder-quicksettings', layer='overlay', anchors=('right', 'bottom'), margins={'right': MARGIN_R, 'bottom': SHELF}, exclusive=0, keyboard='on_demand'):
            self.move(self.x, self.y)
        css = Gtk.CssProvider(); css.load_from_path(os.path.join(HERE, 'qs.css'))
        Gtk.StyleContext.add_provider_for_screen(scr, css, 800)
        if ND:
            nc = Gtk.CssProvider(); nc.load_from_data(ND.CSS.encode()); Gtk.StyleContext.add_provider_for_screen(scr, nc, 801)
        self.connect('key-press-event', lambda w, e: e.keyval == Gdk.KEY_Escape and self.quit())
        self.connect('focus-out-event', lambda *a: GLib.timeout_add(150, self.maybe_quit))
        self.connect('destroy', lambda *a: self.quit())
        self.histdata = N.load()['history'][::-1] if ND else []
        self.compact = bool(self.histdata)
        self.col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=GAP); self.add(self.col)
        self.histbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); self.col.pack_start(self.histbox, False, False, 0)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); panel.set_name('panel')
        self.col.pack_start(panel, False, False, 0)
        # header
        hdr = Gtk.Box(spacing=8)
        d = datetime.date.today(); dn = ['ma','di','wo','do','vr','za','zo'][d.weekday()]
        mn = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'][d.month-1]
        hdr.pack_start(self.pill(f'{dn} {d.day} {mn}', 'x-office-calendar-symbolic'), False, False, 0)
        hdr.pack_end(self.pill(OSBS.VERSION, None), False, False, 0)
        if os.path.exists('/tmp/osb-update.json'):   # Revision 26: ChromeOS 'Update' pill -> reboot (ISO) after confirmation via notification action
            up = self.pill('Update', 'go-up-symbolic'); up.get_style_context().add_class('active'); up.set_tooltip_text('Opnieuw opstarten om bij te werken')
            up.connect('clicked', lambda *a: (subprocess.Popen(['systemctl', 'reboot']) if os.environ.get('POLDEROS_ISO') else print('update pill: reboot (prototype: skipped)', flush=True)))
            hdr.pack_end(up, False, False, 0)
        panel.pack_start(hdr, False, False, 0)
        # Revision 18: MPRIS media card (only when a player has something playing/paused; hidden otherwise)
        P = N.palette(); mc = Gtk.CssProvider(); mc.load_from_data(f'''
#media {{ background: {P['SURFACE_VARIANT']}; border-radius: 18px; padding: 10px 12px; }}
.mart {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; border-radius: 12px; min-width: 48px; min-height: 48px; }}
.mtitle {{ font-weight: 500; font-size: 14px; color: {P['ON_SURFACE']}; }}
.msub {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
.mbtn {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; min-width: 36px; min-height: 36px; padding: 0; color: {P['ON_SURFACE']}; }}
.mbtn:hover {{ background: {P['OUTLINE']}; }}
.mbtn.pp {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; }}
'''.encode()); Gtk.StyleContext.add_provider_for_screen(scr, mc, 805)
        self.mediabox = Gtk.Box(); panel.pack_start(self.mediabox, False, False, 0); self.msig = None
        self.refresh_media(); GLib.timeout_add(1000, self.refresh_media)
        # tiles + pagination
        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        for i, page in enumerate(PAGES):
            g = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
            r = c = 0
            for t in page:
                w = self.tile(*t)
                if t[5]:
                    g.attach(w, c, r, 1, 1); c += 1
                else:
                    g.attach(w, c, r, 1, 1); c += 1
                if c == 2: c, r = 0, r + 1
            self.stack.add_named(g, str(i))
        dots = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER); self.dots = []
        if self.compact:  # ChromeOS-like: collapse tiles to one row of round toggles when notifications exist
            row = Gtk.Box(spacing=8, homogeneous=True)
            for t in PAGES[0]:
                act = t[4] if t[0] != 'wifi' else wifi_state()[0]
                b = Gtk.ToggleButton(); b.set_active(act); b.get_style_context().add_class('tile'); b.get_style_context().add_class('mini')
                b.add(Gtk.Image.new_from_icon_name(t[1], Gtk.IconSize.MENU)); b.set_tooltip_text(t[2])
                b.connect('toggled', self.on_toggle, t[0]); row.pack_start(b, True, True, 0)
            panel.pack_start(row, False, False, 0)
        else:
            panel.pack_start(self.stack, False, False, 0)
        for i in range(len(PAGES)):
            b = Gtk.Button(); b.get_style_context().add_class('dot'); b.connect('clicked', self.page, i)
            dots.pack_start(b, False, False, 0); self.dots.append(b)
        self.page(None, 0)
        if not self.compact and len(PAGES) > 1: panel.pack_start(dots, False, False, 0)
        # sliders
        if have('pactl') or have('amixer'):   # no audio stack in this session -> no fake slider
            panel.pack_start(self.slider('audio-volume-high-symbolic', 70, self.set_vol, None), False, False, 0)
        panel.pack_start(self.slider('display-brightness-symbolic', self.cur_bri(), self.set_bri, None), False, False, 0)
        # footer
        ft = Gtk.Box(spacing=8); ft.set_name('footer')
        ft.pack_start(self.round_btn('system-shutdown-symbolic', self.power_menu), False, False, 0)
        ft.pack_start(self.round_btn('system-lock-screen-symbolic', self.lock), False, False, 0)
        av = Gtk.Label(label='K'); av.get_style_context().add_class('avatar'); ft.pack_start(av, False, False, 0)
        bt = battery()
        if bt: bl = Gtk.Label(label=bt); bl.get_style_context().add_class('battery'); ft.pack_start(bl, False, False, 4)
        ft.pack_end(self.round_btn('emblem-system-symbolic', lambda *a: (run('python3', SETTINGS_APP), self.quit())), False, False, 0)
        panel.pack_end(ft, False, False, 0)
        self.panel = panel; self.sw, self.sh = sw, sh; self.hist = None
        self.show_all(); self.layout()
        self.present()
        self.connect('button-press-event', self.on_press); self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        GLib.timeout_add(300, self.grab)
        try: N.call('MarkRead')
        except Exception as e: print('notify svc', e)

    def make_backdrop(self):
        """Rounded corners without compositor: window bg = wallpaper crop behind the column."""
        if not hasattr(self, 'bgcss'):
            self.bgcss = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.bgcss, 900)
        if RGBA.active(self): self.bgcss.load_from_data(b'#qswin { background: transparent; background-image: none; }'); return
        wp = os.path.join(HERE, '..', 'wallpaper.png'); out = f'/tmp/osb-qs-bg-{self.H}.png'
        subprocess.run(['convert', wp, '-crop', f'{self.W}x{self.H}+{self.x}+{self.y}', '+repage', out])
        if not hasattr(self, 'bgcss'):
            self.bgcss = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.bgcss, 900)
        self.bgcss.load_from_data(f"#qswin {{ background-image: url('{out}'); background-color: transparent; }}".encode())

    def pill(self, text, icon):
        b = Gtk.Button(); b.get_style_context().add_class('pill')
        bx = Gtk.Box(spacing=6)
        if icon: bx.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        bx.pack_start(Gtk.Label(label=text), False, False, 0); b.add(bx); return b

    def tile(self, key, icon, title, sub, active, wide):
        if key == 'wifi':
            active, sub, _ = wifi_state()
        b = Gtk.ToggleButton(); b.set_active(active); sc = b.get_style_context(); sc.add_class('tile')
        if not wide: sc.add_class('small')
        bx = Gtk.Box(spacing=10)
        ic = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR); bx.pack_start(ic, False, False, 0)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0); t.set_ellipsize(3); t.set_max_width_chars(14); t.get_style_context().add_class('title'); tb.pack_start(t, False, False, 0)
        if sub:
            s = Gtk.Label(label=sub, xalign=0); s.set_ellipsize(3); s.set_max_width_chars(14); s.get_style_context().add_class('sub'); tb.pack_start(s, False, False, 0)
        bx.pack_start(tb, True, True, 0)
        b.add(bx); b.connect('toggled', self.on_toggle, key); return b

    def layout(self):
        """One column: [notification card (scrollable)] GAP [QS panel]; same width/right edge, fits above shelf."""
        for c in self.histbox.get_children(): c.destroy()
        self.histbox.hide()
        self.W = W
        ph = self.panel.get_preferred_height()[1]
        avail = self.sh - SHELF - TOP_MARGIN - ph - GAP
        if self.histdata:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); card.set_name('histcard')
            hdr = Gtk.Box()
            l = Gtk.Label(label=f'Meldingen ({len(self.histdata)})', xalign=0); l.get_style_context().add_class('histtitle')
            hdr.pack_start(l, True, True, 0)
            cb = Gtk.Button(label='Alles wissen'); cb.get_style_context().add_class('pill'); cb.connect('clicked', self.clear_all)
            hdr.pack_end(cb, False, False, 0); card.pack_start(hdr, False, False, 0)
            lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            for n in self.histdata: lst.pack_start(ND.build_card(n, self.dismiss, self.activate, inner=True), False, False, 0)
            sc = Gtk.ScrolledWindow(); sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); sc.add(lst)
            sc.set_propagate_natural_height(True)
            sc.set_max_content_height(max(90, avail - 32 - 52))  # minus card padding + header
            card.pack_start(sc, True, True, 0)
            self.histbox.pack_start(card, False, False, 0); self.histbox.show_all()
        self.resize(W, 1)
        self.H = self.get_preferred_size()[1].height
        self.x, self.y = self.sw - W - MARGIN_R, self.sh - SHELF - self.H
        if not LSH.active(self): self.move(self.x, self.y)
        self.make_backdrop()

    def clear_all(self, *a):
        try: N.call('ClearAll')
        except Exception: pass
        self.histdata = []; self.layout()

    def dismiss(self, nid):
        try: N.call('Dismiss', GLib.Variant('(u)', (nid,)))
        except Exception: pass
        self.histdata = [h for h in self.histdata if h['id'] != nid]; self.layout()

    def activate(self, nid, key):
        """Card body (key='default') or action button clicked: daemon emits ActionInvoked/opens app."""
        try: N.call('Invoke', GLib.Variant('(us)', (nid, key)))
        except Exception as e: print('invoke', e)
        self.quit()

    def on_toggle(self, b, key):
        on = b.get_active()
        if key == 'dnd':
            try: N.call('SetDnd', GLib.Variant('(b)', (on,)))
            except Exception as e: print('dnd', e)
        if key == 'wifi' and have('nmcli'): run('nmcli', 'radio', 'wifi', 'on' if on else 'off')
        elif key == 'bt' and have('bluetoothctl'): run('bluetoothctl', 'power', 'on' if on else 'off')
        elif key == 'cap' and have('import'):
            self.quit(); run('sh', '-c', 'sleep 0.4; exec python3 "$0"', os.path.join(HERE, '..', 'capture', 'capture.py'))   # Revision 18: capture bar
        elif key == 'night': OSBS.update(night_light=on)            # osb-settingsd applies xrandr gamma
        elif key == 'dark': OSBS.update(theme='dark' if on else 'light')  # osb-settingsd regenerates + reloads everything
        elif key == 'kbd': self.quit(); run('python3', SETTINGS_APP, 'toetsenbord')
        elif key == 'phone': self.quit(); run('python3', SETTINGS_APP, 'telefoon')

    def slider(self, icon, val, cb, trailing):
        row = Gtk.Box(spacing=8)
        ov = Gtk.Overlay(); ov.get_style_context().add_class('sliderwrap')
        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1); s.set_value(val); s.set_draw_value(False)
        s.set_hexpand(True); s.connect('value-changed', lambda w: cb(int(w.get_value()))); ov.add(s)
        knob = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU); knob.set_halign(Gtk.Align.START)
        knob.set_margin_start(14); knob.get_style_context().add_class('knobicon'); knob.set_can_focus(False)
        ov.add_overlay(knob); ov.set_overlay_pass_through(knob, True)
        row.pack_start(ov, True, True, 0)
        if trailing: row.pack_start(self.round_btn(trailing, None), False, False, 0)
        return row

    def round_btn(self, icon, cb):
        b = Gtk.Button(); b.get_style_context().add_class('round')
        b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        if cb: b.connect('clicked', cb)
        return b

    def page(self, b, i):
        self.stack.set_visible_child_name(str(i))
        for j, d in enumerate(self.dots):
            (d.get_style_context().add_class if j == i else d.get_style_context().remove_class)('on')

    def set_vol(self, v):
        if have('pactl'): run('pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{v}%')
        elif have('amixer'): run('amixer', 'set', 'Master', f'{v}%')
    def output(self):
        o = subprocess.run(['xrandr', '-q'], capture_output=True, text=True, timeout=5).stdout
        return next((l.split()[0] for l in o.splitlines() if ' connected' in l), None)
    def cur_bri(self):
        try:
            o = subprocess.run(['xrandr', '--verbose'], capture_output=True, text=True, timeout=5).stdout
            return int(float(next(l.split()[1] for l in o.splitlines() if 'Brightness:' in l)) * 100)
        except Exception: return 100
    def set_bri(self, v):
        # hardware backlight if present, else real software brightness via xrandr (keeps night-light gamma)
        if have('brightnessctl') and os.listdir('/sys/class/backlight') if os.path.isdir('/sys/class/backlight') else False:
            run('brightnessctl', 'set', f'{v}%')
        elif self.output():
            g = ['--gamma', '1:0.82:0.64'] if OSBS.load().get('night_light') else []
            run('xrandr', '--output', self.output(), '--brightness', f'{max(v, 20) / 100:.2f}', *g)

    def lock(self, *a):
        self.quit()   # Polder OS lock screen (lock/lock.py, PAM); started after QS is gone so it can grab input
        subprocess.Popen(['sh', '-c', 'sleep 0.3; exec "$0"', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lock', 'lock-now.sh')], start_new_session=True)

    def power_menu(self, *a):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text='Wat wil je doen?')
        d.add_buttons('Annuleren', 0, 'Afmelden', 1, 'Opnieuw opstarten', 2, 'Uitschakelen', 3)
        self.dialog_open = True; r = d.run(); d.destroy(); self.dialog_open = False; self.grab()
        # SAFETY: prototype never really powers off the box; ISO version maps to systemctl.
        if r in (1, 2, 3): print('would run:', {1: 'logout', 2: 'systemctl reboot', 3: 'systemctl poweroff'}[r])
        if r in (1, 2, 3) and os.environ.get('POLDEROS_ISO'):   # real system (ISO session): actually do it
            subprocess.Popen({1: ['sh', '-c', 'loginctl terminate-session "$XDG_SESSION_ID"'], 2: ['systemctl', 'reboot'], 3: ['systemctl', 'poweroff']}[r])

    def grab(self):
        # xfwm4 doesn't move focus on a bare-desktop click, so grab the pointer (owner_events keeps our widgets working)
        Gdk.Display.get_default().get_default_seat().grab(self.get_window(), Gdk.SeatCapabilities.ALL_POINTING, True, None, None, None, None)
        return False

    def on_press(self, w, e):
        win = self.get_window(); ox, oy = win.get_origin()[1:]
        if not (ox <= e.x_root < ox + win.get_width() and oy <= e.y_root < oy + win.get_height()) and not self.dialog_open: self.quit()
        return False

    def refresh_media(self):
        m = mpris.active()
        sig = m and (m['name'], m['status'], m['title'], m['artist'], m['art'])
        if sig == self.msig: return True
        first = self.msig is None; self.msig = sig
        for c in self.mediabox.get_children(): c.destroy()
        if m:
            card = Gtk.Box(spacing=12); card.set_name('media'); card.set_hexpand(True)
            if m['art'] and os.path.isfile(m['art']):
                from gi.repository import GdkPixbuf
                art = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(m['art'], 48, 48, True))
            else:
                art = Gtk.Image.new_from_icon_name('audio-x-generic-symbolic', Gtk.IconSize.LARGE_TOOLBAR); art.get_style_context().add_class('mart')
            card.pack_start(art, False, False, 0)
            tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            for txt, cls in ((m['title'] or 'Onbekende titel', 'mtitle'), (' · '.join(x for x in (m['artist'], m['app']) if x), 'msub')):
                l = Gtk.Label(label=txt, xalign=0); l.set_ellipsize(3); l.set_max_width_chars(20); l.get_style_context().add_class(cls); tb.pack_start(l, False, False, 0)
            card.pack_start(tb, True, True, 0)
            for icon, meth, ok in (('media-skip-backward-symbolic', 'Previous', m['can_prev']),
                                   ('media-playback-pause-symbolic' if m['status'] == 'Playing' else 'media-playback-start-symbolic', 'PlayPause', True),
                                   ('media-skip-forward-symbolic', 'Next', m['can_next'])):
                b = Gtk.Button(); b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)); b.get_style_context().add_class('mbtn')
                if meth == 'PlayPause': b.get_style_context().add_class('pp'); b.set_tooltip_text('Pauzeren' if m['status'] == 'Playing' else 'Afspelen')
                else: b.set_tooltip_text('Vorige' if meth == 'Previous' else 'Volgende')
                b.set_sensitive(ok); b.set_valign(Gtk.Align.CENTER)
                b.connect('clicked', lambda _b, meth=meth: (mpris.control(m['name'], meth), GLib.timeout_add(250, self.refresh_media)))
                card.pack_start(b, False, False, 0)
            self.mediabox.pack_start(card, True, True, 0); self.mediabox.show_all()
        if not first and hasattr(self, 'panel'): self.layout()
        return True

    def maybe_quit(self):
        if not self.is_active() and not any(w.is_active() for w in Gtk.Window.list_toplevels() if w is not self): self.quit()
        return False

    def quit(self, *a):
        try: os.remove(PID)
        except Exception: pass
        Gtk.main_quit(); return True

signal.signal(signal.SIGTERM, lambda *a: Gtk.main_quit())
QS(); Gtk.main()
