#!/usr/bin/env python3
"""Exercise capture UI, recording and consent-driven portal frames on real Wayland.

Run inside dbus-run-session on Linux. Requires the Polder runtime plus test-only
gir1.2-gstreamer-1.0 and gstreamer1.0-pipewire for consuming the portal's remote FD.
Uses a private headless compositor; no existing desktop or user files are touched.
"""
import argparse
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback

import gi
from gi.repository import Gio, GLib


class Smoke:
    def __init__(self, config, compositor, output, portal_wlr, activation):
        self.config, self.binary, self.out = config, compositor, output
        self.portal_wlr = portal_wlr
        self.activation, self.activated_backend_pid = activation, None
        self.out.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='polder-capture-test-')
        self.root = Path(self.temp.name)
        self.children, self.logs, self.checks = [], [], []
        self.env = dict(os.environ)
        for key, suffix in [('HOME', 'home'), ('XDG_RUNTIME_DIR', 'runtime'),
                            ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state')]:
            directory = self.root / suffix
            directory.mkdir(mode=0o700)
            self.env[key] = str(directory)
        self.runtime = Path(self.env['XDG_RUNTIME_DIR'])
        self.env.update(OSB_RUNDIR=str(self.runtime / 'polder'), OSB_FILES_HOME=str(self.root / 'files'),
                        POLDER_CONFIG=str(config), POLDER_COMP='1', POLDER_NO_XWAYLAND='1',
                        WLR_BACKENDS='headless', WLR_RENDERER='pixman', WLR_HEADLESS_OUTPUTS='0',
                        XDG_CURRENT_DESKTOP='PolderOS', XDG_SESSION_TYPE='wayland',
                        GDK_BACKEND='wayland', GTK_IM_MODULE='gtk-im-context-simple',
                        LANG='C.UTF-8', LC_ALL='C.UTF-8')
        self.env.pop('DISPLAY', None)
        self.env.pop('WAYLAND_DISPLAY', None)
        Path(self.env['OSB_RUNDIR']).mkdir(mode=0o700)

    def wait(self, label, callback, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            result = callback()
            if result:
                return result
            time.sleep(.025)
        raise RuntimeError('Timed out: ' + label)

    def spawn(self, name, command):
        log = (self.out / (name + '.log')).open('wb')
        self.logs.append(log)
        process = subprocess.Popen(command, env=self.env, stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        self.children.append(process)
        return process

    def run(self, command, timeout=15):
        return subprocess.run(command, env=self.env, capture_output=True, check=True, timeout=timeout)

    def passed(self, label):
        self.checks.append(label)
        print('PASS ' + label, flush=True)

    def windows(self):
        path = self.runtime / 'polder-windows.json'
        path.unlink(missing_ok=True)
        os.kill(self.compositor.pid, signal.SIGUSR2)
        self.wait('window snapshot', path.exists)
        return json.loads(path.read_text())

    def screenshot(self, filename):
        self.run(['grim', str(self.out / filename)])

    def start(self):
        self.compositor = self.spawn('compositor', [str(self.binary)])
        def socket():
            return next((path.name for path in self.runtime.glob('wayland-*')
                         if stat.S_ISSOCK(path.stat().st_mode)), None)
        self.env['WAYLAND_DISPLAY'] = self.wait('Wayland socket', socket)
        self.env['POLDER_COMP_PID'] = str(self.compositor.pid)
        os.environ.update(self.env)
        # A headless backend has no physical keyboard. Advertise one before GTK maps.
        self.spawn('keyboard', ['wtype', '-s', '120000'])
        time.sleep(.15)
        self.spawn('test-window', ['foot', '-c', '/dev/null', '-a', 'polder-capture-test',
                                  '-T', 'Polder capture test', '-w', '600x400', 'sh', '-c',
                                  "printf '\033[44mPolder capture and portal verification\033[0m\n'; "
                                  "i=0; while :; do printf '\rFrame %s ' \"$i\"; i=$((i+1)); sleep 0.1; done"])
        self.wait('test window', lambda: any(window['app_id'] == 'polder-capture-test' for window in self.windows()))
        time.sleep(.3)
        self.screenshot('desktop.png')

    def capture(self):
        sys.path.insert(0, str(self.config / 'capture'))
        import capture_backend as backend
        from PIL import Image
        target = Path(self.env['OSB_FILES_HOME']) / 'Afbeeldingen/Schermafbeeldingen'
        runner = '''import json,sys
sys.path.insert(0,sys.argv[1])
import capture
from gi.repository import Gtk,GLib
capture.notify=lambda *args: None
app=capture.App()
app.source=sys.argv[2]
app.ov.sel=json.loads(sys.argv[3])
def take():
    try: app.capture()
    finally: Gtk.main_quit()
    return False
GLib.timeout_add(300,take)
Gtk.main()
'''
        for mode, rect in [('full', None), ('region', (41, 43, 211, 139))]:
            before = set(target.glob('*.png')) if target.exists() else set()
            process = self.spawn('capture-' + mode, [sys.executable, '-c', runner,
                                 str(self.config / 'capture'), mode, json.dumps(rect)])
            assert process.wait(timeout=20) == 0
            files = set(target.glob('*.png')) - before
            assert len(files) == 1, files
            saved = files.pop()
            with Image.open(saved) as shot:
                with Image.open(self.out / 'desktop.png') as desktop:
                    expected = desktop.size if rect is None else rect[2:]
                assert shot.size == expected, (shot.size, expected)
            copied = self.run(['wl-paste', '-n', '-t', 'image/png']).stdout
            assert copied == saved.read_bytes()
            shutil.copy2(saved, self.out / (mode + '-screenshot.png'))
            self.passed(mode + ' screenshot dimensions and exact PNG clipboard')
        before = set(target.glob('*.png'))
        process = self.spawn('capture-cancel', [sys.executable, str(self.config / 'capture/capture.py')])
        time.sleep(.8)
        self.run(['wtype', '-k', 'Escape'])
        assert process.wait(timeout=10) == 0
        assert set(target.glob('*.png')) == before
        self.passed('Escape cancels capture without saving')

        video = self.out / 'recorded-region.mp4'
        command = backend.recording_command(video, (20, 20, 640, 480), True)
        runner = ('import sys,json; sys.path.insert(0,sys.argv[1]); import capture_backend as b; '
                  'raise SystemExit(0 if b.run_recording(json.loads(sys.argv[2]),max_seconds=10) else 1)')
        recorder = self.spawn('recorder', [sys.executable, '-c', runner, str(self.config / 'capture'), json.dumps(command)])
        self.wait('live recording state', backend.recording_state)
        time.sleep(1)
        assert backend.stop_recording()
        assert recorder.wait(timeout=20) == 0
        assert backend.recording_state() is None and not backend.state_path().exists()
        assert backend.valid_video(video)
        self.run(['ffmpeg', '-v', 'error', '-i', str(video), '-frames:v', '1', str(self.out / 'recorded-frame.png')])
        with Image.open(self.out / 'recorded-frame.png') as frame:
            assert frame.size == (640, 480)
        self.passed('recording starts, scoped stop finalizes decodable video and removes state')

    def portal_setup(self):
        preferences = Path(self.env['XDG_CONFIG_HOME']) / 'xdg-desktop-portal'
        preferences.mkdir()
        (preferences / 'polderos-portals.conf').write_text(
            '[preferred]\ndefault=gtk\norg.freedesktop.impl.portal.ScreenCast=wlr\norg.freedesktop.impl.portal.Screenshot=wlr\n')
        chooser = self.config / 'capture/portal-chooser.py'
        backend_config = self.root / 'wlr.conf'
        import shlex
        backend_config.write_text('[screencast]\nmax_fps=20\nchooser_type=dmenu\nchooser_cmd=' +
                                  shlex.join([sys.executable, str(chooser)]) + '\n')
        if self.activation:
            backend_directory = Path(self.env['XDG_CONFIG_HOME']) / 'xdg-desktop-portal-wlr'
            backend_directory.mkdir()
            shutil.copy2(backend_config, backend_directory / 'PolderOS')
        self.spawn('pipewire', ['pipewire'])
        self.wait('PipeWire socket', lambda: (self.runtime / 'pipewire-0').exists())
        self.spawn('wireplumber', ['wireplumber'])
        self.run(['dbus-update-activation-environment', 'WAYLAND_DISPLAY', 'XDG_CURRENT_DESKTOP',
                  'XDG_SESSION_TYPE', 'XDG_RUNTIME_DIR', 'HOME', 'XDG_CONFIG_HOME'])
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if self.activation:
            self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'StartServiceByName', GLib.Variant('(su)', ('org.freedesktop.impl.portal.desktop.wlr', 0)),
                None, Gio.DBusCallFlags.NONE, 10000, None)
            result = self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                GLib.Variant('(s)', ('org.freedesktop.impl.portal.desktop.wlr',)),
                None, Gio.DBusCallFlags.NONE, 10000, None)
            self.activated_backend_pid = result.unpack()[0]
            actual = (Path('/proc') / str(self.activated_backend_pid) / 'exe').resolve()
            assert actual == self.portal_wlr.resolve(), (actual, self.portal_wlr)
            self.passed('D-Bus activation selects installed Polder portal backend')
        else:
            portal_wlr = self.spawn('portal-wlr', [str(self.portal_wlr), '-l', 'DEBUG', '-c', str(backend_config)])
        portal = self.spawn('portal', ['/usr/libexec/xdg-desktop-portal', '--verbose', '--replace'])
        def owned(name, process):
            assert process.poll() is None, name + ' exited before bus ownership'
            try:
                result = self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                    GLib.Variant('(s)', (name,)), None,
                    Gio.DBusCallFlags.NONE, 500, None)
                return result.unpack()[0] == process.pid
            except GLib.Error:
                return False
        if not self.activation:
            self.wait('selected portal backend owner',
                      lambda: owned('org.freedesktop.impl.portal.desktop.wlr', portal_wlr), 30)
        self.wait('single portal owner', lambda: owned('org.freedesktop.portal.Desktop', portal), 30)
        self.responses = {}
        self.bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                                  'Response', None, None, Gio.DBusSignalFlags.NONE,
                                  lambda _bus, _sender, path, _interface, _signal, args:
                                  self.responses.__setitem__(path, args.unpack()))
        def ready():
            try:
                value = self.bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
                    'org.freedesktop.DBus.Properties', 'Get',
                    GLib.Variant('(ss)', ('org.freedesktop.portal.ScreenCast', 'AvailableSourceTypes')),
                    None, Gio.DBusCallFlags.NONE, 500, None)
                return value.unpack()[0] & 1
            except GLib.Error:
                return False
        self.wait('ScreenCast interface', ready, 30)

    def request(self, method, signature, args, choice=None):
        value = self.bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
                                  'org.freedesktop.portal.ScreenCast', method, GLib.Variant(signature, args),
                                  None, Gio.DBusCallFlags.NONE, 10000, None)
        handle = value.unpack()[0]
        if choice is not None:
            self.wait('explicit screen-sharing chooser', lambda: any(window['title'] == 'Scherm delen' for window in self.windows()))
            self.screenshot('portal-' + choice + '-dialog.png')
            if choice == 'cancel':
                self.run(['wtype', '-k', 'Escape'])
            else:
                self.run(['wtype', '-M', 'alt', '-k', 'd', '-m', 'alt'])
        return self.wait('portal ' + method + ' response', lambda: self.responses.get(handle), 30)

    def portal(self):
        self.portal_setup()
        active_session = None
        for choice in ('cancel', 'share'):
            options = dict(handle_token=GLib.Variant('s', 'create_' + choice),
                           session_handle_token=GLib.Variant('s', 'session_' + choice))
            status, result = self.request('CreateSession', '(a{sv})', (options,))
            assert status == 0, (status, result)
            session = result['session_handle']
            status, result = self.request('SelectSources', '(oa{sv})',
                (session, dict(types=GLib.Variant('u', 1), multiple=GLib.Variant('b', False),
                               cursor_mode=GLib.Variant('u', 1), handle_token=GLib.Variant('s', 'select_' + choice))), choice)
            if choice == 'cancel':
                assert status == 1 and not result.get('streams'), (status, result)
                self.passed('portal cancellation returns cancellation and no stream')
            else:
                assert status == 0, (status, result)
                status, result = self.request('Start', '(osa{sv})',
                    (session, '', dict(handle_token=GLib.Variant('s', 'start_' + choice))))
                assert status == 0 and len(result['streams']) == 1, (status, result)
                active_session = session
                node, properties = result['streams'][0]
                (self.out / 'portal-stream.json').write_text(json.dumps(dict(node=node, properties=properties), indent=2))
                self.passed('portal CreateSession/SelectSources/Start after visible explicit consent')
        result, descriptors = self.bus.call_with_unix_fd_list_sync(
            'org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop', 'org.freedesktop.portal.ScreenCast',
            'OpenPipeWireRemote', GLib.Variant('(oa{sv})', (active_session, {})), None,
            Gio.DBusCallFlags.NONE, 10000, None, None)
        descriptor = descriptors.get(result.unpack()[0])
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        Gst.init(None)
        pipeline = Gst.parse_launch('pipewiresrc name=source num-buffers=5 ! video/x-raw ! fakesink name=sink signal-handoffs=true sync=false')
        source = pipeline.get_by_name('source')
        source.set_property('fd', descriptor)
        source.set_property('path', str(node))
        frames = []
        motion_count = [0]
        def change_content():
            self.run(['wtype', '-M', 'logo', '-k', 'Up', '-m', 'logo'])
            motion_count[0] += 1
            return True
        def frame(_sink, buffer, pad):
            success, mapped = buffer.map(Gst.MapFlags.READ)
            assert success
            try:
                frames.append(dict(bytes=len(mapped.data), varied=len(set(mapped.data)) > 8,
                                   sha256=hashlib.sha256(mapped.data).hexdigest(),
                                   caps=pad.get_current_caps().to_string()))
                if len(frames) == 1:
                    from PIL import Image
                    structure = pad.get_current_caps().get_structure(0)
                    if structure.get_value('format') == 'BGRx':
                        Image.frombytes('RGB', (structure.get_value('width'), structure.get_value('height')),
                                        bytes(mapped.data), 'raw', 'BGRX').save(self.out / 'portal-frame.png')
            finally:
                buffer.unmap(mapped)
        pipeline.get_by_name('sink').connect('handoff', frame)
        try:
            motion = GLib.timeout_add(250, change_content)
            pipeline.set_state(Gst.State.PLAYING)
            # Keep dispatching the client context while GStreamer delivers buffers.
            message = self.wait('five portal video frames', lambda: pipeline.get_bus().pop_filtered(
                Gst.MessageType.ERROR | Gst.MessageType.EOS), 20)
            if message.type == Gst.MessageType.ERROR:
                raise RuntimeError(str(message.parse_error()))
            assert len(frames) == 5 and all(frame['bytes'] > 0 and frame['varied'] for frame in frames), frames
            assert len({frame['sha256'] for frame in frames}) > 1, 'Portal must carry changing screen content'
            (self.out / 'portal-frames.json').write_text(json.dumps(frames, indent=2))
            self.passed('OpenPipeWireRemote FD delivers five video frames with changing screen content')
        finally:
            GLib.source_remove(motion)
            (self.out / 'portal-frames.json').write_text(json.dumps(frames, indent=2))
            pipeline.set_state(Gst.State.NULL)
            os.close(descriptor)
            self.bus.call_sync('org.freedesktop.portal.Desktop', active_session, 'org.freedesktop.portal.Session',
                               'Close', None, None, Gio.DBusCallFlags.NONE, 5000, None)

    def close(self):
        if self.activated_backend_pid is not None:
            try:
                os.kill(self.activated_backend_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in reversed(self.children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        for stream in self.logs:
            stream.close()
        recording_log = Path(self.env['OSB_RUNDIR']) / 'osb-rec.log'
        if recording_log.exists():
            shutil.copy2(recording_log, self.out / 'recording-backend.log')
        self.temp.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, default=Path('/usr/share/polderos/config'))
    parser.add_argument('--compositor', type=Path, default=Path('/usr/bin/polder-comp'))
    parser.add_argument('--portal-wlr', type=Path, default=Path('/usr/libexec/xdg-desktop-portal-wlr'))
    parser.add_argument('--activation', action='store_true', help='Verify installed D-Bus backend activation')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    test = Smoke(args.config_dir, args.compositor, args.output_dir, args.portal_wlr, args.activation)
    faulthandler.dump_traceback_later(120, exit=True)
    status, error = 'passed', None
    try:
        test.start()
        test.capture()
        test.portal()
    except Exception:
        status, error = 'failed', traceback.format_exc()
        print(error, file=sys.stderr)
    finally:
        faulthandler.cancel_dump_traceback_later()
        test.close()
        (test.out / 'report.json').write_text(json.dumps(dict(status=status, checks=test.checks, error=error), indent=2))
    return 0 if status == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
