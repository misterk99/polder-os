#!/usr/bin/env python3
"""Polder OS lock screen. Grabs keyboard+pointer on a fullscreen override-redirect window; unlocks only after
PAM ('login' service) accepts the password of the user running this process. Single instance (/tmp/osb-lock.pid)."""
import os, sys, pwd, threading, subprocess, signal, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lockui
from lockui import Gtk, Gdk, GLib, S
PID = '/tmp/osb-lock.pid'

class Lock(lockui.LockUI):
    def __init__(self):
        me = pwd.getpwuid(os.getuid())
        s = S.load(); display = s.get('display_name') or me.pw_gecos.split(',')[0] or me.pw_name
        hint = None
        if os.environ.get('OSB_LOCK_TEST_ACCOUNT'):   # box-only test arrangement, shown honestly on screen
            display = s.get('display_name') or 'Gebruiker'; hint = f'Testaccount voor deze prototype-box: {me.pw_name}'
        face = os.path.join(me.pw_dir, '.face')
        self.user = me.pw_name
        super().__init__([{'name': me.pw_name, 'display': display, 'face': face}], hint=hint, popup=True)
        self.prev = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True, timeout=3).stdout.strip()
        self.show_all(); self.present(); self.grabbed = False; GLib.timeout_add(50, self.grab)
        GLib.timeout_add(1500, self.keep_above)

    def grab(self):
        """Keep trying until we own keyboard+pointer (another popup/launcher may briefly hold a grab)."""
        seat = Gdk.Display.get_default().get_default_seat()
        st = seat.grab(self.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        self.grabbed = st == Gdk.GrabStatus.SUCCESS
        if self.grabbed: self.entry.grab_focus(); print('locked: grab ok', flush=True); return False
        return True

    def keep_above(self):
        self.get_window().raise_(); return True     # override-redirect: stay on top of new windows

    def authenticate(self, user, pw, done):
        def work():
            import pam
            p = pam.pam(); ok = p.authenticate(self.user, pw, service='login')
            GLib.idle_add(done, ok, '' if ok else ('Onjuist wachtwoord' if 'failure' in (p.reason or '').lower() else f'Onjuist wachtwoord'))
        threading.Thread(target=work, daemon=True).start()

    def unlocked(self):
        Gdk.Display.get_default().get_default_seat().ungrab(); self.hide()
        if self.prev: subprocess.run(['xdotool', 'windowactivate', self.prev], timeout=3, capture_output=True)
        print('unlocked', flush=True); Gtk.main_quit()

    def power(self, action):
        # SAFETY: the prototype never powers off/logs out the box; the ISO maps these to systemctl/loginctl.
        self.msg.set_text({'shutdown': 'Uitschakelen is uitgeschakeld in het prototype', 'logout': 'Afmelden is uitgeschakeld in het prototype'}[action])
        print('would run:', {'shutdown': 'systemctl poweroff', 'logout': 'loginctl terminate-session $XDG_SESSION_ID'}[action], flush=True)
        if os.environ.get('POLDEROS_ISO'):
            subprocess.Popen({'shutdown': ['systemctl', 'poweroff'], 'logout': ['sh', '-c', 'loginctl terminate-session "$XDG_SESSION_ID"']}[action])

if __name__ == '__main__':
    try: os.kill(int(open(PID).read()), 0); print('already locked'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid())); os.chmod(PID, 0o644)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # don't let a stray pkill unlock the screen
    try: Lock(); Gtk.main()
    finally:
        try: os.remove(PID)
        except OSError: pass
