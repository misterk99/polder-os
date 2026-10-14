#!/usr/bin/env python3
"""Exercise actual GTK Settings widgets against an isolated native compositor.

Run in the ARM live runtime with wlr-randr and python3-pil installed. Screenshots,
daemon logs and the widget assertions are retained in --output-dir.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def client(config, output):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    sys.argv = [str(config / 'settings/instellingen.py'), 'beeldscherm']
    # Construct the unmodified application, then schedule widget actions before
    # entering the real GTK loop. No display backend or settings calls are mocked.
    with patch.object(Gtk, 'main', lambda: None):
        runpy.run_path(sys.argv[0], run_name='__main__')
    app = next(w for w in Gtk.Window.list_toplevels() if w.get_title() == 'Instellingen')
    import wayland_display as D
    import wayland_control as control
    import osbsettings as S
    checks = []; phase = 0; deadline = time.monotonic() + 40; other = None

    def state():
        path = Path(os.environ['XDG_RUNTIME_DIR']) / 'polder-state.json'
        path.unlink(missing_ok=True); control.command('dump')
        until = time.monotonic() + 2
        while not path.exists():
            assert time.monotonic() < until, 'compositor did not publish state'
            time.sleep(.01)
        return json.loads(path.read_text())

    def descendants(widget):
        yield widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children(): yield from descendants(child)

    def button(label):
        return next(w for w in descendants(app) if isinstance(w, Gtk.Button) and w.get_label() == label)

    def capture(name):
        subprocess.run(['grim', str(output / (name + '.png'))], check=True, timeout=10)

    def tick():
        nonlocal phase, other
        try:
            assert time.monotonic() < deadline, f'UI phase {phase} timed out'
            if phase == 0:
                combos = [w for w in descendants(app) if isinstance(w, Gtk.ComboBoxText)]
                assert len(combos) == 3
                capture('settings-displays')
                combos[1].set_active_id('1.25')
                button('Toepassen').clicked(); phase = 1
            elif phase == 1:
                dialogs = [w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog)]
                if not dialogs: return True
                assert D.outputs()[0]['scale'] == 1.25
                capture('settings-confirm-display')
                dialogs[0].response(Gtk.ResponseType.ACCEPT)
                checks.append('GTK display controls apply fractional scale and confirm the preview')
                phase = 2
            elif phase == 2:
                if not S.load().get('displays'): return True
                assert next(iter(S.load()['displays'].values()))['scale'] == 1.25
                if other is None:
                    other = subprocess.Popen(['foot', '-c', '/dev/null', '-a', 'settings-focus-test', 'sleep', '30'],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                if state()['windows'][0]['app_id'] != 'settings-focus-test': return True
                subprocess.run([sys.executable, str(config / 'settings/instellingen.py'), 'toetsenbord'], check=True, timeout=10)
                phase = 3
            elif phase == 3:
                if app.cur != 'toetsenbord': return True
                assert len([w for w in Gtk.Window.list_toplevels() if w.get_title() == 'Instellingen']) == 1
                assert state()['windows'][0]['app_id'] == 'polder-settings', 'Settings was not raised over the other app'
                combos = [w for w in descendants(app) if isinstance(w, Gtk.ComboBoxText)]
                german = next(i for i, row in enumerate(combos[0].get_model()) if 'Duits' in row[0])
                combos[0].set_active(german)
                phase = 4
            elif phase == 4:
                status = json.loads((Path(os.environ['XDG_RUNTIME_DIR']) / 'polder-keyboard.json').read_text())
                if status['layout'] != 'de': return True
                assert status['ad06'] == 'z'
                capture('settings-keyboard')
                checks.append('reopening Settings raises its existing instance and switches page')
                checks.append('GTK keyboard selection reaches the daemon and changes the live compiled map')
                app.show('personalisatie')
                phase = 5
            elif phase == 5:
                toggles = [w for w in descendants(app) if isinstance(w, Gtk.Switch)]
                assert len(toggles) == 1
                toggles[0].set_active(True)
                phase = 6
            elif phase == 6:
                if not S.load()['reduced_motion']: return True
                capture('settings-personalisation')
                checks.append('reduced-motion preference is available and persists through the actual GTK control')
                (output / 'ui-report.json').write_text(json.dumps(dict(status='passed', checks=checks), indent=2))
                app.quit(); return False
        except Exception:
            (output / 'ui-report.json').write_text(json.dumps(dict(status='failed', checks=checks, phase=phase, error=traceback.format_exc()), indent=2))
            traceback.print_exc(); app.quit(); return False
        return True
    GLib.timeout_add(500, tick)
    Gtk.main()
    if other is not None:
        other.terminate(); other.wait(timeout=5)
    return 0 if json.loads((output / 'ui-report.json').read_text())['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compositor', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--client', type=Path)
    args = parser.parse_args()
    if args.client: return client(args.client, args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='settings-', dir=args.output_dir.resolve()))
    spec = importlib.util.spec_from_file_location('smoke', ROOT / 'compositor/polder-comp/tests/headless-smoke.py')
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    session = smoke.Session(args.compositor.resolve(), output, 20)
    try:
        config = session.root / 'config-source'
        shutil.copytree(ROOT / 'config', config, ignore=shutil.ignore_patterns('__pycache__'))
        for path in config.rglob('*'):
            if not path.is_file(): continue
            try: source = path.read_text()
            except UnicodeError: continue
            source = source.replace('/workspace/osbuilder/config', str(config))
            path.write_text(source)
        session.env.update(GTK_IM_MODULE='gtk-im-context-simple', GDK_BACKEND='wayland',
                           OSB_RUNDIR=str(session.runtime), OSB_SETTINGS=str(session.root / 'settings.json'))
        session.start()
        session.env['POLDER_COMP'] = str(session.compositor.pid)
        session.spawn('seat-keyboard', ['wtype', '-s', '60000'])
        session.spawn('settings-daemon', ['python3', str(config / 'osb/osb-settingsd.py')])
        process = session.spawn('settings-ui', ['dbus-run-session', '--', 'python3', __file__,
                                               '--client', str(config), '--output-dir', str(output)])
        process.wait(timeout=55)
        print((output / 'ui-report.json').read_text())
        assert process.returncode == 0, f'Settings GUI failed: {output}'
        state = session.state()
        (output / 'final-compositor-state.json').write_text(json.dumps(state, indent=2))
        print(f'Settings GUI passed: {output}')
    finally: session.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
