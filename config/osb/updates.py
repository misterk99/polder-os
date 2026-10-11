#!/usr/bin/env python3
"""Automatic updates (Revision 26). Shared by osb-settingsd (reboot check + notification), QS (Update pill) and
Instellingen > Over. System side lives in the ISO: unattended-upgrades via apt-daily timers + polder-flatpak-update.timer."""
import os, re, glob, time, subprocess, threading
REBOOT = '/var/run/reboot-required'
AUTO = '/etc/apt/apt.conf.d/20auto-upgrades'
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'polder-autoupdate')

def reboot_required():
    if not os.path.exists(REBOOT): return None
    pk = []
    try: pk = sorted(set(open(REBOOT + '.pkgs').read().split()))
    except OSError: pass
    return {'since': os.path.getmtime(REBOOT), 'pkgs': pk}

def auto_enabled():
    try: return bool(re.search(r'Unattended-Upgrade\s+"1"', open(AUTO).read()))
    except OSError: return None      # unattended-upgrades not configured on this system

def set_auto(on):
    """Writes 20auto-upgrades via the root helper (pkexec -> polkit password prompt; sudo -n fallback on the prototype box)."""
    arg = 'on' if on else 'off'
    for cmd in (['pkexec', HELPER, arg], ['sudo', '-n', HELPER, arg]):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0: return True
        except Exception: pass
    return False

def last_update():
    """(timestamp, source) of the last real package upgrade: unattended-upgrades log, else apt history."""
    best = None
    for f, rx in (('/var/log/unattended-upgrades/unattended-upgrades.log', r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO (?:All upgrades installed|Packages that will be upgraded)'),
                  ('/var/log/apt/history.log', r'^End-Date: (\d{4}-\d\d-\d\d\s+\d\d:\d\d:\d\d)')):
        try:
            hits = re.findall(rx, open(f, errors='replace').read(), re.M)
            if hits:
                t = time.mktime(time.strptime(re.sub(r'\s+', ' ', hits[-1]), '%Y-%m-%d %H:%M:%S'))
                if not best or t > best[0]: best = (t, 'unattended-upgrades' if 'unattended' in f else 'apt')
        except OSError: pass
    return best

def check(cb):
    """Refresh + count updates via PackageKit (same backend as Polder Store); flatpak counted separately. cb(dict) in a thread."""
    def work():
        out = {'apt': None, 'flatpak': None, 'error': None}
        try:
            import gi; gi.require_version('PackageKitGlib', '1.0'); from gi.repository import PackageKitGlib as PK
            c = PK.Client(); c.refresh_cache(False, None, lambda *a: None, None)
            out['apt'] = len(c.get_updates(PK.FilterEnum.NONE, None, lambda *a: None, None).get_package_array())
        except Exception as e: out['error'] = f'PackageKit: {e}'
        try:
            r = subprocess.run(['flatpak', 'remote-ls', '--updates', '--columns=application'], capture_output=True, text=True, timeout=60)
            if r.returncode == 0: out['flatpak'] = len([l for l in r.stdout.splitlines() if l.strip()])
        except Exception: pass
        cb(out)
    threading.Thread(target=work, daemon=True).start()
