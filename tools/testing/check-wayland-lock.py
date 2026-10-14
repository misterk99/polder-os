#!/usr/bin/env python3
"""Exercise actual GTK/swaylock clients against an isolated headless compositor.

Requires the live-session GTK/PAM dependencies. No password is configured and no
real suspend is requested; successful PAM authentication remains a manual check.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('headless', ROOT / 'compositor/polder-comp/tests/headless-smoke.py')
headless = importlib.util.module_from_spec(spec)
spec.loader.exec_module(headless)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compositor', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--two-outputs', action='store_true')
    parser.add_argument('--wlr-randr', default='wlr-randr')
    parser.add_argument('--unlock-password-env', help='Environment variable containing a disposable test account password')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = headless.Session(args.compositor, args.output_dir, 15)
    if args.two_outputs:
        session.env['WLR_HEADLESS_OUTPUTS'] = '1'
        if '/' in args.wlr_randr:
            session.env['PATH'] = str(Path(args.wlr_randr).resolve().parent) + ':' + session.env['PATH']
    config = session.root / 'polder-config'
    shutil.copytree(ROOT / 'config', config, ignore=shutil.ignore_patterns('__pycache__'))
    for path in (config / 'lock').iterdir():
        if path.suffix in ('.sh', '.py'):
            path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
            path.chmod(0o755)
    keys = session.root / 'keys'; keys.write_text('')
    private = session.runtime / 'polderos-wayland'; private.mkdir(mode=0o700)
    session.env.update(POLDER_COMP='1', XDG_SESSION_TYPE='wayland', GDK_BACKEND='wayland',
                       GTK_IM_MODULE='gtk-im-context-simple', POLDER_CONFIG=str(config),
                       OSB_RUNDIR=str(private))
    if os.environ.get('POLDER_TEST_WAYLAND_DEBUG'):
        session.env['WAYLAND_DEBUG'] = 'client'
    controller = None
    outputs = []
    preview = None
    try:
        session.start()
        if args.two_outputs:
            def read_outputs():
                return json.loads(session.run([args.wlr_randr, '--json']).stdout)
            outputs = read_outputs()
            if len(outputs) != 2 or not all(output['enabled'] for output in outputs):
                raise RuntimeError('Expected two enabled headless displays')
            session.run([args.wlr_randr, '--output', outputs[0]['name'], '--pos', '-1280,0',
                         '--output', outputs[1]['name'], '--pos', '0,0'])
            if next(output for output in read_outputs() if output['name'] == outputs[0]['name'])['position']['x'] != -1280:
                raise RuntimeError('Negative monitor placement was not applied')
            session.passed('two enabled outputs include a monitor at a negative origin')
        # A physical session advertises a keyboard before clients map. Keep one
        # virtual device alive to reproduce that seat in the headless fixture.
        session.spawn('persistent-keyboard', ['wtype', '-s', '120000'])
        time.sleep(.2)
        window, receiver = session.client('protected')
        session.command(f'focus {window}')
        session.type_marker('before-lock', receiver, session.root / 'unused-client')
        baseline = receiver.read_text()
        if args.two_outputs and args.unlock_password_env:
            code = '''import json,os,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import wayland_display as D
profiles = [D.profile(output) for output in D.outputs()]
profiles[0]['scale'] = 1.25
token = D.begin_preview(profiles, seconds=2)
children = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split()
print(json.dumps({'token': token, 'pid': int(children[0])}))
'''
            preview = json.loads(session.run([sys.executable, '-c', code, str(config / 'osb')]).stdout)
        controller = session.spawn('lock-controller', [sys.executable, str(config / 'lock/lock-session.py'), '--serve'])
        session.wait_for('lock controller socket', lambda: (private / 'lock/controller.sock').exists())
        started = time.monotonic()
        session.run(['sh', str(config / 'lock/lock-now.sh'), '-f'])
        acknowledgement_seconds = time.monotonic() - started
        session.passed('lock request returns only after real compositor acknowledgement')
        session.run(['grim', str(args.output_dir / 'acknowledged.png')])

        def child_pid():
            children = Path(f'/proc/{controller.pid}/task/{controller.pid}/children')
            return next((int(value) for value in children.read_text().split()), None)

        gtk_pid = session.wait_for('GTK locker child', child_pid)
        if b'lock-wayland.py' not in Path(f'/proc/{gtk_pid}/cmdline').read_bytes():
            raise RuntimeError('The primary GTK locker did not remain running')
        def gui_visible():
            if child_pid() != gtk_pid:
                raise RuntimeError('GTK locker died before its UI became visible')
            session.run(['grim', str(args.output_dir / 'gtk-lock.png')])
            with Image.open(args.output_dir / 'gtk-lock.png') as image:
                return len(image.convert('RGB').resize((64, 48)).getcolors(3072) or []) > 32
        session.wait_for('GTK lock UI visible', gui_visible)
        session.passed('GTK lock screen renders after acknowledgement')
        session.run(['wtype', '-M', 'logo', '-M', 'shift', '-k', 'Escape',
                     '-m', 'shift', '-m', 'logo', '-s', '100'])
        session.alive()
        os.kill(gtk_pid, 0)
        session.passed('locked Super+Shift+Escape cannot terminate the compositor')
        # Give GTK time to bind the keyboard advertised by this virtual input device.
        session.run(['wtype', '-s', '250', '-d', '5', 'polder-invalid-lock-test-password', '-k', 'Return', '-s', '250'])
        session.run(['grim', str(args.output_dir / 'password-attempt.png')])
        session.wait_for('PAM rejection', lambda: 'authentication rejected' in
                         (args.output_dir / 'lock-controller.log').read_text())
        if receiver.read_text() != baseline:
            raise RuntimeError('Protected client received input while locked')
        os.kill(gtk_pid, 0)
        session.passed('invalid password keeps locker alive and blocks protected-client input')
        if args.unlock_password_env:
            if preview:
                preview_file = session.runtime / 'polder-displays/preview.json'
                session.wait_for('expired display preview waits while locked',
                                 lambda: json.loads(preview_file.read_text())['status'] == 'restoring')
                if next(output for output in read_outputs() if output['name'] == outputs[0]['name'])['scale'] != 1.25:
                    raise RuntimeError('Display preview changed while compositor was locked')
                session.passed('expired display preview retains its rollback guard while locked')
            password = os.environ[args.unlock_password_env]
            # Do not put passwords into commands.log; the child has no input echo.
            typed = session.spawn('unlock-input', ['wtype', '-s', '250', '-M', 'ctrl', '-k', 'a',
                                  '-m', 'ctrl', '-d', '5', password, '-k', 'Return'])
            if typed.wait(timeout=10) != 0:
                raise RuntimeError('Failed to type the disposable account password')
            session.wait_for('authenticated locker exit', lambda: controller.poll() is not None)
            if controller.returncode != 0:
                raise RuntimeError('Locker did not report successful authenticated unlock')
            session.command(f'focus {window}')
            session.type_marker('after-authenticated-unlock', receiver, session.root / 'unused-client')
            baseline = receiver.read_text()
            session.passed('successful PAM authentication unlocks and restores protected-client input')
            if preview:
                session.wait_for('deferred display rollback after unlock',
                                 lambda: json.loads(preview_file.read_text())['status'] == 'reverted')
                if next(output for output in read_outputs() if output['name'] == outputs[0]['name'])['scale'] != 1:
                    raise RuntimeError('Display preview did not restore its original scale after unlock')
                session.passed('expired display preview automatically restores the original scale after authenticated unlock')
            controller = session.spawn('lock-controller-relocked', [sys.executable, str(config / 'lock/lock-session.py'), '--serve'])
            session.wait_for('new lock controller socket', lambda: (private / 'lock/controller.sock').exists())
            session.run(['sh', str(config / 'lock/lock-now.sh'), '-f'])
            gtk_pid = session.wait_for('new GTK locker child', child_pid)
            session.wait_for('new GTK lock UI visible', gui_visible)
            session.passed('session can lock again after a successful authenticated unlock')
        os.kill(gtk_pid, signal.SIGKILL)
        fallback = session.wait_for('fallback swaylock child',
            lambda: (pid if (pid := child_pid()) and pid != gtk_pid and
                     b'swaylock' in Path(f'/proc/{pid}/cmdline').read_bytes() else None))
        session.run(['sh', str(config / 'lock/lock-now.sh'), '-f'])
        session.run(['grim', str(args.output_dir / 'fallback-lock.png')])
        session.passed('swaylock takes over after GTK locker is killed')
        controller.terminate(); controller.wait(timeout=4)
        session.run(['wtype', 'must-not-reach-client', '-k', 'Return'])
        session.run(['grim', str(args.output_dir / 'locker-death-cover.png')])
        def assert_opaque(path):
            with Image.open(path) as image:
                colors = image.convert('RGB').getcolors(image.width * image.height)
                if not colors or max(count for count, _ in colors) < image.width * image.height * .99:
                    raise RuntimeError(f'Compositor did not retain its opaque cover: {path.name}')
        if not args.two_outputs:
            assert_opaque(args.output_dir / 'locker-death-cover.png')
        else:
            # A combined capture contains gaps between unequal-height outputs.
            # Inspect real output pixels rather than counting those empty gaps.
            for index, output in enumerate(outputs):
                path = args.output_dir / f'locker-death-before-move-{index}.png'
                session.run(['grim', '-o', output['name'], str(path)])
                assert_opaque(path)
        if receiver.read_text() != baseline:
            raise RuntimeError('Protected client received input after locker death')
        session.passed('all locker processes dying leaves opaque cover and blocked client input')
        if args.two_outputs:
            # The compositor rejects client-requested output changes while locked.
            attempt = subprocess.run([args.wlr_randr, '--output', outputs[0]['name'], '--pos', '-1600,-200'],
                                     env=session.env, capture_output=True, timeout=10)
            (args.output_dir / 'locked-output-change.log').write_bytes(attempt.stdout + attempt.stderr)
            if attempt.returncode == 0:
                raise RuntimeError('Locked display reconfiguration was unexpectedly accepted')
            monitors = read_outputs()
            position = next(output for output in monitors if output['name'] == outputs[0]['name'])['position']
            if position != {'x': -1280, 'y': 0}:
                raise RuntimeError('Rejected locked display change altered the negative-origin layout')
            for index, output in enumerate(outputs):
                path = args.output_dir / f'locker-death-output-{index}.png'
                session.run(['grim', '-o', output['name'], str(path)])
                assert_opaque(path)
            session.passed('locked display changes are rejected and both negative-origin output covers remain opaque')
        (args.output_dir / 'report.json').write_text(json.dumps(dict(
            checks=session.checks, acknowledgement_seconds=round(acknowledgement_seconds, 3),
            limitations=['Real hardware suspend/resume was not exercised.'] +
                         ([] if args.unlock_password_env else ['Successful PAM authentication was not exercised.'])), indent=2) + '\n')
        return 0
    finally:
        if preview:
            try:
                command = Path(f'/proc/{preview["pid"]}/cmdline').read_bytes()
                if b'--guard' in command and preview['token'].encode() in command:
                    os.killpg(preview['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
        session.close()


if __name__ == '__main__':
    sys.exit(main())
