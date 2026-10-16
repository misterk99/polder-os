#!/usr/bin/env python3
"""Telefoon (Revision 28): thin client for kdeconnectd (KDE Connect) over the session D-Bus.
Used by Instellingen > Telefoon, the QS 'Telefoon' tile, the shelf status and the 'Naar telefoon sturen' action.
Never invents a device: everything comes from the daemon. CLI: phone.py list | send <file>... | ring <id>"""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, sys, json, subprocess, shutil
import gi; gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
BUS = 'org.kde.kdeconnect'; ROOT = '/modules/kdeconnect'
PLUGINS = [('kdeconnect_notifications', _('Sync notifications'), _('Notifications from your phone appear here.')),
           ('kdeconnect_clipboard', _('Share clipboard'), _('Copied text goes back and forth automatically.')),
           ('kdeconnect_share', _('Receive files'), _('Shared files go into ~/Downloads.')),
           ('kdeconnect_battery', _('Battery status'), _("Your phone's battery in Quick Settings.")),
           ('kdeconnect_findmyphone', _('Find phone'), _('Make your phone ring, even on silent.'))]

def available(): return bool(shutil.which('kdeconnectd') or os.path.exists('/usr/lib/x86_64-linux-gnu/libexec/kdeconnectd'))

def _bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)

def _call(path, iface, method, args=None, sig=None, timeout=3000, dest=BUS):
    r = _bus().call_sync(dest, path, iface, method, args, GLib.VariantType(sig) if sig else None, Gio.DBusCallFlags.NONE, timeout, None)
    return r.unpack() if r else None

def _prop(path, iface, name):
    try: return _call(path, 'org.freedesktop.DBus.Properties', 'Get', GLib.Variant('(ss)', (iface, name)), '(v)')[0]
    except Exception: return None

def running():
    try: return bool(_call('/org/freedesktop/DBus', 'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', (BUS,)), '(b)', 1000, dest='org.freedesktop.DBus')[0])
    except Exception: return False

def start():
    """Start kdeconnectd on this session bus (D-Bus activation; falls back to spawning the binary)."""
    if running(): return True
    for b in (shutil.which('kdeconnectd'), '/usr/lib/x86_64-linux-gnu/libexec/kdeconnectd'):
        if b and os.path.exists(b):
            subprocess.Popen([b], stdout=subprocess.DEVNULL, stderr=open('/tmp/kdeconnectd.log', 'a'), start_new_session=True); return True
    return False

def devices():
    """[{id, name, type, reachable, paired, pair_requested, battery, charging, verification}]"""
    out = []
    try: ids = _call(ROOT, 'org.kde.kdeconnect.daemon', 'devices', GLib.Variant('(bb)', (False, False)), '(as)')[0]
    except Exception: return out
    for i in ids:
        p = f'{ROOT}/devices/{i}'; D = 'org.kde.kdeconnect.device'
        d = {'id': i, 'name': _prop(p, D, 'name') or i, 'type': _prop(p, D, 'type') or 'phone',
             'reachable': bool(_prop(p, D, 'isReachable')), 'paired': bool(_prop(p, D, 'isPaired')),
             'pair_requested': bool(_prop(p, D, 'isPairRequested') or _prop(p, D, 'isPairRequestedByPeer')),
             'verification': _prop(p, D, 'verificationKey') or ''}
        b = f'{p}/battery'; d['battery'] = _prop(b, 'org.kde.kdeconnect.device.battery', 'charge'); d['charging'] = _prop(b, 'org.kde.kdeconnect.device.battery', 'isCharging')
        out.append(d)
    return out

def dev_call(did, method, *args, sig=''):
    return _call(f'{ROOT}/devices/{did}', 'org.kde.kdeconnect.device', method, GLib.Variant(f'({sig})', args) if sig else None)

def pair(did): dev_call(did, 'requestPairing')
def unpair(did): dev_call(did, 'unpair')
def accept(did): dev_call(did, 'acceptPairing')
def plugin_enabled(did, name):
    try: return bool(dev_call(did, 'isPluginEnabled', name, sig='s')[0])
    except Exception: return None
def set_plugin(did, name, on): dev_call(did, 'setPluginEnabled', name, bool(on), sig='sb')
def ring(did): _call(f'{ROOT}/devices/{did}/findmyphone', 'org.kde.kdeconnect.device.findmyphone', 'ring')
def refresh(): 
    try: _call(ROOT, 'org.kde.kdeconnect.daemon', 'forceOnNetworkChange')
    except Exception: pass
def send(did, paths):
    for f in paths: _call(f'{ROOT}/devices/{did}/share', 'org.kde.kdeconnect.device.share', 'shareUrl', GLib.Variant('(s)', (Gio.File.new_for_path(f).get_uri(),)))

def connected():
    """First paired + reachable device or None (QS tile / shelf)."""
    if not running(): return None
    return next((d for d in devices() if d['paired'] and d['reachable']), None)

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == 'list': print(json.dumps({'running': running(), 'devices': devices()}, indent=1, ensure_ascii=False))
    elif a[0] == 'start': print(start())
    elif a[0] == 'ring': ring(a[1])
    elif a[0] == 'send':   # Thunar action: send to the (first) connected phone, notify the result
        d = connected()
        if not d: subprocess.run(['notify-send', '-a', _('Phone'), '-i', 'phone-symbolic', _('No phone connected'), _('Pair your phone in Settings › Phone.')]); sys.exit(1)
        send(d['id'], a[1:]); subprocess.run(['notify-send', '-a', _('Phone'), '-i', 'phone-symbolic', _('Sent to {p0}').format(p0=d['name']), ', '.join(os.path.basename(x) for x in a[1:])[:200]])
