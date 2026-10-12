"""Revision 27: one IPC channel for polder-shell (unix socket, newline-terminated commands:
launcher | clip | assistant | clip-clear | notify-reload | ping). send() returns True if the shell took it."""
import os, socket
SOCK = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or '/tmp', f'polder-shell-{os.getuid()}.sock')

def send(cmd, timeout=3.0):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout); s.connect(SOCK)
        s.sendall(cmd.encode() + b'\n'); ok = s.recv(16).startswith(b'ok'); s.close(); return ok
    except OSError: return False

if __name__ == '__main__':
    import sys; sys.exit(0 if send(sys.argv[1] if len(sys.argv) > 1 else 'ping') else 1)
