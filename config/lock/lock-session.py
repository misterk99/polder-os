#!/usr/bin/env python3
"""One supervised Wayland locker per session; success means compositor acknowledgement."""
import argparse
import fcntl
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ACK_TIMEOUT = 4.0
REQUEST_TIMEOUT = ACK_TIMEOUT * 2 + 2


def runtime_dir():
    base = Path(os.environ['XDG_RUNTIME_DIR'])
    if base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o077:
        raise RuntimeError('XDG_RUNTIME_DIR must be private and owned by this user')
    path = Path(os.environ.get('OSB_RUNDIR', str(base / 'polderos-wayland'))) / 'lock'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise RuntimeError('Lock runtime directory is not private')
    return path


def stop_child(child):
    if child is not None and child.poll() is None:
        # The compositor keeps its opaque cover if a locker dies.
        child.kill()
        child.wait(timeout=3)


def serve(path, commands=None, ack_timeout=ACK_TIMEOUT):
    """Keep ownership until unlock and recover a failed GTK locker with swaylock."""
    commands = commands or [[sys.executable, str(HERE / 'lock-wayland.py')],
                            ['bash', str(HERE / 'polder-lock-wayland.sh')]]
    with (path / 'controller.lock').open('w') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        address = path / 'controller.sock'
        address.unlink(missing_ok=True)
        selector = selectors.DefaultSelector()
        server = socket.socket(socket.AF_UNIX)
        clients = []
        child = None
        ready_fd = None
        try:
            server.bind(str(address)); server.listen(16); server.setblocking(False)
            selector.register(server, selectors.EVENT_READ)

            def broadcast(message):
                for client in clients[:]:
                    try:
                        client.sendall(message)
                    except OSError:
                        clients.remove(client); client.close()

            for index, command in enumerate(commands):
                read_fd, write_fd = os.pipe()
                ready_fd = read_fd
                env = dict(os.environ, POLDER_LOCK_READY_FD=str(write_fd))
                argv = list(command)
                if index:
                    argv += ['--ready-fd', str(write_fd)]
                try:
                    child = subprocess.Popen(argv, env=env, pass_fds=(write_fd,))
                except OSError as error:
                    print(f'Could not start locker: {error}; trying fallback.', flush=True)
                    os.close(read_fd); ready_fd = None
                    continue
                finally:
                    os.close(write_fd)
                selector.register(read_fd, selectors.EVENT_READ)
                deadline = time.monotonic() + ack_timeout
                acknowledged = False
                while True:
                    for key, _x in selector.select(.1):
                        if key.fileobj is server:
                            client, _x = server.accept(); client.settimeout(.2)
                            clients.append(client)
                            if acknowledged:
                                try: client.sendall(b'LOCKED\n')
                                except OSError: clients.remove(client); client.close()
                        elif key.fd == ready_fd:
                            data = os.read(read_fd, 64)
                            selector.unregister(read_fd); os.close(read_fd); ready_fd = None
                            if data == b'\n':
                                acknowledged = True
                                broadcast(b'LOCKED\n')
                    result = child.poll()
                    if result is not None:
                        if result == 0 and acknowledged:
                            broadcast(b'UNLOCKED\n')
                            return 0
                        print(f'Locker exited before unlock (status {result}); trying fallback.', flush=True)
                        break
                    if not acknowledged and time.monotonic() >= deadline:
                        print('Locker acknowledgement timed out; trying fallback.', flush=True)
                        stop_child(child)
                        break
                if ready_fd is not None:
                    selector.unregister(ready_fd); os.close(ready_fd); ready_fd = None
            broadcast(b'ERROR\n')
            return 1
        finally:
            stop_child(child)
            if ready_fd is not None: os.close(ready_fd)
            for client in clients: client.close()
            selector.close(); server.close(); address.unlink(missing_ok=True)


def request(path, daemonize=False):
    deadline = time.monotonic() + REQUEST_TIMEOUT
    launched = False
    while time.monotonic() < deadline:
        client = socket.socket(socket.AF_UNIX)
        try:
            client.connect(str(path / 'controller.sock'))
        except (FileNotFoundError, ConnectionRefusedError):
            client.close()
            if not launched:
                with (path / 'locker.log').open('ab') as log:
                    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True)
                launched = True
            time.sleep(.025)
            continue
        with client:
            client.settimeout(max(.1, deadline - time.monotonic()))
            stream = client.makefile('rb')
            if stream.readline(64) != b'LOCKED\n':
                raise RuntimeError('Locker failed to acknowledge the session lock')
            if daemonize:
                return 0
            client.settimeout(None)
            message = stream.readline(64)
            while message == b'LOCKED\n':  # a replacement locker took over after a crash
                message = stream.readline(64)
            if message != b'UNLOCKED\n':
                raise RuntimeError('Locker ended without a confirmed unlock')
            return 0
    raise RuntimeError('Timed out waiting for the session locker')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-f', '--daemonize', action='store_true', help='return after the compositor confirms locking')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        path = runtime_dir()
        return serve(path) if args.serve else request(path, args.daemonize)
    except (OSError, RuntimeError) as error:
        print(f'Could not lock session: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
