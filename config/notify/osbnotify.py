"""Shared helpers for the Polder OS notification service (state + D-Bus client)."""
import os, json
from gi.repository import Gio, GLib
DIR = '/tmp/osb-notify'; STATE = DIR + '/state.json'; BUSFILE = DIR + '/bus'
NAME, PATH, IFACE = 'org.osbuilder.Notify', '/org/osbuilder/Notify', 'org.osbuilder.Notify'
MONTHS = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec']

def palette():
    p = {}
    for l in open(os.path.join(os.path.dirname(__file__), '..', 'palette.env')):
        l = l.split('#', 1)[0] if not l.strip().startswith('#') else ''
    for l in open(os.path.join(os.path.dirname(__file__), '..', 'palette.env')):
        if '=' in l and not l.startswith('#'):
            k, v = l.split('=', 1); p[k.strip()] = v.split()[0]
    return p

def load():
    try: return json.load(open(STATE))
    except Exception: return {'history': [], 'unread': 0, 'dnd': False}

def bus():
    addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
    if os.path.exists(BUSFILE): addr = open(BUSFILE).read().strip()
    return Gio.DBusConnection.new_for_address_sync(addr,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)

def call(method, args=None):
    b = bus()
    return b.call_sync(NAME, PATH, IFACE, method, args, None, Gio.DBusCallFlags.NONE, 2000, None)
