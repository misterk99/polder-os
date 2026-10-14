#!/usr/bin/env python3
"""Native ARM-friendly integration checks for output transactions and keyboard maps."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'config/osb'))
import wayland_display as D

spec = importlib.util.spec_from_file_location('smoke', ROOT / 'compositor/polder-comp/tests/headless-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compositor', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='desktop-', dir=args.output_dir.resolve()))
    session = smoke.Session(args.compositor, output, 10)
    session.env['WLR_HEADLESS_OUTPUTS'] = '1'  # One backend output plus the compositor's own test output.
    status = 'failed'
    try:
        session.start()
        with patch.dict(os.environ, session.env, clear=True):
            monitors = D.outputs()
            assert len(monitors) == 2, monitors
            session.passed('output management exposes both displays')
            original = [D.profile(o) for o in monitors]
            name = original[0]['name']
            def scale(): return next(o['scale'] for o in D.outputs() if o['name'] == name)
            keyboard_file = session.runtime / 'polder-keyboard.json'
            session.command('keyboard de -')
            session.wait_for('German compiled map', lambda: json.loads(keyboard_file.read_text()).get('ad06') == 'z')
            session.passed('keyboard changes live to a compiled German QWERTZ map')
            session.command('keyboard missing_layout -')
            session.wait_for('invalid keyboard rejection', lambda: json.loads(keyboard_file.read_text()).get('error'))
            assert json.loads(keyboard_file.read_text())['layout'] == 'de'
            session.passed('invalid keyboard map preserves the previous layout')
            session.command('keyboard us intl')
            session.wait_for('international variant', lambda: json.loads(keyboard_file.read_text()).get('variant') == 'intl')
            session.passed('keyboard variant changes without restarting the compositor')

            proposed = json.loads(json.dumps(original)); proposed[0]['scale'] = 1.25
            proposed[0]['position'] = {'x': -1200, 'y': 0}
            D.apply(proposed)
            assert scale() == 1.25
            session.passed('live fractional scaling and negative monitor placement apply')
            session.run(['grim', '-s', '1', '-o', name, str(output / 'scaled-output.png')])
            from PIL import Image
            mode = proposed[0]['mode']
            with Image.open(output / 'scaled-output.png') as picture:
                assert abs(picture.width - mode['width'] / 1.25) <= 1
                assert abs(picture.height - mode['height'] / 1.25) <= 1
            session.passed('captured pixels reflect the scaled logical output size')
            D.apply(original)

            args_off = sum((['--output', o['name'], '--off'] for o in monitors), [])
            result = subprocess.run(['wlr-randr'] + args_off, capture_output=True, env=session.env)
            assert result.returncode != 0 and all(o['enabled'] for o in D.outputs())
            session.passed('compositor rejects disabling every display without altering the layout')
            result = subprocess.run(['wlr-randr', '--output', name, '--scale', '0.25'], capture_output=True, env=session.env)
            assert result.returncode != 0 and scale() == 1
            session.passed('unsupported scale is rejected without changing the current display')

            proposed[0]['position'] = original[0]['position']
            code = 'import json,sys;sys.path.insert(0,sys.argv[1]);import wayland_display as D;print(D.begin_preview(json.loads(sys.argv[2]),seconds=0.8))'
            client = subprocess.run([sys.executable, '-c', code, str(ROOT / 'config/osb'), json.dumps(proposed)],
                                    env=session.env, capture_output=True, text=True, timeout=10, check=True)
            assert client.stdout.strip() and scale() == 1.25
            session.wait_for('watchdog restoration', lambda: D.read_state()['status'] == 'reverted')
            assert scale() == 1
            session.passed('unconfirmed display change rolls back after its Settings client has exited')

            session.wait_for('preview lock release', lambda: lock_available())
            token = D.begin_preview(proposed, seconds=10)
            try:
                D.begin_preview(proposed)
                raise AssertionError('concurrent preview accepted')
            except RuntimeError as exc:
                assert 'vorige' in str(exc)
            D.decide(token, True)
            session.wait_for('confirmed preview guard exit', lambda: lock_available())
            assert scale() == 1.25
            import osbsettings as S
            saved = S.load()
            assert saved['displays'][name]['scale'] == 1.25
            session.passed('confirmed display settings persist and simultaneous previews are rejected')
            D.apply(original); D.restore_saved(saved)
            assert scale() == 1.25
            session.passed('saved profiles restore against the matching connected monitors')
            D.apply(original)

            # Real hardware exposes its seat keyboard before an application maps.
            # Keep a virtual device connected so its capability announcement cannot
            # race the first synthetic keystrokes on this headless-only seat.
            session.spawn('seat-keyboard', ['wtype', '-s', '60000'])
            time.sleep(0.2)
            _, receiver = session.client('keyboard')
            session.command('keyboard de -')
            session.wait_for('map switch with active client', lambda: json.loads(keyboard_file.read_text())['layout'] == 'de')
            session.type_marker('virtual-keymap', receiver, session.root / 'unused')
            session.passed('virtual keyboards retain their supplied keymaps after a physical-layout change')

            session.run(['wtype', '-M', 'logo', '-k', 'Up', '-m', 'logo'])
            maximized = session.expect_state('client maximizes on its own monitor',
                lambda s: next((w for w in s['windows'] if w['app_id'] == 'polder-smoke-keyboard' and w['w'] > 1000), None))
            window = session.window(maximized, 'polder-smoke-keyboard')
            owner = next(i for i, p in enumerate(original) if p['position']['x'] == window['x'] and p['position']['y'] == window['y'])
            moved = json.loads(json.dumps(original))
            moved[owner]['position'] = {'x': -1600, 'y': -100}
            moved[owner]['scale'] = 1.25
            D.apply(moved)
            session.expect_state('maximized client follows its monitor across a position and scale change',
                lambda s: (w := session.window(s, 'polder-smoke-keyboard')) and w['x'] == -1600 and w['y'] == -100
                and abs(w['w'] - moved[owner]['mode']['width'] / 1.25) <= 1)
            D.apply(original)
        status = 'passed'
    finally:
        session.close()
        (output / 'report.json').write_text(json.dumps(dict(status=status, checks=session.checks), indent=2) + '\n')
    print(f'{status.upper()}: {len(session.checks)} checks; {output}')


def lock_available():
    import fcntl
    with (D.runtime() / 'preview.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
    return True


if __name__ == '__main__':
    main()
