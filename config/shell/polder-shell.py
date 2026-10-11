#!/usr/bin/env python3
"""polder-shell (Revision 27): ONE process for the always-running Polder OS services, one GTK main loop.
Modules: notify (org.freedesktop.Notifications), shelf (+ desktop window), launcher (hidden window), clipboard,
settings daemon (thread), hotkeys (keyd, thread with its own X connection). Each module starts in its own try/except:
a failing module is logged and skipped, the rest keeps running. IPC: unix socket (osb/shellipc.py) instead of
per-process signals. The session script restarts polder-shell if it exits; POLDER_SHELL=0 = old separate processes."""
import os, sys, time, socket, threading, traceback, importlib.util
C = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ['POLDER_SHELL'] = '1'
for d in ('osb', 'notify', 'calendar', 'weather', 'wm', 'shelf', 'launcher', 'clip'): sys.path.insert(0, os.path.join(C, d))
import gi; gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, GLib
import shellipc, faulthandler, signal
faulthandler.register(signal.SIGQUIT, all_threads=True)   # debug: kill -QUIT dumps all thread stacks to the log
PID = '/tmp/polder-shell.pid'

def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)

def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(C, rel)); m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m; spec.loader.exec_module(m); return m

class Shell:
    def __init__(self):
        self.mods = {}; self.objs = {}
        for name, fn in (('notify', self.m_notify), ('shelf', self.m_shelf), ('launcher', self.m_launcher),
                         ('clip', self.m_clip), ('settingsd', self.m_settingsd), ('keyd', self.m_keyd)):
            t = time.time()
            try: fn(); log(f'module {name}: ok ({(time.time() - t) * 1000:.0f} ms)')
            except Exception: log(f'module {name}: FAILED\n' + traceback.format_exc())
        self.ipc()

    def m_notify(self):
        m = self.mods['notify'] = load('osb_notifyd', 'notify/osb-notifyd.py'); self.objs['notify'] = m.Daemon()
    def m_shelf(self):
        m = self.mods['shelf'] = load('shelf', 'shelf/shelf.py'); self.objs['shelf'] = m.Shelf()
    def m_launcher(self):
        m = self.mods['launcher'] = load('launcher', 'launcher/launcher.py'); self.objs['launcher'] = m.Launcher()
    def m_clip(self):
        m = self.mods['clip'] = load('clipd', 'clip/clipd.py'); self.objs['clip'] = m.Clip()
    def m_settingsd(self):
        m = self.mods['settingsd'] = load('osb_settingsd', 'osb/osb-settingsd.py')
        threading.Thread(target=self.guard, args=('settingsd', m.main), daemon=True).start()
    def m_keyd(self):
        # keyd grabs keys at import and loops in next_event(): run the whole module in a thread, dispatch toggles to the main loop
        def run():
            import runpy
            g = {'__name__': 'keyd_mod'}
            src = open(os.path.join(C, 'wm/keyd.py')).read()
            src = src.replace('DISPATCH = None', 'DISPATCH = _shell_dispatch', 1)
            g['_shell_dispatch'] = lambda mode: GLib.idle_add(self.once, mode)
            g['__file__'] = os.path.join(C, 'wm/keyd.py')
            exec(compile(src, g['__file__'], 'exec'), g)
        threading.Thread(target=self.guard, args=('keyd', run), daemon=True).start()

    def guard(self, name, fn):
        """Thread modules: restart after a crash (max once per 10 s)."""
        while True:
            t = time.time()
            try: fn(); log(f'{name} returned')
            except Exception: log(f'{name} crashed\n' + traceback.format_exc())
            time.sleep(max(0, 10 - (time.time() - t)))

    def once(self, cmd):
        self.dispatch(cmd); return False   # idle callback: never repeat

    def dispatch(self, cmd):
        try:
            if cmd == 'launcher': self.objs['launcher'].toggle()
            elif cmd == 'clip': self.objs['clip'].toggle()
            elif cmd == 'clip-clear': self.objs['clip'].clear()
            elif cmd == 'notify-reload':
                m = load('osb_notifyd_css', 'notify/osb-notifyd.py'); self.objs['notify'].prov.load_from_data(m.CSS.encode())   # re-exec module: CSS is built from palette.env at import
            elif cmd != 'ping': return False
            return True
        except Exception:
            log(f'dispatch {cmd} failed\n' + traceback.format_exc()); return False

    def ipc(self):
        try: os.unlink(shellipc.SOCK)
        except OSError: pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); self.srv.bind(shellipc.SOCK); os.chmod(shellipc.SOCK, 0o600); self.srv.listen(8)
        threading.Thread(target=self.serve, daemon=True).start()   # blocking accept in a thread; actions go to the main loop via idle_add

    def serve(self):
        while True:
            try: self.on_conn()
            except Exception as e: log('ipc', e)

    def on_conn(self, *a):
        c, _ = self.srv.accept(); c.settimeout(1)
        try:
            cmd = c.recv(64).decode().strip()
            known = cmd in ('launcher', 'clip', 'clip-clear', 'notify-reload', 'ping')
            c.sendall(b'ok\n' if known else b'err\n')      # answer first: showing the launcher can take >1 s the first time
            if known: GLib.idle_add(self.once, cmd)
        except Exception as e: log('ipc', e)
        finally: c.close()
        return True

if __name__ == '__main__':
    try: os.kill(int(open(PID).read()), 0); print('already running'); sys.exit(0)
    except (OSError, ValueError): pass
    open(PID, 'w').write(str(os.getpid()))
    Shell(); Gtk.main()
