"""Shared ChromeOS-style lock/login UI for Polder OS (used by lock.py and the LightDM greeter).
Fullscreen window: blurred+dimmed wallpaper, centred round avatar(s), name, borderless pill password field
with arrow, caps-lock hint, error shake, bottom-left power buttons, bottom-right status (time, badge)."""
import os, sys, subprocess, hashlib, datetime, json
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
for d in ('osb', 'notify'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import osbsettings as S

def palette():
    p = {}
    for l in open(os.path.join(C, 'palette.env')):
        if '=' in l and not l.startswith('#'): k, v = l.split('=', 1); p[k.strip()] = v.split()[0]
    return p

def blurred_bg(w, h, theme):
    """Heavily blurred + dimmed copy of the current wallpaper, cached per wallpaper/theme/size."""
    wp = os.path.join(C, 'wallpaper.png')
    if not os.path.exists(wp): wp = os.path.join(C, 'wallpapers', 'polderheuvel.png')   # Rev 34f: same fallback as the desktop
    cdir = os.environ.get('OSB_LOCK_CACHE') or os.path.join(S.CACHE, 'lock')
    os.makedirs(cdir, exist_ok=True)
    dim = '20' if theme == 'dark' else '35'
    key = hashlib.md5(f'{os.path.getmtime(wp)}{theme}{w}x{h}{dim}'.encode()).hexdigest()[:10]
    out = os.path.join(cdir, f'bg-{key}.png')
    if not os.path.exists(out):
        subprocess.run(['convert', wp, '-resize', f'{w}x{h}^', '-gravity', 'center', '-extent', f'{w}x{h}', '-resize', '12%',
                        '-blur', '0x6', '-resize', f'{w}x{h}!', '-fill', 'black', '-colorize', dim, out], timeout=20)
        for f in os.listdir(os.path.dirname(out)):
            try:
                if f != os.path.basename(out): os.remove(os.path.join(cdir, f))
            except OSError: pass
    return out

def css(P, bg):
    return f'''
* {{ font-family: Roboto; }}
#lockwin {{ background-image: url('{bg}'); background-size: cover; color: #ffffff; }}
.avatar {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; border-radius: 48px; min-width: 96px; min-height: 96px; font-size: 40px; font-weight: 500; }}
.avatar.small {{ border-radius: 32px; min-width: 64px; min-height: 64px; font-size: 26px; }}
.pod {{ background: transparent; border: none; box-shadow: none; padding: 8px; border-radius: 20px; color: #ffffff; }}
.pod:hover {{ background: alpha(#ffffff, 0.10); }}
.pod.sel {{ background: alpha(#ffffff, 0.16); }}
.name {{ font-size: 22px; color: #ffffff; text-shadow: 0 1px 3px alpha(#000000, 0.5); }}
.name.small {{ font-size: 14px; }}
.hint {{ font-size: 12px; color: alpha(#ffffff, 0.8); }}
.pwbox {{ background: alpha({P['SURFACE']}, 0.92); border-radius: 24px; padding: 2px 4px 2px 18px; }}
.pwbox entry {{ background: transparent; border: none; box-shadow: none; color: {P['ON_SURFACE']}; font-size: 15px; min-height: 40px; caret-color: {P['ACCENT']}; }}
.go {{ background: {P['ACCENT']}; color: {P['ON_ACCENT']}; border: none; box-shadow: none; border-radius: 20px; min-width: 40px; min-height: 40px; padding: 0; }}
.go:disabled {{ background: {P['SURFACE_VARIANT']}; color: {P['ON_SURFACE_VARIANT']}; }}
.err {{ color: #ffb4ab; font-size: 13px; font-weight: 500; text-shadow: 0 1px 2px alpha(#000000, 0.6); }}
.caps {{ color: #ffe08a; font-size: 12px; }}
.shelfbtn {{ background: alpha({P['SURFACE']}, 0.85); color: {P['ON_SURFACE']}; border: none; box-shadow: none; border-radius: 18px; padding: 6px 14px; }}
.shelfbtn:hover {{ background: {P['SURFACE']}; }}
.status {{ background: alpha({P['SURFACE']}, 0.85); color: {P['ON_SURFACE']}; border-radius: 18px; padding: 6px 14px; font-weight: 500; }}
.badge {{ background: {P['ON_SURFACE']}; color: {P['SURFACE']}; border-radius: 10px; min-width: 20px; font-size: 11px; font-weight: 500; }}
.confirm {{ background: alpha({P['SURFACE']}, 0.95); color: {P['ON_SURFACE']}; border-radius: 20px; padding: 10px 14px; }}
.danger {{ background: #b3261e; color: #ffffff; border: none; box-shadow: none; border-radius: 16px; padding: 4px 14px; }}
.clock {{ font-size: 13px; color: alpha(#ffffff, 0.9); }}
'''

def initial(name): return (name or '?').strip()[:1].upper()

def avatar(name, face=None, small=False):
    sz = 64 if small else 96
    if face and os.path.exists(face):
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(face, sz, sz, False)
        img = Gtk.Image.new_from_pixbuf(pb); return img   # (square; ~/.face is usually pre-cropped)
    l = Gtk.Label(label=initial(name)); sc = l.get_style_context(); sc.add_class('avatar')
    if small: sc.add_class('small')
    l.set_halign(Gtk.Align.CENTER); return l

class LockUI(Gtk.Window):
    """Base fullscreen UI. Subclasses implement authenticate(user, password, done_cb) and power(action)."""
    POWER = [('system-shutdown-symbolic', 'Uitschakelen', 'shutdown'), ('system-log-out-symbolic', 'Afmelden', 'logout')]

    def __init__(self, users, hint=None, popup=True):
        super().__init__(type=Gtk.WindowType.POPUP if popup else Gtk.WindowType.TOPLEVEL, title='Polder OS vergrendeld')
        self.set_name('lockwin'); self.users = users; self.sel = 0
        scr = Gdk.Screen.get_default(); self.sw, self.sh = scr.get_width(), scr.get_height()
        self.move(0, 0); self.set_default_size(self.sw, self.sh); self.set_size_request(self.sw, self.sh)
        self.theme = S.effective_theme(); P = palette()
        prov = Gtk.CssProvider(); prov.load_from_data(css(P, blurred_bg(self.sw, self.sh, self.theme)).encode())
        Gtk.StyleContext.add_provider_for_screen(scr, prov, 900)
        ov = Gtk.Overlay(); self.add(ov); ov.add(Gtk.Box())
        # centre column
        self.col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.pods = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER); self.col.pack_start(self.pods, False, False, 0)
        self.build_pods()
        if hint: h = Gtk.Label(label=hint); h.get_style_context().add_class('hint'); self.col.pack_start(h, False, False, 0)
        self.pwrow = Gtk.Box(spacing=6); self.pwrow.get_style_context().add_class('pwbox'); self.pwrow.set_size_request(300, -1)
        self.entry = Gtk.Entry(); self.entry.set_visibility(False); self.entry.set_placeholder_text('Wachtwoord'); self.entry.set_hexpand(True)
        self.entry.connect('activate', self.submit); self.entry.connect('changed', lambda *a: self.go.set_sensitive(bool(self.entry.get_text())))
        self.go = Gtk.Button(); self.go.add(Gtk.Image.new_from_icon_name('go-next-symbolic', Gtk.IconSize.MENU)); self.go.get_style_context().add_class('go')
        self.go.set_sensitive(False); self.go.connect('clicked', self.submit)
        self.pwrow.pack_start(self.entry, True, True, 0); self.pwrow.pack_start(self.go, False, False, 0)
        self.pwwrap = Gtk.Box(halign=Gtk.Align.CENTER); self.pwwrap.pack_start(self.pwrow, False, False, 0); self.col.pack_start(self.pwwrap, False, False, 0)
        self.msg = Gtk.Label(); self.msg.get_style_context().add_class('err'); self.col.pack_start(self.msg, False, False, 0)
        self.caps = Gtk.Label(label='Caps Lock staat aan'); self.caps.get_style_context().add_class('caps'); self.caps.set_no_show_all(True); self.col.pack_start(self.caps, False, False, 0)
        ov.add_overlay(self.col)
        # bottom-left power, bottom-right status
        bl = Gtk.Box(spacing=8, halign=Gtk.Align.START, valign=Gtk.Align.END); bl.set_margin_start(14); bl.set_margin_bottom(12)
        for icon, label, act in self.POWER:
            b = Gtk.Button(); bx = Gtk.Box(spacing=8); bx.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            bx.pack_start(Gtk.Label(label=label), False, False, 0); b.add(bx); b.get_style_context().add_class('shelfbtn')
            b.connect('clicked', lambda _b, a=act, l=label: self.ask(a, l)); bl.pack_start(b, False, False, 0)
        self.confirm = Gtk.Box(spacing=10); self.confirm.get_style_context().add_class('confirm'); self.confirm.set_no_show_all(True); bl.pack_start(self.confirm, False, False, 0)
        ov.add_overlay(bl)
        br = Gtk.Box(spacing=8, halign=Gtk.Align.END, valign=Gtk.Align.END); br.set_margin_end(14); br.set_margin_bottom(12)
        # Revision 18: compact media card (MPRIS on the session bus; hidden when nothing plays or the bus isn't reachable)
        self.media = Gtk.Box(spacing=8); self.media.get_style_context().add_class('status'); self.media.set_no_show_all(True)
        self.mlabel = Gtk.Label(); self.mlabel.set_max_width_chars(28); self.mlabel.set_ellipsize(3)
        self.mbtn = Gtk.Button(); self.mbtn.get_style_context().add_class('go'); self.mimg = Gtk.Image.new_from_icon_name('media-playback-pause-symbolic', Gtk.IconSize.MENU)
        self.mbtn.add(self.mimg); self.mbtn.connect('clicked', self.media_pp)
        mi = Gtk.Image.new_from_icon_name('audio-x-generic-symbolic', Gtk.IconSize.MENU)
        for w_ in (mi, self.mlabel, self.mbtn): self.media.pack_start(w_, False, False, 0); w_.show_all()
        br.pack_start(self.media, False, False, 0); self.mstate = None
        self.status = Gtk.Box(spacing=8); self.status.get_style_context().add_class('status'); br.pack_start(self.status, False, False, 0)
        self.tlabel = Gtk.Label(); self.status.pack_start(self.tlabel, False, False, 0)
        self.badge = Gtk.Label(); self.badge.get_style_context().add_class('badge'); self.badge.set_no_show_all(True); self.status.pack_start(self.badge, False, False, 0)
        ov.add_overlay(br)
        self.connect('key-press-event', self.on_key); self.connect('key-release-event', lambda *a: self.update_caps())
        self.tick(); GLib.timeout_add_seconds(5, self.tick)

    def build_pods(self):
        for c in self.pods.get_children(): c.destroy()
        small = len(self.users) > 1
        for i, u in enumerate(self.users):
            b = Gtk.Button(); b.get_style_context().add_class('pod')
            if small and i == self.sel: b.get_style_context().add_class('sel')
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); v.pack_start(avatar(u['display'], u.get('face'), small), False, False, 0)
            n = Gtk.Label(label=u['display']); n.get_style_context().add_class('name')
            if small: n.get_style_context().add_class('small')
            v.pack_start(n, False, False, 0); b.add(v); b.connect('clicked', lambda _b, i=i: self.pick(i)); self.pods.pack_start(b, False, False, 0)
        self.pods.show_all()

    def pick(self, i):
        self.sel = i; self.build_pods(); self.msg.set_text(''); self.entry.set_text(''); self.entry.grab_focus()

    def tick(self):
        s = S.load(); fmt = '%H:%M' if s.get('clock24', True) else '%-I:%M'
        d = datetime.date.today(); mn = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'][d.month - 1]
        self.tlabel.set_text(f"{['ma','di','wo','do','vr','za','zo'][d.weekday()]} {d.day} {mn}   {datetime.datetime.now().strftime(fmt)}")
        try: n = json.load(open('/tmp/osb-notify/state.json')).get('unread', 0)
        except Exception: n = 0
        self.badge.set_text(str(n)); self.badge.set_visible(n > 0)
        try:
            import mpris; m = mpris.active()
        except Exception: m = None
        self.mstate = m
        if m:
            self.mlabel.set_text(m['title'] + (f" · {m['artist']}" if m['artist'] else ''))
            self.mimg.set_from_icon_name('media-playback-pause-symbolic' if m['status'] == 'Playing' else 'media-playback-start-symbolic', Gtk.IconSize.MENU)
        self.media.set_visible(bool(m)); return True

    def media_pp(self, *a):
        if self.mstate:
            import mpris; mpris.control(self.mstate['name'], 'PlayPause'); GLib.timeout_add(300, lambda: self.tick() and False)

    def update_caps(self):
        self.caps.set_visible(Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_caps_lock_state())

    def on_key(self, w, e):
        GLib.idle_add(self.update_caps)
        if e.keyval == Gdk.KEY_Escape: self.entry.set_text(''); self.hide_confirm(); return True
        if not self.entry.has_focus(): self.entry.grab_focus()
        return False

    def submit(self, *a):
        pw = self.entry.get_text()
        if not pw: return
        self.entry.set_sensitive(False); self.go.set_sensitive(False); self.msg.set_text('Controleren…')
        self.authenticate(self.users[self.sel], pw, self.auth_done)

    def auth_done(self, ok, reason=''):
        self.entry.set_sensitive(True); self.entry.set_text('')
        if ok: self.msg.set_text(''); self.unlocked(); return
        self.msg.set_text('Onjuist wachtwoord' if not reason else reason); self.entry.grab_focus(); self.shake()

    def shake(self):
        steps = [12, -12, 9, -9, 5, -5, 0]
        def step(i=[0]):
            if i[0] >= len(steps): i[0] = 0; return False
            v = steps[i[0]]; self.pwwrap.set_margin_start(max(v, 0) * 2); self.pwwrap.set_margin_end(max(-v, 0) * 2); i[0] += 1; return True
        GLib.timeout_add(40, step)

    def ask(self, action, label):
        for c in self.confirm.get_children(): c.destroy()
        self.confirm.pack_start(Gtk.Label(label=f'{label}?'), False, False, 0)
        no = Gtk.Button(label='Annuleren'); no.get_style_context().add_class('shelfbtn'); no.connect('clicked', lambda *a: self.hide_confirm())
        yes = Gtk.Button(label=label); yes.get_style_context().add_class('danger'); yes.connect('clicked', lambda *a: (self.hide_confirm(), self.power(action)))
        self.confirm.pack_start(no, False, False, 0); self.confirm.pack_start(yes, False, False, 0); self.confirm.set_no_show_all(False); self.confirm.show_all()

    def hide_confirm(self): self.confirm.hide(); self.confirm.set_no_show_all(True)

if __name__ == '__main__' and sys.argv[1:] == ['--prerender']:   # called by osb/apply.py after a wallpaper/theme change
    scr = Gdk.Screen.get_default(); print(blurred_bg(scr.get_width(), scr.get_height(), S.effective_theme()))
