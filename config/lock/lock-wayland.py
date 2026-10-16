#!/usr/bin/env python3
"""Rev 34f: Polder OS lock screen for polder-comp (Wayland). Same UI as the X11 lock (lockui.LockUI: clock, date,
avatar, Dutch text, blurred wallpaper) but locked through ext-session-lock-v1 (gtk-session-lock): the compositor
covers every output and routes all input to us until we call unlock; if this process dies the session STAYS locked.
PAM ('login' service) checks the password of the user running this process. Fallback: polder-lock-wayland.sh (swaylock)."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, sys, pwd, threading, subprocess, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('GtkSessionLock', '0.1')
import lockui
from lockui import Gtk, Gdk, GLib, S
from gi.repository import GtkSessionLock

class Lock(lockui.LockUI):
    def __init__(self, lock):
        me = pwd.getpwuid(os.getuid()); self.lock = lock; self.user = me.pw_name
        s = S.load(); display = s.get('display_name') or me.pw_gecos.split(',')[0] or me.pw_name; hint = None
        if os.environ.get('OSB_LOCK_TEST_ACCOUNT'):   # box-only test arrangement, shown honestly on screen
            display = s.get('display_name') or _('User'); hint = _('Test account for this prototype box: {pw_name}').format(pw_name=me.pw_name)
        super().__init__([{'name': me.pw_name, 'display': display, 'face': os.path.join(me.pw_dir, '.face')}], hint=hint, popup=False)
        self.set_decorated(False)   # no GTK client-side titlebar on the lock surface
        # The shared X11 UI requests the whole screen as a minimum. A Wayland
        # lock surface must exactly match its output's configured size, which
        # can be smaller than the combined desktop (or change with scaling).
        self.set_size_request(-1, -1)
        self.set_default_size(1, 1)
        self.entry.connect('key-press-event', self.entry_key)

    def entry_key(self, _entry, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self.entry.get_sensitive(): self.submit()
            return True
        return False

    def authenticate(self, user, pw, done):
        def work():
            try:
                import pam   # python3-pampy
                ok = pam.pam().authenticate(self.user, pw, service='login'); why = '' if ok else _('Incorrect password')
            except Exception as e:   # never leave the UI stuck on 'Controleren…'
                print('pam error:', e, flush=True); ok, why = False, _('Password check not available')
            if not ok: print('authentication rejected', flush=True)
            GLib.idle_add(done, ok, why)
        threading.Thread(target=work, daemon=True).start()

    def unlocked(self):
        self.lock.unlock()

    def power(self, action):
        # SAFETY: the prototype never powers off/logs out the box; the ISO maps these to systemctl/loginctl.
        self.msg.set_text({'shutdown': _('Shutting down is disabled in the prototype'), 'logout': _('Signing out is disabled in the prototype')}[action])
        if os.environ.get('POLDEROS_ISO'):
            subprocess.Popen({'shutdown': ['systemctl', 'poweroff'], 'logout': ['sh', '-c', 'loginctl terminate-session "$XDG_SESSION_ID"']}[action])

class SessionLock:
    def __init__(self):
        self.display = Gdk.Display.get_default()
        self.windows = {}
        self.confirmed = False
        self.ended = False
        self.result = 3
        self.lock = GtkSessionLock.prepare_lock()
        self.lock.connect('locked', self.on_locked)
        self.lock.connect('finished', self.on_finished)
        self.display.connect('monitor-added', self.monitor_added)
        self.display.connect('monitor-removed', self.monitor_removed)

    def on_locked(self, *_x):
        self.confirmed = True
        # The compositor's locked event, not window creation or a PID, gates suspend.
        ready = os.environ.pop('POLDER_LOCK_READY_FD', None)
        if ready is not None:
            fd = int(ready)
            try: os.write(fd, b'\n')
            except BrokenPipeError: pass
            finally: os.close(fd)
        print('locked: compositor acknowledged', flush=True)
        # Background rendering can take time; the opaque compositor cover already protects us.
        GLib.idle_add(self.show_monitors)

    def show_monitors(self):
        for index in range(self.display.get_n_monitors()):
            self.add_monitor(self.display.get_monitor(index))
        return False

    def add_monitor(self, monitor):
        if self.ended or not self.confirmed or monitor in self.windows:
            return False
        if not any(self.display.get_monitor(i) == monitor for i in range(self.display.get_n_monitors())):
            return False
        try:
            window = Lock(self)
            self.windows[monitor] = window
            self.lock.new_surface(window, monitor)
            window.show_all(); window.entry.grab_focus()
        except Exception as error:
            # Leave the compositor locked and let the supervisor start its fallback.
            print(f'Could not create lock screen: {error}', flush=True)
            Gtk.main_quit()
        return False

    def monitor_added(self, _display, monitor):
        GLib.idle_add(self.add_monitor, monitor)

    def monitor_removed(self, _display, monitor):
        window = self.windows.pop(monitor, None)
        if window is not None: window.destroy()

    def on_finished(self, *_x):
        self.ended = True
        self.lock.destroy()
        print('Compositor refused the session lock', flush=True)
        Gtk.main_quit()

    def unlock(self):
        if self.ended or not self.confirmed: return
        self.ended = True
        self.lock.unlock_and_destroy()
        for window in self.windows.values(): window.destroy()
        self.windows.clear()
        # Wait for the unlock request to reach the compositor before exiting.
        self.display.sync()
        self.result = 0
        print('unlocked', flush=True)
        Gtk.main_quit()


def main():
    if not GtkSessionLock.is_supported():
        print('ext-session-lock-v1 not supported', flush=True)
        return 3
    session = SessionLock()
    session.lock.lock_lock()
    Gtk.main()
    return session.result

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # a stray pkill must not unlock (the compositor would keep it locked anyway)
    sys.exit(main())
