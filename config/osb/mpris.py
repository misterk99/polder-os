"""Tiny MPRIS client on Gio (no extra process/deps). Used by QS (media card), shelf (media pill) and lock screen."""
import gi
from gi.repository import Gio, GLib
_bus = None
def bus():
    global _bus
    if _bus is None: _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return _bus

def _call(name, path, iface, method, args=None, rtype=None, timeout=800):
    return bus().call_sync(name, path, iface, method, args, rtype, Gio.DBusCallFlags.NONE, timeout, None)

def players():
    try: names = _call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames').unpack()[0]
    except Exception: return []
    return [n for n in names if n.startswith('org.mpris.MediaPlayer2.')]

def state(name):
    try:
        props = _call(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'GetAll',
                      GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',))).unpack()[0]
    except Exception: return None
    md = props.get('Metadata', {}) or {}
    art = md.get('mpris:artUrl', '') or ''
    artist = md.get('xesam:artist', []) or []
    if isinstance(artist, str): artist = [artist]
    title = md.get('xesam:title', '') or ''
    if not title and md.get('xesam:url'): title = GLib.filename_display_basename(md['xesam:url'])
    try: ident = _call(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get',
                       GLib.Variant('(ss)', ('org.mpris.MediaPlayer2', 'Identity'))).unpack()[0]
    except Exception: ident = name.split('.')[3]
    return dict(name=name, status=props.get('PlaybackStatus', 'Stopped'), title=title, artist=', '.join(artist),
                album=md.get('xesam:album', '') or '', art=art[7:] if art.startswith('file://') else '',
                can_next=props.get('CanGoNext', False), can_prev=props.get('CanGoPrevious', False), app=ident)

def active():
    """Most relevant player: Playing first, then Paused. None when nothing is loaded/playing (no fake card)."""
    best = None
    for n in players():
        s = state(n)
        if not s or s['status'] not in ('Playing', 'Paused') or not (s['title'] or s['artist']): continue
        if s['status'] == 'Playing': return s
        best = best or s
    return best

def control(name, method):   # PlayPause | Next | Previous
    try: _call(name, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', method)
    except Exception as e: print('mpris', e)
