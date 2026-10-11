#!/usr/bin/env python3
"""Polder OS notification service: owns org.freedesktop.Notifications on the session bus,
shows ChromeOS-style pop-ups, keeps history/unread/DND in /tmp/osb-notify/state.json,
and exposes org.osbuilder.Notify (ClearAll, Dismiss, MarkRead, SetDnd) for QS/shelf."""
import os, sys, json, time, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
import osbnotify as N
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb')); import osbsettings as OSBS

HERE = os.path.dirname(os.path.abspath(__file__)); CFG = os.path.join(HERE, '..')
P = N.palette(); CARD_W, GAP, SHELF, MARGIN = 420, 8, 62, 10  # same column as Quick Settings
TIMEOUT = 6000

XML = '''<node>
<interface name="org.freedesktop.Notifications">
 <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
  <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
  <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
 <method name="CloseNotification"><arg type="u" direction="in"/></method>
 <method name="GetCapabilities"><arg type="as" direction="out"/></method>
 <method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
  <arg type="s" direction="out"/><arg type="s" direction="out"/></method>
 <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
 <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface>
<interface name="org.osbuilder.Notify">
 <method name="ClearAll"/><method name="MarkRead"/>
 <method name="Dismiss"><arg type="u" direction="in"/></method>
 <method name="SetDnd"><arg type="b" direction="in"/></method>
 <method name="Invoke"><arg type="u" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>'''

CSS = f'''
* {{ font-family: Roboto; }}
.card {{ background: {P['SURFACE']}; border-radius: 20px; padding: 12px 14px; color: {P['ON_SURFACE']}; border: 1px solid {P['OUTLINE']}; }}
.app {{ font-size: 11px; color: {P['ON_SURFACE_VARIANT']}; }}
.ntitle {{ font-weight: 500; font-size: 13px; }}
.nbody {{ font-size: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
.x {{ background: transparent; border: none; box-shadow: none; padding: 0; min-width: 24px; min-height: 24px; border-radius: 12px; color: {P['ON_SURFACE_VARIANT']}; }}
.x:hover {{ background: {P['SURFACE_VARIANT']}; }}
.card.inner {{ background: {P['SURFACE_VARIANT']}; border: none; border-radius: 16px; }}
.card.popup {{ border-radius: 24px; padding: 14px 16px; }}
.act {{ background: {P['ACCENT_CONTAINER']}; color: {P['ON_ACCENT_CONTAINER']}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 14px; min-height: 28px; font-weight: 500; }}
.act:hover {{ background: shade({P['ACCENT_CONTAINER']}, 0.95); }}
.appicon {{ background: {P['ACCENT_CONTAINER']}; border-radius: 16px; min-width: 32px; min-height: 32px; color: {P['ON_ACCENT_CONTAINER']}; }}
'''

ICONS = {'downloads': 'folder-download-symbolic', 'systeem': 'emblem-system-symbolic', 'chromium': 'web-browser-symbolic',
         'bestanden': 'system-file-manager-symbolic'}

def backdrop_css(name, x, y, w, h):
    """Rounded corners w/o compositor: paint the wallpaper region behind the window as its background."""
    out = f'/tmp/osb-notify/bg-{name}.png'
    subprocess.run(['convert', os.path.join(CFG, 'wallpaper.png'), '-crop', f'{w}x{h}+{x}+{y}', '+repage', out])
    return f"#{name} {{ background-image: url('{out}'); background-color: transparent; }}"

def build_card(n, on_close, on_activate=None, inner=False):
    """Rounded card for notification n. Body click -> on_activate(id,'default'); buttons -> on_activate(id,key)."""
    card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12); sc = card.get_style_context(); sc.add_class('card')
    sc.add_class('inner' if inner else 'popup')
    icon_name = n.get('icon') or ICONS.get(n['app'].lower(), 'dialog-information-symbolic')
    ic = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR); ic.get_style_context().add_class('appicon')
    ic.set_valign(Gtk.Align.START); card.pack_start(ic, False, False, 0)
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    t = datetime.datetime.fromtimestamp(n['time']).strftime('%H:%M')
    a = Gtk.Label(label=f"{n['app']} · {t}", xalign=0); a.get_style_context().add_class('app'); col.pack_start(a, False, False, 0)
    ti = Gtk.Label(label=n['summary'], xalign=0); ti.set_ellipsize(Pango.EllipsizeMode.END); ti.get_style_context().add_class('ntitle'); col.pack_start(ti, False, False, 0)
    if n.get('body'):
        b = Gtk.Label(label=n['body'], xalign=0); b.set_line_wrap(True); b.set_max_width_chars(40); b.set_lines(2)
        b.set_ellipsize(Pango.EllipsizeMode.END); b.get_style_context().add_class('nbody'); col.pack_start(b, False, False, 0)
    if n.get('image') and os.path.isfile(n['image']):
        try:
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(n['image'], 240, 120, True)
            im = Gtk.Image.new_from_pixbuf(pb); im.set_halign(Gtk.Align.START); im.set_margin_top(6); im.get_style_context().add_class('nthumb'); col.pack_start(im, False, False, 0)
        except Exception as e: print('thumb', e)
    acts = [(k, l) for k, l in n.get('actions', []) if k != 'default']
    if acts and on_activate:
        row = Gtk.Box(spacing=8); row.set_margin_top(6)
        for k, l in acts:
            bt = Gtk.Button(label=l); bt.get_style_context().add_class('act')
            bt.connect('clicked', lambda _b, k=k: on_activate(n['id'], k)); row.pack_start(bt, False, False, 0)
        col.pack_start(row, False, False, 0)
    card.pack_start(col, True, True, 0)
    x = Gtk.Button(); x.add(Gtk.Image.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)); x.set_tooltip_text('Sluiten')
    x.get_style_context().add_class('x'); x.set_valign(Gtk.Align.START); x.connect('clicked', lambda *_: on_close(n['id']))
    card.pack_end(x, False, False, 0)
    if not on_activate: return card
    ev = Gtk.EventBox(); ev.add(card)
    ev.connect('button-release-event', lambda w, e: e.button == 1 and on_activate(n['id'], 'default'))
    ev.connect('realize', lambda w: w.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), 'pointer')))
    return ev

def open_app(n):
    """Fallback for notifications without a 'default' action: open/raise the sending app."""
    app = (n.get('desktop') or n['app']).lower()
    def raise_or(cls, cmd):
        r = subprocess.run(['xdotool', 'search', '--class', cls], capture_output=True, text=True).stdout.split()
        if r: subprocess.run(['xdotool', 'windowmap', r[-1], 'windowactivate', r[-1]], stderr=subprocess.DEVNULL)
        else: subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if app in ('downloads', 'bestanden', 'files', 'thunar'):
        sub = 'Downloads' if app == 'downloads' else ''
        subprocess.Popen([os.path.join(CFG, 'files', 'run-files.sh'), f'/tmp/osb-files/Mijn bestanden/{sub}'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif app in ('chromium', 'google chrome', 'chrome'):
        raise_or('chromium', ['chromium', '--user-data-dir=/tmp/protohome/chromium', '--no-first-run'])
    elif app in ('systeem', 'system'):
        subprocess.Popen(['xfce4-settings-manager'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            info = Gio.DesktopAppInfo.new(app + '.desktop')
            if info: info.launch([], None)
        except Exception as e: print('no app for', app, e)

class Daemon:
    def __init__(self):
        os.makedirs(N.DIR, exist_ok=True)
        open(N.BUSFILE, 'w').write(os.environ['DBUS_SESSION_BUS_ADDRESS'])
        self.state = N.load(); self.next_id = max([h['id'] for h in self.state['history']] + [0]) + 1
        self.popups = []  # list of (id, window)
        self.prov = prov = Gtk.CssProvider(); prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, 800)
        self.bgprov = Gtk.CssProvider(); Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.bgprov, 900)
        self.bgrules = {}
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        Gio.bus_own_name(Gio.BusType.SESSION, 'org.freedesktop.Notifications', Gio.BusNameOwnerFlags.REPLACE, self.on_bus, None,
                         lambda *a: (print('lost org.freedesktop.Notifications'), Gtk.main_quit()))
        Gio.bus_own_name(Gio.BusType.SESSION, N.NAME, Gio.BusNameOwnerFlags.NONE, None, None, None)
        self.save()

    def on_bus(self, conn, name):
        self.conn = conn
        for iface in self.node.interfaces:
            conn.register_object('/org/freedesktop/Notifications' if iface.name.startswith('org.freedesktop') else N.PATH,
                                 iface, self.on_call, None, None)

    def save(self):
        tmp = N.STATE + '.tmp'; json.dump(self.state, open(tmp, 'w')); os.replace(tmp, N.STATE)

    def on_call(self, conn, sender, path, iface, method, params, inv):
        p = params.unpack(); r = None
        if method == 'GetCapabilities': r = GLib.Variant('(as)', (['body', 'actions', 'persistence'],))
        elif method == 'GetServerInformation': r = GLib.Variant('(ssss)', ('Polder OS Meldingen', 'Polder OS', '0.13', '1.2'))
        elif method == 'Notify': r = GLib.Variant('(u)', (self.notify(*p),))
        elif method == 'CloseNotification': self.close_popup(p[0])
        elif method == 'ClearAll': self.state['history'] = []; self.state['unread'] = 0
        elif method == 'Dismiss': self.state['history'] = [h for h in self.state['history'] if h['id'] != p[0]]; self.close_popup(p[0])
        elif method == 'MarkRead': self.state['unread'] = 0
        elif method == 'Invoke': self.invoke(*p)
        elif method == 'SetDnd':
            self.state['dnd'] = bool(p[0])
            if p[0]: [self.close_popup(i) for i, _ in list(self.popups)]
        self.save(); inv.return_value(r)

    def notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        nid = replaces or self.next_id; self.next_id = max(self.next_id, nid + 1)
        n = {'id': nid, 'app': app or 'Systeem', 'icon': icon if icon and '/' not in icon else '', 'summary': summary,
             'body': body, 'time': time.time(), 'actions': [[actions[i], actions[i+1]] for i in range(0, len(actions) - 1, 2)],
             'desktop': hints.get('desktop-entry', '') if hints else ''}
        img = (hints or {}).get('image-path') or (hints or {}).get('image_path') or (icon if icon and icon.startswith('/') else '')
        if img.startswith('file://'): img = img[7:]
        if img and os.path.isfile(img): n['image'] = img   # Revision 18: thumbnail (e.g. screenshots)
        cfg = OSBS.load()   # Instellingen > Meldingen (read per notification, so changes apply immediately)
        if cfg['notifications'] or cfg['notif_history']:
            self.state['history'] = [h for h in self.state['history'] if h['id'] != nid] + [n]
            self.state['history'] = self.state['history'][-50:]
            self.state['unread'] += 1
        if cfg['notifications'] and not self.state['dnd']:
            self.show_popup(n, int(cfg['popup_secs']) * 1000 if timeout in (-1, 0) else timeout)
        self.save(); return nid

    def show_popup(self, n, timeout):
        w = Gtk.Window(type=Gtk.WindowType.POPUP); w.set_name(f"np{n['id']}")
        w.add(build_card(n, self.dismiss_popup, lambda i, k: self.invoke(i, k))); w.show_all()
        self.popups.append((n['id'], w)); self.relayout()
        GLib.timeout_add(TIMEOUT if timeout in (-1, 0) or timeout > 60000 else timeout, lambda: self.expire(n['id']))

    def dismiss_popup(self, nid): self.close_popup(nid, reason=2)

    def invoke(self, nid, key):
        n = next((h for h in self.state['history'] if h['id'] == nid), None)
        if not n: return
        keys = [k for k, _ in n.get('actions', [])]
        if key in keys:
            self.conn.emit_signal(None, '/org/freedesktop/Notifications', 'org.freedesktop.Notifications', 'ActionInvoked',
                                  GLib.Variant('(us)', (nid, key)))
        else:
            open_app(n)
        self.state['history'] = [h for h in self.state['history'] if h['id'] != nid]
        self.close_popup(nid, reason=2); self.save()

    def close_popup(self, nid, reason=1):
        for i, w in list(self.popups):
            if i == nid: w.destroy(); self.popups.remove((i, w)); self.bgrules.pop(f'np{i}', None)
        self.relayout()
        try: self.conn.emit_signal(None, '/org/freedesktop/Notifications', 'org.freedesktop.Notifications', 'NotificationClosed', GLib.Variant('(uu)', (nid, reason)))
        except Exception: pass
        return False

    def expire(self, nid):
        # popup timed out: hide it but keep it in history; tell the app (reason 1 = expired)
        if any(i == nid for i, _ in self.popups): self.close_popup(nid, reason=1)
        return False

    def relayout(self):
        scr = Gdk.Screen.get_default(); sw, sh = scr.get_width(), scr.get_height()
        y = sh - SHELF
        for i, w in reversed(self.popups):  # newest at bottom
            w.set_size_request(CARD_W, -1); h = w.get_child().get_preferred_height_for_width(CARD_W)[1]; w.resize(CARD_W, h)
            y -= h; x = sw - CARD_W - MARGIN; w.move(x, y)
            self.bgrules[f'np{i}'] = backdrop_css(f'np{i}', x, y, CARD_W, h)
            y -= GAP
        self.bgprov.load_from_data('\n'.join(self.bgrules.values()).encode())

if __name__ == '__main__':
    Daemon(); Gtk.main()
