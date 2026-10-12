#!/usr/bin/env python3
"""Rev 34f: Polder OS lock screen for polder-comp (Wayland). Same UI as the X11 lock (lockui.LockUI: clock, date,
avatar, Dutch text, blurred wallpaper) but locked through ext-session-lock-v1 (gtk-session-lock): the compositor
covers every output and routes all input to us until we call unlock; if this process dies the session STAYS locked.
PAM ('login' service) checks the password of the user running this process. Fallback: polder-lock-wayland.sh (swaylock)."""
import os, sys, pwd, threading, subprocess, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('GtkSessionLock', '0.1')
import lockui
from lockui import Gtk, Gdk, GLib, S
from gi.repository import GtkSessionLock
PID = os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'osb-lock-wl.pid')

class Lock(lockui.LockUI):
    def __init__(self, lock):
        me = pwd.getpwuid(os.getuid()); self.lock = lock; self.user = me.pw_name
        s = S.load(); display = s.get('display_name') or me.pw_gecos.split(',')[0] or me.pw_name; hint = None
        if os.environ.get('OSB_LOCK_TEST_ACCOUNT'):   # box-only test arrangement, shown honestly on screen
            display = s.get('display_name') or 'Gebruiker'; hint = f'Testaccount voor deze prototype-box: {me.pw_name}'
        super().__init__([{'name': me.pw_name, 'display': display, 'face': os.path.join(me.pw_dir, '.face')}], hint=hint, popup=False)
        self.set_decorated(False)   # no GTK client-side titlebar on the lock surface

    def authenticate(self, user, pw, done):
        def work():
            try:
                import pam   # python3-pampy
                ok = pam.pam().authenticate(self.user, pw, service='login'); why = '' if ok else 'Onjuist wachtwoord'
            except Exception as e:   # never leave the UI stuck on 'Controleren…'
                print('pam error:', e, flush=True); ok, why = False, 'Wachtwoordcontrole niet beschikbaar'
            GLib.idle_add(done, ok, why)
        threading.Thread(target=work, daemon=True).start()

    def unlocked(self):
        self.lock.unlock_and_destroy(); Gdk.Display.get_default().flush()
        print('unlocked', flush=True); GLib.timeout_add(200, Gtk.main_quit)

    def power(self, action):
        # SAFETY: the prototype never powers off/logs out the box; the ISO maps these to systemctl/loginctl.
        self.msg.set_text({'shutdown': 'Uitschakelen is uitgeschakeld in het prototype', 'logout': 'Afmelden is uitgeschakeld in het prototype'}[action])
        if os.environ.get('POLDEROS_ISO'):
            subprocess.Popen({'shutdown': ['systemctl', 'poweroff'], 'logout': ['sh', '-c', 'loginctl terminate-session "$XDG_SESSION_ID"']}[action])

def main():
    if not GtkSessionLock.is_supported(): print('ext-session-lock-v1 not supported', flush=True); sys.exit(3)
    lock = GtkSessionLock.prepare_lock(); lock.lock_lock()
    disp = Gdk.Display.get_default(); ui = None
    for i in range(disp.get_n_monitors()):   # full UI on the primary monitor, blurred wallpaper on the others
        mon = disp.get_monitor(i)
        if ui is None and (mon.is_primary() or i == disp.get_n_monitors() - 1 or disp.get_primary_monitor() is None):
            ui = w = Lock(lock)
        else:
            w = Gtk.Window(); w.set_name('lockwin'); w.set_decorated(False)
        lock.new_surface(w, mon); w.show_all()
    ui.entry.grab_focus(); print('locked', flush=True)
    Gtk.main()

if __name__ == '__main__':
    try: os.kill(int(open(PID).read()), 0); print('already locked'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # a stray pkill must not unlock (the compositor would keep it locked anyway)
    try: main()
    finally:
        try: os.remove(PID)
        except OSError: pass
