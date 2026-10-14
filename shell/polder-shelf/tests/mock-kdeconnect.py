#!/usr/bin/env python3
"""TEST FIXTURE ONLY - not part of Polder OS. A fake kdeconnectd on the (test) session bus implementing the subset of
the real org.kde.kdeconnect D-Bus API (KDE Connect 24.12: core/daemon.h, core/device.h, plugins/*) that the
Telefoon-hub uses, with clean made-up data. Every method call is logged to stdout so tests can assert on it.
  mock-kdeconnect.py --state paired|unpaired|request|none  [--sftp-root DIR]"""
import argparse, os, sys
from gi.repository import Gio, GLib

ap = argparse.ArgumentParser(); ap.add_argument('--state', default='paired'); ap.add_argument('--sftp-root', default='/tmp/mock-phone')
A = ap.parse_args()
DEV = 'a1b2c3d4_testtelefoon'; ROOT = '/modules/kdeconnect'; DP = f'{ROOT}/devices/{DEV}'
dev = {'name': 'Testtelefoon', 'type': 'smartphone', 'iconName': 'smartphone', 'verificationKey': '7F3A 91C2 0B6E',
       'statusIconName': 'smartphone-connected', 'isReachable': A.state != 'none', 'isPaired': A.state == 'paired',
       'isPairRequested': False, 'isPairRequestedByPeer': A.state == 'request', 'pairState': 2 if A.state == 'paired' else 0,
       'supportedPlugins': ['kdeconnect_battery', 'kdeconnect_notifications', 'kdeconnect_findmyphone', 'kdeconnect_share',
                            'kdeconnect_clipboard', 'kdeconnect_sftp', 'kdeconnect_connectivity_report']}
plugins = {'kdeconnect_clipboard': True}
notifs = {'101': {'internalId': '101', 'appName': 'Berichten', 'ticker': '', 'title': 'Testcontact', 'text': 'Kom je vanavond ook eten?',
                  'iconPath': '', 'dismissable': True, 'hasIcon': False, 'silent': False, 'replyId': 'r101'},
          '102': {'internalId': '102', 'appName': 'Agenda', 'ticker': '', 'title': 'Tandarts', 'text': 'Morgen om 09:30',
                  'iconPath': '', 'dismissable': True, 'hasIcon': False, 'silent': False, 'replyId': ''}}
sftp = {'mounted': False}
def log(*a): print('CALL', *a, flush=True)

def P(name, sig, access='read'): return f'<property name="{name}" type="{sig}" access="{access}"/>'
XML = f'''<node>
<interface name="org.kde.kdeconnect.daemon">
 <method name="devices"><arg type="b" direction="in"/><arg type="b" direction="in"/><arg type="as" direction="out"/></method>
 <method name="forceOnNetworkChange"/><method name="announcedName"><arg type="s" direction="out"/></method></interface>
<interface name="org.kde.kdeconnect.device">
 {P('name','s')}{P('type','s')}{P('iconName','s')}{P('verificationKey','s')}{P('statusIconName','s')}{P('isReachable','b')}
 {P('isPaired','b')}{P('isPairRequested','b')}{P('isPairRequestedByPeer','b')}{P('pairState','i')}{P('supportedPlugins','as')}
 <method name="requestPairing"/><method name="unpair"/><method name="acceptPairing"/><method name="cancelPairing"/>
 <method name="hasPlugin"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
 <method name="isPluginEnabled"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
 <method name="setPluginEnabled"><arg type="s" direction="in"/><arg type="b" direction="in"/></method></interface>
<interface name="org.kde.kdeconnect.device.battery">{P('charge','i')}{P('isCharging','b')}</interface>
<interface name="org.kde.kdeconnect.device.connectivity_report">{P('cellularNetworkType','s')}{P('cellularNetworkStrength','i')}</interface>
<interface name="org.kde.kdeconnect.device.findmyphone"><method name="ring"/></interface>
<interface name="org.kde.kdeconnect.device.share"><method name="shareUrl"><arg type="s" direction="in"/></method>
 <method name="shareUrls"><arg type="as" direction="in"/></method><method name="shareText"><arg type="s" direction="in"/></method></interface>
<interface name="org.kde.kdeconnect.device.clipboard">{P('isAutoShareDisabled','b')}<method name="sendClipboard"/></interface>
<interface name="org.kde.kdeconnect.device.sftp"><method name="mountAndWait"><arg type="b" direction="out"/></method>
 <method name="isMounted"><arg type="b" direction="out"/></method><method name="mountPoint"><arg type="s" direction="out"/></method>
 <method name="getMountError"><arg type="s" direction="out"/></method>
 <method name="getDirectories"><arg type="a{{sv}}" direction="out"/></method><method name="unmount"/></interface>
<interface name="org.kde.kdeconnect.device.notifications"><method name="activeNotifications"><arg type="as" direction="out"/></method>
 <method name="sendReply"><arg type="s" direction="in"/><arg type="s" direction="in"/></method></interface>
<interface name="org.kde.kdeconnect.device.notifications.notification">
 {P('internalId','s')}{P('appName','s')}{P('ticker','s')}{P('title','s')}{P('text','s')}{P('iconPath','s')}{P('dismissable','b')}
 {P('hasIcon','b')}{P('silent','b')}{P('replyId','s')}<method name="dismiss"/><method name="reply"/>
 <method name="sendReply"><arg type="s" direction="in"/></method></interface>
</node>'''
NODE = Gio.DBusNodeInfo.new_for_xml(XML); I = {i.name: i for i in NODE.interfaces}
SIG = {'s': 's', 'b': 'b', 'i': 'i', 'as': 'as'}
regs = {}

def ret(inv, sig=None, *v): inv.return_value(GLib.Variant(f'({sig})', v) if sig else None)

def on_call(conn, sender, path, iface, m, p, inv):
    a = p.unpack(); log(path.replace(DP, '<dev>'), m, *a)
    if iface == 'org.kde.kdeconnect.daemon':
        if m == 'devices':
            reach, paired = a
            ok = (not reach or dev['isReachable']) and (not paired or dev['isPaired']) and A.state != 'none'
            return ret(inv, 'as', [DEV] if ok else [])
        if m == 'announcedName': return ret(inv, 's', 'Polder-laptop')
        return ret(inv)
    if iface == 'org.kde.kdeconnect.device':
        if m == 'requestPairing':
            dev['isPairRequested'] = True
            def done(): dev.update(isPaired=True, isPairRequested=False, pairState=2); register_plugins(conn); log('PAIRED'); return False
            GLib.timeout_add(2500, done)   # the phone user accepts after a moment
        elif m == 'acceptPairing': dev.update(isPaired=True, isPairRequestedByPeer=False, pairState=2); register_plugins(conn)
        elif m == 'cancelPairing': dev.update(isPairRequested=False, isPairRequestedByPeer=False)
        elif m == 'unpair': dev.update(isPaired=False, pairState=0)
        elif m == 'hasPlugin': return ret(inv, 'b', a[0] in dev['supportedPlugins'])
        elif m == 'isPluginEnabled': return ret(inv, 'b', plugins.get(a[0], True))
        elif m == 'setPluginEnabled': plugins[a[0]] = a[1]
        return ret(inv)
    if iface.endswith('.sftp'):
        if m == 'mountAndWait': sftp['mounted'] = os.path.isdir(A.sftp_root); return ret(inv, 'b', sftp['mounted'])
        if m == 'isMounted': return ret(inv, 'b', sftp['mounted'])
        if m == 'mountPoint': return ret(inv, 's', A.sftp_root)
        if m == 'getMountError': return ret(inv, 's', '')
        if m == 'getDirectories':
            return ret(inv, 'a{sv}', {os.path.join(A.sftp_root, 'DCIM/Camera'): GLib.Variant('s', 'Camera'),
                                      os.path.join(A.sftp_root, 'Download'): GLib.Variant('s', 'Downloads')})
        sftp['mounted'] = False; return ret(inv)
    if iface.endswith('.device.notifications'):
        if m == 'activeNotifications': return ret(inv, 'as', list(notifs))
        return ret(inv)
    if iface.endswith('.notification'):
        nid = path.rsplit('/', 1)[1]
        if m == 'dismiss': notifs.pop(nid, None); unregister(conn, path)
        return ret(inv)
    return ret(inv)

def on_get(conn, sender, path, iface, prop):
    if iface == 'org.kde.kdeconnect.device': v = dev[prop]
    elif iface.endswith('.battery'): v = {'charge': 76, 'isCharging': True}[prop]
    elif iface.endswith('.connectivity_report'): v = {'cellularNetworkType': '4G', 'cellularNetworkStrength': 3}[prop]
    elif iface.endswith('.clipboard'): v = not plugins.get('kdeconnect_clipboard', True)
    else: v = notifs[path.rsplit('/', 1)[1]][prop]
    t = next(p.signature for p in I[iface].properties if p.name == prop)
    return GLib.Variant(t, v)

def reg(conn, path, iface):
    regs.setdefault(path, []).append(conn.register_object(path, I[iface], on_call, on_get, None))
def unregister(conn, path):
    for r in regs.pop(path, []): conn.unregister_object(r)

def register_plugins(conn):
    if f'{DP}/battery' in regs: return
    for sub, iface in [('battery', 'battery'), ('connectivity_report', 'connectivity_report'), ('findmyphone', 'findmyphone'),
                       ('share', 'share'), ('clipboard', 'clipboard'), ('sftp', 'sftp'), ('notifications', 'notifications')]:
        reg(conn, f'{DP}/{sub}', f'org.kde.kdeconnect.device.{iface}')
    for nid in notifs: reg(conn, f'{DP}/notifications/{nid}', 'org.kde.kdeconnect.device.notifications.notification')

def acquired(conn, name):
    reg(conn, ROOT, 'org.kde.kdeconnect.daemon')
    if A.state != 'none': reg(conn, DP, 'org.kde.kdeconnect.device')
    if dev['isPaired']: register_plugins(conn)
    print('READY', A.state, flush=True)

Gio.bus_own_name(Gio.BusType.SESSION, 'org.kde.kdeconnect', Gio.BusNameOwnerFlags.NONE, acquired, None, lambda *a: sys.exit('name lost'))
GLib.MainLoop().run()
