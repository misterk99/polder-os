"""Small nonblocking client for the current user's compositor control channel."""
import json
import os
from pathlib import Path
import re
import stat


def command(text):
    if '\n' in text or len(text.encode()) > 900:
        raise ValueError('Invalid compositor request')
    path = os.environ.get('POLDER_COMP_CMD') or str(Path(os.environ['XDG_RUNTIME_DIR']) / 'polder-comp.cmd')
    fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise RuntimeError('Compositor control channel is not a FIFO')
        os.write(fd, (text + '\n').encode())
    finally:
        os.close(fd)


def keyboard(layout, variant=''):
    if not re.fullmatch(r'[A-Za-z0-9_,-]+', layout) or not re.fullmatch(r'[A-Za-z0-9_,-]*', variant):
        raise ValueError('Invalid keyboard layout')
    command(f'keyboard {layout} {variant or "-"}')


def keyboard_state():
    try:
        return json.loads((Path(os.environ['XDG_RUNTIME_DIR']) / 'polder-keyboard.json').read_text())
    except (KeyError, OSError, ValueError):
        return {}
