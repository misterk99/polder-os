"""Rev 34: raise/close windows on polder-comp through wlr-foreign-toplevel-management (helper polder-toplevels,
JSON lines out, '<cmd> <id>' in). The Wayland counterpart of 'xdotool search --class X windowactivate'."""
import os, json, shutil, subprocess, time, select

def helper():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get('POLDER_TOPLEVELS') or shutil.which('polder-toplevels') or \
        os.path.join(here, '..', '..', 'compositor', 'polder-comp', 'tools', 'polder-toplevels')

def toplevels(p=None, wait=0.4):
    """Snapshot {id: state} (the helper prints every toplevel right after binding)."""
    own = p is None
    if own: p = subprocess.Popen([helper()], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    tl, buf, end = {}, b'', time.time() + wait
    while time.time() < end:
        r, _, _ = select.select([p.stdout], [], [], max(0, end - time.time()))
        if not r: break
        d = os.read(p.stdout.fileno(), 65536)
        if not d: break
        buf += d; *lines, buf = buf.split(b'\n')
        for l in lines:
            try: ev = json.loads(l)
            except ValueError: continue
            if ev.get('ev') == 'state': tl[ev['id']] = ev
            elif ev.get('ev') == 'closed': tl.pop(ev['id'], None)
    if own: p.kill()
    return tl

def raise_app(cls):
    """Activate the newest toplevel whose app_id (or title) matches cls; True if one was found."""
    try: p = subprocess.Popen([helper()], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    except OSError: return False
    try:
        c = cls.lower(); hit = [i for i, t in toplevels(p).items() if c in ((t.get('app_id') or '').lower(), (t.get('title') or '').lower())
                                 or (t.get('app_id') or '').lower().endswith('.' + c)]
        if hit: p.stdin.write(f'activate {max(hit)}\n'.encode()); p.stdin.flush(); time.sleep(0.2)
        return bool(hit)
    finally: p.kill()
