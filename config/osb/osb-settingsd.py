#!/usr/bin/env python3
"""Watches ~/.config/osb/settings.json and applies changes live; auto theme by time; periodic ICS feed sync.
Plain Python (no GTK) to stay light: polls the file mtime once per second."""
import os, sys, time, threading, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'calendar')); sys.path.insert(0, os.path.join(HERE, '..', 'weather'))
import osbsettings as S, apply as A, feeds, weather as W
GROUPS = {'theme': ('theme', 'accent', 'wallpaper'), 'kbd': ('kbd_layout', 'kbd_variant'),
          'shelf': ('clock24', 'show_date'), 'night': ('night_light',), 'motion': ('reduced_motion',)}

def feed_sync():
    try: feeds.sync_all()
    except Exception as e: print('feeds', e, flush=True)

def weather_fetch():
    try: print('weather', W.fetch().get('ok'), flush=True)
    except Exception as e: print('weather', e, flush=True)
    subprocess.Popen(['pkill', '-USR1', '-x', 'tint2'])   # re-run executors -> pill updates (or hides) now

def reboot_watch():
    """Revision 26: when /var/run/reboot-required appears, one real notification with a reboot action + state file for QS/shelf."""
    import json, updates as U
    seen = None
    while True:
        r = U.reboot_required(); st = '/tmp/osb-update.json'
        if r and r['since'] != seen:
            seen = r['since']; json.dump(r, open(st, 'w'))
            subprocess.Popen(['pkill', '-USR1', '-x', 'tint2'])
            n = subprocess.run(['notify-send', '-a', 'Systeem', '-i', 'system-software-update-symbolic', '-A', 'reboot=Nu opnieuw opstarten', '--wait',
                                'Opnieuw opstarten om bij te werken', 'Er zijn updates geïnstalleerd' + (f" ({', '.join(r['pkgs'][:3])})" if r['pkgs'] else '') + '.'],
                               capture_output=True, text=True).stdout.strip()
            if n == 'reboot':
                if os.environ.get('POLDEROS_ISO'): subprocess.Popen(['systemctl', 'reboot'])
                else: print('reboot requested (prototype box: not rebooting)', flush=True)
        elif not r and (seen or os.path.exists(st)):   # also clears a stale state file left by a restarted shell
            seen = None
            try: os.remove(st)
            except OSError: pass
            subprocess.Popen(['pkill', '-USR1', '-x', 'tint2'])
        time.sleep(30)

def idle_lock():
    """Auto-lock: poll X idle time (XScreenSaver extension via python-xlib) every 5 s."""
    try:
        from Xlib import display; d = display.Display(); root = d.screen().root
        if not d.has_extension('MIT-SCREEN-SAVER'): print('idle: no MIT-SCREEN-SAVER', flush=True); return
    except Exception as e: print('idle', e, flush=True); return
    armed = True
    while True:
        time.sleep(5)
        try:
            mins = int(S.load().get('lock_idle_min', 10)); idle = root.screensaver_query_info().idle / 1000
        except Exception as e: print('idle', e, flush=True); continue
        if not mins: continue
        if idle < 5: armed = True
        elif armed and idle >= mins * 60 and not os.path.exists('/tmp/osb-lock.pid'):
            armed = False; print(time.strftime('%H:%M:%S'), 'idle lock', flush=True)
            subprocess.Popen([os.path.join(HERE, '..', 'lock', 'lock-now.sh')], start_new_session=True)

def polder_sync(restore=False):   # Revision 30: Polder Sync (runs in a thread, never blocks the loop)
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sync')); import polder_sync as Y
        ok, msg = Y.sync_safe(restore); print(time.strftime('%H:%M:%S'), 'sync', ok, msg, flush=True)
    except Exception as e: print('sync', e, flush=True)

def main():
    wayland_session = bool(os.environ.get('POLDER_COMP'))
    if not wayland_session:
        threading.Thread(target=idle_lock, daemon=True).start()
    threading.Thread(target=reboot_watch, daemon=True).start()
    s = S.load()
    if not os.path.exists(S.FILE): S.save(s)
    A.kbd(s)
    A.motion(s)
    if not wayland_session: A.night(s)
    if wayland_session: A.displays(s)
    display_signature = None; display_check = 0
    mtime = os.path.getmtime(S.FILE); eff = S.effective_theme(s); last_sync = 0; last_wx = 0
    sync_due = time.time() + 5 if s.get('sync_enabled') else 0   # Rev 30: sync at login, then debounced 15 s after changes + every 30 min
    SYNC_IGNORE = {'sync_last_request'}
    while True:
        time.sleep(1)
        try: m = os.path.getmtime(S.FILE)
        except OSError: continue
        if m != mtime:
            mtime = m; n = S.load()
            for fn, keys in GROUPS.items():
                if any(n.get(k) != s.get(k) for k in keys):
                    if wayland_session and fn == 'night':
                        print(time.strftime('%H:%M:%S'), fn, 'requires native Wayland support or a new session', flush=True)
                        continue
                    print(time.strftime('%H:%M:%S'), 'apply', fn, flush=True); getattr(A, fn)(n)
            if [f['id'] for f in n['feeds']] != [f['id'] for f in s['feeds']]: last_sync = 0
            if n.get('weather_loc') != s.get('weather_loc'): last_wx = 0
            if n.get('sync_enabled') and any(n.get(k) != s.get(k) for k in set(n) | set(s) if not k.startswith('sync_')): sync_due = time.time() + 15
            if n.get('sync_request') != s.get('sync_request') and n.get('sync_enabled'): sync_due = time.time()
            s = n; eff = S.effective_theme(s)
        if wayland_session and time.monotonic() >= display_check:
            display_check = time.monotonic() + 3
            try:
                import wayland_display as D
                signature = sorted((o['name'], tuple(D.identity(o))) for o in D.outputs())
                if display_signature is not None and signature != display_signature: A.displays(s)
                display_signature = signature
            except Exception as exc:
                print('display detection:', exc, flush=True)
        if s.get('theme') == 'auto' and S.effective_theme(s) != eff:    # auto: switch at 07:00 / 19:00
            eff = S.effective_theme(s); print('auto theme ->', eff, flush=True); A.theme(s)
        if s['feeds'] and time.time() - last_sync > 60 * max(5, int(s.get('feed_refresh_min', 60))):
            last_sync = time.time(); threading.Thread(target=feed_sync, daemon=True).start()

        if s.get('sync_enabled') and not sync_due: sync_due = time.time() + 1800
        if sync_due and time.time() >= sync_due:
            sync_due = time.time() + 1800 if s.get('sync_enabled') else 0
            threading.Thread(target=polder_sync, daemon=True).start()
        if time.time() - last_wx > 1800:   # Revision 25: Polder Weer, every 30 min (Open-Meteo)
            last_wx = time.time(); threading.Thread(target=weather_fetch, daemon=True).start()

if __name__ == '__main__': main()
