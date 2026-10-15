"""Capture process/state helpers, shared by the capture bar and shelf.

No GTK import: stopping a recording must also work during session shutdown.
"""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time


def runtime_dir():
    directory = Path(os.environ.get('OSB_RUNDIR', '/tmp'))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def state_path():
    return runtime_dir() / 'osb-rec.json'


def process_identity(pid):
    """Linux PID lifetime, not merely a PID which another process could reuse."""
    proc = Path('/proc') / str(int(pid))
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] == 'Z' or proc.stat().st_uid != os.getuid():
        raise ProcessLookupError(pid)
    return {'start_ticks': fields[19],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def recording_state():
    try:
        state = json.loads(state_path().read_text())
        identity = process_identity(state['pid'])
        if all(state.get(key) == value for key, value in identity.items()):
            return state
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        pass
    return None


def stop_recording(wait=False):
    state = recording_state()
    if state is None:
        return False
    descriptor = None
    try:
        # Pin the process before the final identity check, closing the PID-reuse race.
        descriptor = os.pidfd_open(state['pid'])
        if process_identity(state['pid']) != {key: state[key] for key in ('start_ticks', 'boot_id')}:
            return False
        signal.pidfd_send_signal(descriptor, signal.SIGINT)
        if wait:
            poll = select.poll()
            poll.register(descriptor, select.POLLIN)
            poll.poll(15000)
        return True
    except (OSError, ValueError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def acquire_lock(name):
    fd = os.open(runtime_dir() / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return None
    return fd


def publish_state(state):
    fd, temporary = tempfile.mkstemp(prefix='.recording-', dir=runtime_dir())
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
        os.replace(temporary, state_path())
    finally:
        Path(temporary).unlink(missing_ok=True)


def clip_rect(rect, width, height):
    x, y, w, h = (int(value) for value in rect)
    right, bottom = min(width, x + w), min(height, y + h)
    x, y = max(0, x), max(0, y)
    return (x, y, right - x, bottom - y) if right > x and bottom > y else None


def recording_command(path, rect, wayland, pointer=False, origin=(0, 0)):
    x, y, width, height = rect
    width -= width % 2
    height -= height % 2
    if width < 2 or height < 2:
        raise ValueError(_('Select a larger region to record.'))
    x += origin[0]
    y += origin[1]
    if wayland:
        # wlroots coordinates are logical; wf-recorder handles output scale itself.
        # Constant-rate recording also avoids waiting forever for damage on a still desktop.
        return ['wf-recorder', '-y', '-D', '-g', f'{x},{y} {width}x{height}', '-r', '20',
                '-c', 'libx264', '-p', 'preset=ultrafast', '-p', 'crf=28',
                '-p', 'threads=2', '-x', 'yuv420p', '-f', str(path)]
    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'x11grab',
            '-draw_mouse', '1' if pointer else '0', '-framerate', '20',
            '-video_size', f'{width}x{height}', '-i', f"{os.environ.get('DISPLAY', ':0')}+{x},{y}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-threads', '2', '-crf', '28', '-pix_fmt', 'yuv420p', '-t', '3600', str(path)]


def valid_video(path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=width,height,duration', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=15, check=True)
        stream = json.loads(result.stdout)['streams'][0]
        return stream['width'] > 0 and stream['height'] > 0 and float(stream.get('duration', 0)) > 0
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return False


def run_recording(command, max_seconds=3600):
    """Return success only after the recorder exits and a real video stream exists."""
    lock = acquire_lock('osb-recording.lock')
    if lock is None:
        return False
    process = None
    state = None
    log_path = runtime_dir() / 'osb-rec.log'
    previous = {}
    try:
        with log_path.open('w') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            def finish(signum, frame):
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, finish)
            try:
                process.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                state = dict(pid=process.pid, helper_pid=os.getpid(), start=time.time(),
                             file=command[-1], **process_identity(process.pid))
                publish_state(state)
                try:
                    process.wait(timeout=max_seconds)
                except subprocess.TimeoutExpired:
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=15)
        return process.returncode in (0, 255, -signal.SIGINT) and valid_video(command[-1])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        with log_path.open('a') as log:
            log.write(str(error) + '\n')
        return False
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if state is not None:
            try:
                if json.loads(state_path().read_text()) == state:
                    state_path().unlink()
            except (OSError, ValueError):
                pass
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        os.close(lock)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--stop']:
        stop_recording(wait=True)
    else:
        raise SystemExit('Usage: capture_backend.py --stop')
