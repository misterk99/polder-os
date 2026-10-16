#!/usr/bin/env python3
"""Polder OS LightDM greeter (same look as the lock screen). Runs under LightDM via liblightdm-gobject
(gir1.2-lightdm-1). `--preview [--users "Anna,Sanne"]` renders the UI without LightDM (no real login possible)."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lockui
from lockui import Gtk, Gdk, GLib
ap = argparse.ArgumentParser(); ap.add_argument('--preview', action='store_true'); ap.add_argument('--users', default='')
args = ap.parse_args()
SESSION = 'polderos'

class Greeter(lockui.LockUI):
    POWER = [('system-shutdown-symbolic', _('Shut down'), 'shutdown'), ('system-reboot-symbolic', _('Restart'), 'restart')]
    def __init__(self):
        self.ldm = None; users = []
        if not args.preview:
            import gi; gi.require_version('LightDM', '1'); from gi.repository import LightDM
            self.LightDM = LightDM; self.ldm = LightDM.Greeter()
            self.ldm.connect('show-prompt', self.on_prompt); self.ldm.connect('show-message', lambda g, t, ty: self.msg.set_text(t))
            self.ldm.connect('authentication-complete', self.on_complete); self.ldm.connect_to_daemon_sync()
            for u in LightDM.UserList.get_instance().get_users():
                users.append({'name': u.get_name(), 'display': u.get_display_name() or u.get_name(), 'face': u.get_image()})
        else:
            names = [n.strip() for n in args.users.split(',') if n.strip()] or [_('User')]
            users = [{'name': n.lower(), 'display': n} for n in names]
        super().__init__(users or [{'name': '', 'display': _('User')}],
                         hint=_('PREVIEW — not via LightDM, signing in is disabled') if args.preview else None, popup=False)
        self.session = SESSION
        sessions = ([(s.get_key(), s.get_name()) for s in self.LightDM.get_sessions()]
                    if self.ldm else [('polderos', 'Polder OS (X11)'), ('polderos-wayland', 'Polder OS (Wayland)')])
        if sessions:
            default = self.ldm.get_default_session_hint() if self.ldm else SESSION
            available = {key for key, _x in sessions}
            self.session = default if default in available else (SESSION if SESSION in available else sessions[0][0])
        if len(sessions) > 1:
            row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            row.pack_start(Gtk.Label(label=_('Desktop')), False, False, 0)
            self.session_choice = Gtk.ComboBoxText()
            for key, name in sessions: self.session_choice.append(key, name)
            self.session_choice.set_active_id(self.session)
            self.session_choice.connect('changed', lambda choice: setattr(self, 'session', choice.get_active_id() or SESSION))
            row.pack_start(self.session_choice, False, False, 0)
            self.col.pack_start(row, False, False, 0)
        self.pw_pending = None
        self.fullscreen(); self.show_all(); self.entry.grab_focus()

    def authenticate(self, user, pw, done):
        self.done = done
        if args.preview: GLib.timeout_add(600, done, False, _('Preview: signing in is not possible')); return
        self.pw_pending = pw
        if self.ldm.get_in_authentication(): self.ldm.cancel_authentication()
        self.ldm.authenticate(user['name'])

    def on_prompt(self, g, text, ptype):
        if self.pw_pending is not None: g.respond(self.pw_pending); self.pw_pending = None

    def on_complete(self, g):
        if g.get_is_authenticated(): self.done(True)
        else: self.done(False, _('Incorrect password'))

    def unlocked(self):
        try: self.ldm.start_session_sync(self.session)
        except GLib.Error as e: self.msg.set_text(_('Starting session failed: {message}').format(message=e.message))

    def power(self, action):
        if args.preview: self.msg.set_text(_('Preview: {action} not performed').format(action=action)); return
        {'shutdown': self.LightDM.shutdown, 'restart': self.LightDM.restart}[action]()

Greeter(); Gtk.main()
