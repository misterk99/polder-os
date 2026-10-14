#!/usr/bin/env python3
"""Reload the idle timeout without removing logind's sleep/lock hooks."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading

HERE = Path(__file__).resolve().parent


def read_timeout(path, previous=600):
    try:
        if 'POLDER_IDLE_SECS' in os.environ:
            value = int(os.environ['POLDER_IDLE_SECS'])
        else:
            try: settings = json.loads(path.read_text())
            except FileNotFoundError: settings = {}
            value = int(settings.get('lock_idle_min', 10)) * 60
        return value if 0 <= value <= 86400 else previous
    except (OSError, ValueError, TypeError, AttributeError):
        return previous


def idle_command(seconds):
    lock = shlex.join([str(HERE / 'lock-now.sh'), '-f'])
    command = ['swayidle', '-C', '/dev/null', '-w', 'before-sleep', lock, 'lock', lock]
    if seconds:
        command += ['timeout', str(seconds), lock]
    return command


def stop(process):
    if process is None or process.poll() is not None: return
    process.terminate()
    try: process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait()


def main():
    path = Path(os.environ.get('OSB_SETTINGS', str(Path.home() / '.config/osb/settings.json')))
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopped.set())
    previous = None
    child = None
    try:
        while not stopped.is_set():
            current = read_timeout(path, previous if previous is not None else 600)
            if current != previous or child is None or child.poll() is not None:
                stop(child)
                child = subprocess.Popen(idle_command(current))
                previous = current
                print(f'Idle locking: {current} seconds; sleep and logind lock hooks active', flush=True)
            stopped.wait(1)
    finally:
        stop(child)
    return 0


if __name__ == '__main__':
    sys.exit(main())
