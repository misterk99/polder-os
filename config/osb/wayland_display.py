"""Native output configuration with a separate, crash-resistant preview watchdog."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def runtime():
    directory = Path(os.environ['XDG_RUNTIME_DIR']) / 'polder-displays'
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def outputs():
    result = subprocess.run(['wlr-randr', '--json'], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Beeldschermen konden niet worden gelezen.')
    return json.loads(result.stdout)


def identity(output):
    return [output.get(key) for key in ('make', 'model', 'serial')]


def profile(output):
    mode = next((m for m in output.get('modes', []) if m.get('current')), None)
    return dict(name=output['name'], identity=identity(output), enabled=output['enabled'],
                mode=mode, scale=output.get('scale', 1), transform=output.get('transform', 'normal'),
                position=output.get('position', {'x': 0, 'y': 0}))


def arguments(profiles):
    args = []
    for p in profiles:
        args += ['--output', p['name'], '--on' if p['enabled'] else '--off']
        if not p['enabled']:
            continue
        mode = p.get('mode')
        if mode:
            value = f"{int(mode['width'])}x{int(mode['height'])}"
            if mode.get('refresh', 0) > 0:
                value += f"@{float(mode['refresh']):.6f}Hz"
            args += ['--mode', value]
        args += ['--scale', str(float(p['scale'])), '--transform', p['transform'],
                 '--pos', f"{int(p['position']['x'])},{int(p['position']['y'])}"]
    return args


def apply(profiles):
    if not any(p['enabled'] for p in profiles):
        raise RuntimeError('Laat minstens één beeldscherm ingeschakeld.')
    args = arguments(profiles)
    for dryrun in (True, False):
        result = subprocess.run(['wlr-randr'] + (['--dryrun'] if dryrun else []) + args,
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Deze beeldscherminstellingen worden niet ondersteund.')


@contextlib.contextmanager
def state_lock():
    with (runtime() / 'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write_state(state):
    temporary = runtime() / 'preview.tmp'
    temporary.write_text(json.dumps(state))
    temporary.replace(runtime() / 'preview.json')


def read_state():
    return json.loads((runtime() / 'preview.json').read_text())


def begin_preview(proposed, seconds=15):
    lock = (runtime() / 'preview.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        token = uuid.uuid4().hex
        previous = [profile(o) for o in outputs()]
        state = dict(token=token, status='starting', previous=previous, deadline=time.monotonic() + 10)
        with state_lock():
            write_state(state)
        with (runtime() / 'watchdog.log').open('a') as log:
            subprocess.Popen([sys.executable, __file__, '--guard', token], pass_fds=(lock.fileno(),),
                             start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    except BlockingIOError:
        raise RuntimeError('Bevestig eerst de vorige beeldschermwijziging.')
    finally:
        lock.close()  # The watchdog owns the preview lock, even if Settings crashes.
    try:
        with state_lock():
            apply(proposed)
            state.update(status='preview', deadline=time.monotonic() + seconds)
            write_state(state)
    except Exception:
        with state_lock():
            state.update(status='revert')
            write_state(state)
        raise
    return token


def decide(token, keep):
    with state_lock():
        state = read_state()
        if state['token'] != token or state['status'] != 'preview':
            raise RuntimeError('De vorige beeldscherminstellingen zijn al hersteld.')
        if keep and time.monotonic() >= state['deadline']:
            raise RuntimeError('De bevestigingstijd is verstreken.')
        if keep:
            import osbsettings as S
            saved = S.load().get('displays', {})
            saved.update({o['name']: profile(o) for o in outputs()})
            S.update(displays=saved)
        state['status'] = 'keep' if keep else 'revert'
        write_state(state)


def guard(token):
    while True:
        retry = False
        with state_lock():
            state = read_state()
            if state['token'] != token or state['status'] == 'keep':
                return
            if state['status'] == 'revert' or time.monotonic() >= state['deadline']:
                try:
                    connected = {o['name']: o for o in outputs()}
                except Exception as exc:
                    state.update(status='error', error=str(exc))
                    write_state(state)
                    print('Display connection lost during restoration:', exc, flush=True)
                    return
                try:
                    old = [p for p in state['previous'] if p['name'] in connected
                           and p['identity'] == identity(connected[p['name']])]
                    for p in old:
                        modes = connected[p['name']].get('modes', [])
                        wanted = p.get('mode')
                        if wanted and modes and not any(all(m.get(k) == wanted.get(k) for k in ('width', 'height', 'refresh')) for m in modes):
                            p['mode'] = next((m for m in modes if m.get('current')), modes[0])
                    # Preserve newly attached monitors, and never switch every remaining one off.
                    old += [profile(o) for name, o in connected.items() if name not in {p['name'] for p in old}]
                    if old and not any(p['enabled'] for p in old):
                        # The previously active monitor was unplugged during the preview.
                        old[0]['enabled'] = True
                    if old:
                        apply(old)
                    state['status'] = 'reverted'
                    state.pop('error', None)
                except Exception as exc:
                    # Output changes are refused while locked. Keep ownership and
                    # retry after unlock rather than leaving an unconfirmed mode.
                    if state.get('error') != str(exc):
                        print('Display restoration deferred:', exc, flush=True)
                    state.update(status='restoring', error=str(exc))
                    retry = True
                write_state(state)
                if not retry: return
        time.sleep(1 if retry else 0.1)


def restore_saved(settings):
    saved = settings.get('displays', {})
    if not saved:
        return
    lock = (runtime() / 'preview.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = outputs()
        profiles = [saved.get(o['name']) if o['name'] in saved and saved[o['name']].get('identity') == identity(o)
                    else profile(o) for o in current]
        apply(profiles)
    except BlockingIOError:
        pass  # A user's unconfirmed preview takes precedence over saved settings.
    finally:
        lock.close()


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--guard':
    guard(sys.argv[2])
