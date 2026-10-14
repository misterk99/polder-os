#!/usr/bin/env python3
"""Test fixture: minimal MPRIS player on the test session bus (clean data for screenshots)."""
from gi.repository import Gio, GLib
XML = '''<node><interface name="org.mpris.MediaPlayer2"><property name="Identity" type="s" access="read"/></interface>
<interface name="org.mpris.MediaPlayer2.Player"><method name="PlayPause"/><method name="Next"/><method name="Previous"/>
<property name="PlaybackStatus" type="s" access="read"/><property name="Metadata" type="a{sv}" access="read"/>
<property name="CanGoNext" type="b" access="read"/><property name="CanGoPrevious" type="b" access="read"/></interface></node>'''
st = {'s': 'Playing', 'i': 0}
TR = [('Polderwind', 'Testorkest'), ('Molenlied', 'Testorkest')]
def call(c, snd, path, iface, m, p, inv):
    if m == 'PlayPause': st['s'] = 'Paused' if st['s'] == 'Playing' else 'Playing'
    elif m == 'Next': st['i'] = (st['i'] + 1) % 2
    elif m == 'Previous': st['i'] = (st['i'] - 1) % 2
    print('call', m, st, flush=True); inv.return_value(None)
def get(c, snd, path, iface, prop):
    t = TR[st['i']]
    return {'Identity': GLib.Variant('s', 'Testspeler'), 'PlaybackStatus': GLib.Variant('s', st['s']),
            'Metadata': GLib.Variant('a{sv}', {'xesam:title': GLib.Variant('s', t[0]), 'xesam:artist': GLib.Variant('as', [t[1]])}),
            'CanGoNext': GLib.Variant('b', True), 'CanGoPrevious': GLib.Variant('b', True)}[prop]
node = Gio.DBusNodeInfo.new_for_xml(XML)
def acq(c, n):
    for i in node.interfaces: c.register_object('/org/mpris/MediaPlayer2', i, call, get, None)
Gio.bus_own_name(Gio.BusType.SESSION, 'org.mpris.MediaPlayer2.testspeler', 0, acq, None, None)
GLib.MainLoop().run()
