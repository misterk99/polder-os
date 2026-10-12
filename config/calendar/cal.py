#!/usr/bin/env python3
"""ChromeOS-style calendar popup (GTK3). Toggle by clicking the date pill; closes on Escape/focus loss;
mutually exclusive with Quick Settings. Events from ~/.local/share/osb/calendar.ics (simple VEVENT parser)."""
import os, sys, signal, subprocess, datetime, calendar
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'notify'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'osb')); import rgba as RGBA   # Rev 29.2: real rounded corners
import osbnotify as N
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb'))
import osbsettings
import layershell as LSH   # Rev 33c
SET = osbsettings.load()
HERE = os.path.dirname(os.path.abspath(__file__)); CFG = os.path.join(HERE, '..')
PID = '/tmp/osb-cal.pid'; ICS = os.path.expanduser('~/.local/share/osb/calendar.ics')
W, MARGIN_R, SHELF = 360, 10, 62
if os.path.exists(PID):
    try: os.kill(int(open(PID).read()), signal.SIGTERM); os.remove(PID); sys.exit(0)
    except Exception: os.remove(PID)
open(PID, 'w').write(str(os.getpid()))
if os.path.exists('/tmp/osb-qs.pid'):  # close Quick Settings
    try: os.kill(int(open('/tmp/osb-qs.pid').read()), signal.SIGTERM); os.remove('/tmp/osb-qs.pid')
    except Exception: pass

MONTHS = ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december']
DAYS = ['ma','di','wo','do','vr','za','zo']; DAYS_LONG = ['maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag','zondag']
P = N.palette()
CSS = f'''
* {{ font-family: Roboto; }}
#cal {{ background: {P['SURFACE']}; border-radius: 24px; padding: 16px; color: {P['ON_SURFACE']}; }}
.month {{ font-size: 16px; font-weight: 500; }}
.nav {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; min-width: 32px; min-height: 32px; padding: 0; color: {P['ON_SURFACE']}; }}
.nav:hover {{ background: {P['SURFACE_VARIANT']}; }}
.today-btn {{ background: {P['SURFACE_VARIANT']}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 12px; color: {P['ON_SURFACE']}; font-weight: 500; }}
.wd {{ font-size: 11px; color: {P['ON_SURFACE_VARIANT']}; font-weight: 500; }}
.day {{ background: transparent; border: none; box-shadow: none; border-radius: 18px; min-width: 36px; min-height: 36px; padding: 0; color: {P['ON_SURFACE']}; font-size: 13px; }}
.day:hover {{ background: {P['SURFACE_VARIANT']}; }}
.day.other {{ color: alpha({P['ON_SURFACE_VARIANT']}, 0.55); }}
.day.today {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; font-weight: 500; }}
.day.sel {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; font-weight: 500; }}
.day.today.sel {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; }}
.dot {{ color: {P['ACCENT']}; font-size: 11px; margin-top: -4px; }}
.day.today .dot {{ color: {P['ON_ACCENT']}; }}
.evhdr {{ font-size: 13px; font-weight: 500; color: {P['ON_SURFACE_VARIANT']}; }}
.ev {{ background: {P['SURFACE_VARIANT']}; border-radius: 16px; padding: 10px 14px; }}
.evbar {{ background: {P['ACCENT']}; border-radius: 2px; min-width: 4px; }}
.evtitle {{ font-weight: 500; font-size: 13px; }}
.evsub {{ font-size: 11px; color: {P['ON_SURFACE_VARIANT']}; }}
.empty {{ color: {P['ON_SURFACE_VARIANT']}; font-size: 13px; padding: 10px; }}
'''

import feeds   # ICS feeds + local calendar, RRULE/EXDATE/TZID aware

class Cal(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False); self.set_keep_above(True); self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG); self.set_name('calwin'); self.set_resizable(False); RGBA.enable(self)
        # Rev 33c: on polder-comp a layer surface anchored bottom-right, right edge aligned with the pill that opened it
        right = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--right=')), MARGIN_R)
        LSH.setup(self, 'polder-calendar', layer='overlay', anchors=('right', 'bottom'), margins={'right': max(MARGIN_R, right), 'bottom': SHELF}, exclusive=0, keyboard='on_demand')
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        prov = Gtk.CssProvider(); prov.load_from_data(CSS.encode()); Gtk.StyleContext.add_provider_for_screen(scr, prov, 800)
        self.bgcss = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(scr, self.bgcss, 900)
        self.events = {}; self.today = datetime.date.today()
        self.year, self.month, self.sel = self.today.year, self.today.month, self.today
        self.connect('key-press-event', lambda w, e: e.keyval == Gdk.KEY_Escape and self.quit())
        self.connect('focus-out-event', lambda *a: GLib.timeout_add(150, self.maybe_quit))
        self.connect('destroy', self.quit)
        self.connect('scroll-event', self.on_scroll); self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); self.box.set_name('cal'); self.add(self.box)
        hdr = Gtk.Box(spacing=4)
        self.title = Gtk.Label(xalign=0); self.title.get_style_context().add_class('month'); hdr.pack_start(self.title, True, True, 0)
        tb = Gtk.Button(label='Vandaag'); tb.get_style_context().add_class('today-btn'); tb.connect('clicked', self.goto_today); hdr.pack_start(tb, False, False, 4)
        for icon, d, tip in (('go-up-symbolic', -1, 'Vorige maand'), ('go-down-symbolic', 1, 'Volgende maand')):
            b = Gtk.Button(); b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)); b.set_tooltip_text(tip)
            b.get_style_context().add_class('nav'); b.connect('clicked', lambda _b, d=d: self.shift(d)); hdr.pack_start(b, False, False, 0)
        if '--weather' in sys.argv:   # Revision 25: Polder Weer card on top (opened from the weather pill)
            sys.path.insert(0, os.path.join(CFG, 'weather')); import wxcard
            wp = Gtk.CssProvider(); wp.load_from_data(wxcard.css(P).encode()); Gtk.StyleContext.add_provider_for_screen(scr, wp, 810)
            self.box.pack_start(wxcard.card(), False, False, 0)
        self.box.pack_start(hdr, False, False, 0)
        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=2, column_spacing=2); self.box.pack_start(self.grid, False, False, 0)
        self.evbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.evbox.set_size_request(-1, 0 if '--weather' in sys.argv else 150);  # fixed: panel never jumps
        self.box.pack_start(self.evbox, False, False, 0)
        self.render(); self.show_all(); self.place(); self.present()
        # click-outside: clicking the bare desktop doesn't move focus under xfwm4, so grab the pointer
        # (owner_events=True keeps our own widgets working) and quit on any press outside the panel.
        self.connect('button-press-event', self.on_press); self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        GLib.timeout_add(300, self.grab)

    def grab(self):
        if LSH.active(self): return False   # layer surface: focus-out / Esc close it (no X pointer grab on Wayland)
        seat = Gdk.Display.get_default().get_default_seat()
        seat.grab(self.get_window(), Gdk.SeatCapabilities.ALL_POINTING, True, None, None, None, None)
        return False

    def on_press(self, w, e):
        win = self.get_window(); ox, oy = win.get_origin()[1:]; ww, wh = win.get_width(), win.get_height()
        if not (ox <= e.x_root < ox + ww and oy <= e.y_root < oy + wh):
            self.quit()
        return False

    def place(self):
        """Bottom-right above the shelf (same conventions as QS); rounded corners via wallpaper backdrop."""
        self.resize(W, 1); w = W; h = self.box.get_preferred_height_for_width(W)[1]
        self.set_size_request(w, h); self.resize(w, h)
        x, y = self.sw - w - MARGIN_R, self.sh - SHELF - h
        if LSH.active(self): return   # compositor places layer surfaces; RGBA works there
        self.move(x, y)
        if RGBA.active(self): self.bgcss.load_from_data(b'#calwin { background: transparent; background-image: none; }'); return
        out = f'/tmp/osb-cal-bg-{h}.png'
        if not os.path.exists(out):
            subprocess.run(['convert', os.path.join(CFG, 'wallpaper.png'), '-crop', f'{w}x{h}+{x}+{y}', '+repage', out], timeout=10)
        self.bgcss.load_from_data(f"#calwin {{ background-image: url('{out}'); background-color: transparent; }}".encode())

    def render(self):
        self.title.set_label(f'{MONTHS[self.month - 1].capitalize()} {self.year}')
        for c in self.grid.get_children(): c.destroy()
        for i, d in enumerate(DAYS):
            l = Gtk.Label(label=d); l.get_style_context().add_class('wd'); self.grid.attach(l, i, 0, 1, 1)
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self.year, self.month)
        while len(weeks) < 6:  # constant height: always 6 rows
            last = weeks[-1][-1]; weeks.append([last + datetime.timedelta(days=i + 1) for i in range(7)])
        try: self.events = feeds.events_between(weeks[0][0], weeks[-1][-1] + datetime.timedelta(days=1))
        except Exception as e: print('agenda', e); self.events = {}
        for r, wk in enumerate(weeks):
            for c, day in enumerate(wk):
                b = Gtk.Button(); b.set_halign(Gtk.Align.CENTER); sc = b.get_style_context(); sc.add_class('day')
                v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, valign=Gtk.Align.CENTER)
                v.pack_start(Gtk.Label(label=str(day.day)), False, False, 0)
                dot = Gtk.Label(label='•' if day in self.events else ' '); dot.get_style_context().add_class('dot'); v.pack_start(dot, False, False, 0)
                b.add(v)
                if day.month != self.month: sc.add_class('other')
                if day == self.today: sc.add_class('today')
                if day == self.sel: sc.add_class('sel')
                b.connect('clicked', lambda _b, day=day: self.select(day)); self.grid.attach(b, c, r + 1, 1, 1)
        self.grid.show_all(); self.render_events()

    def render_events(self):
        if '--weather' in sys.argv: return   # weather mode: card + month grid only (fits 768px)
        for c in self.evbox.get_children(): c.destroy()
        d = self.sel
        h = Gtk.Label(label=f'{DAYS_LONG[d.weekday()]} {d.day} {MONTHS[d.month - 1]}', xalign=0); h.get_style_context().add_class('evhdr')
        self.evbox.pack_start(h, False, False, 0)
        evs = self.events.get(d, [])
        if not evs:
            e = Gtk.Label(label='Geen evenementen', xalign=0); e.get_style_context().add_class('empty'); self.evbox.pack_start(e, False, False, 0)
        for ev in evs[:2]:
            row = Gtk.Box(spacing=10); row.get_style_context().add_class('ev')
            bar = Gtk.Box(); bar.get_style_context().add_class('evbar'); row.pack_start(bar, False, False, 0)
            if ev.get('color'):
                cp = Gtk.CssProvider(); cp.load_from_data(f".evbar {{ background: {ev['color']}; }}".encode())
                bar.get_style_context().add_provider(cp, 950)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t = Gtk.Label(label=ev.get('title', '(geen titel)'), xalign=0); t.set_ellipsize(Pango.EllipsizeMode.END); t.get_style_context().add_class('evtitle')
            col.pack_start(t, False, False, 0)
            sub = Gtk.Label(label=' · '.join(x for x in (self.when(ev, d), ev.get('loc'), ev.get('cal')) if x), xalign=0); sub.get_style_context().add_class('evsub')
            sub.set_ellipsize(Pango.EllipsizeMode.END); col.pack_start(sub, False, False, 0)
            row.pack_start(col, True, True, 0); self.evbox.pack_start(row, False, False, 0)
        if len(evs) > 2:
            m = Gtk.Label(label=f'+{len(evs) - 2} meer', xalign=0); m.get_style_context().add_class('evsub'); self.evbox.pack_start(m, False, False, 0)
        self.evbox.show_all()
        if self.get_realized(): self.place()

    def when(self, ev, d):
        fmt = (lambda t: t.strftime('%H:%M')) if SET.get('clock24', True) else (lambda t: t.strftime('%-I:%M %p').lower())
        span = ev['first'] != ev['last']
        if ev['allday']:
            return f"Hele dag (dag {(d - ev['first']).days + 1} van {(ev['last'] - ev['first']).days + 1})" if span else 'Hele dag'
        if span:
            return ('Vanaf ' + fmt(ev['start'])) if d == ev['first'] else ('Tot ' + fmt(ev['end'])) if d == ev['last'] else 'Hele dag'
        return fmt(ev['start']) + ('–' + fmt(ev['end']) if ev['end'] and ev['end'] != ev['start'] else '')

    def select(self, day):
        self.sel = day
        if (day.year, day.month) != (self.year, self.month): self.year, self.month = day.year, day.month
        self.render()

    def shift(self, d):
        m = self.month - 1 + d; self.year += m // 12; self.month = m % 12 + 1; self.render()

    def goto_today(self, *a):
        self.year, self.month, self.sel = self.today.year, self.today.month, self.today; self.render()

    def on_scroll(self, w, e):
        dy = e.delta_y if e.direction == Gdk.ScrollDirection.SMOOTH else (-1 if e.direction == Gdk.ScrollDirection.UP else 1)
        now = GLib.get_monotonic_time()
        if dy and now - getattr(self, '_last', 0) > 150000:  # debounce ~150 ms
            self._last = now; self.shift(1 if dy > 0 else -1)
        return True

    def maybe_quit(self):
        if not self.is_active() or (LSH.active(self) and not self.has_toplevel_focus()): self.quit()
        return False

    def quit(self, *a):
        try: os.remove(PID)
        except Exception: pass
        Gtk.main_quit(); return True

signal.signal(signal.SIGTERM, lambda *a: Gtk.main_quit())
Cal(); Gtk.main()
