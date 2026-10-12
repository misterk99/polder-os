#!/usr/bin/env python3
"""Polder Sync (Rev 30): ChromeOS-style settings sync. REAL backends only:
  folder  - any directory (Nextcloud/Dropbox/rclone mount, USB stick...): <dir>/polder-sync/bundle.(json|enc)
  git     - a (private) git repo, e.g. GitHub via `gh auth login` (device flow) or any git URL / bare repo.
What syncs: whitelisted settings.json keys (theme, accent, wallpaper choice, meldingen, vergrendelen, klok, toetsenbord,
pinned apps + volgorde, weer-locatie, agenda iCal-links, assistent dienst + model), webapps (.desktop + icon) and the list of
apps installed via Polder Store (restore *offers* to install). NEVER: API keys, sync settings/passphrase, clipboard, welcome state.
Merge: per item newest timestamp wins; before applying remote values the local state is backed up to
~/.config/osb/sync-backups/. Optional client-side encryption: scrypt(passphrase) -> Fernet (AES-128-CBC + HMAC).
CLI: polder_sync.py sync [--restore] | status"""
import os, sys, json, time, base64, socket, shutil, subprocess, copy, glob
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(C, 'osb')); import osbsettings as S
CONF = os.path.dirname(S.FILE)
STATE = os.path.join(CONF, 'sync-state.json'); BACKUPS = os.path.join(CONF, 'sync-backups')
PASSFILE = os.path.join(CONF, 'sync-passphrase'); STOREFILE = os.path.join(CONF, 'store-installed.json')
def data_home(): return os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
SYNC_KEYS = ['theme', 'accent', 'wallpaper', 'notifications', 'notif_history', 'popup_secs', 'feeds', 'feed_refresh_min',
             'kbd_layout', 'kbd_variant', 'clock24', 'show_date', 'night_light', 'lock_idle_min', 'pinned', 'app_order',
             'clipboard_history', 'weather_loc', 'assistant_provider', 'assistant_model', 'auto_updates', 'display_name']
FORMAT = 'polder-sync-1'

class SyncError(Exception): pass

def cfg():
    s = S.load()
    return {'enabled': s.get('sync_enabled', False), 'backend': s.get('sync_backend', 'folder'), 'folder': s.get('sync_folder', ''),
            'git_url': s.get('sync_git_url', ''), 'encrypt': s.get('sync_encrypt', False)}

# ---------- passphrase (never synced) ----------
def _secret(): return shutil.which('secret-tool') and os.environ.get('DBUS_SESSION_BUS_ADDRESS')
def get_pass():
    if _secret():
        r = subprocess.run(['secret-tool', 'lookup', 'service', 'polder-sync'], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout: return r.stdout
    try: return open(PASSFILE).read()
    except OSError: return ''
def set_pass(p):
    if _secret() and p and subprocess.run(['secret-tool', 'store', '--label', 'Polder Sync', 'service', 'polder-sync'], input=p, text=True, capture_output=True).returncode == 0:
        return 'sleutelbos'
    if not p:
        try: os.remove(PASSFILE)
        except OSError: pass
        return ''
    os.makedirs(CONF, exist_ok=True); fd = os.open(PASSFILE + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(p)
    os.replace(PASSFILE + '.tmp', PASSFILE); return 'bestand'

# ---------- encryption ----------
def encrypt(obj, pw):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt = os.urandom(16); k = base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(pw.encode()))
    return {'format': 'polder-sync-enc-1', 'kdf': 'scrypt-n15-r8-p1', 'salt': base64.b64encode(salt).decode(),
            'data': Fernet(k).encrypt(json.dumps(obj).encode()).decode()}
def decrypt(env, pw):
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not pw: raise SyncError('De gegevens zijn versleuteld: vul je sync-wachtzin in.')
    k = base64.urlsafe_b64encode(Scrypt(salt=base64.b64decode(env['salt']), length=32, n=2**15, r=8, p=1).derive(pw.encode()))
    try: return json.loads(Fernet(k).decrypt(env['data'].encode()))
    except InvalidToken: raise SyncError('Verkeerde sync-wachtzin (kan de gegevens niet ontsleutelen).')

# ---------- local items ----------
def _webapps():
    out = {}
    for f in glob.glob(os.path.join(data_home(), 'applications', 'polder-webapp-*.desktop')):
        wid = os.path.basename(f)[len('polder-webapp-'):-len('.desktop')]
        icon = os.path.join(data_home(), 'icons', 'polder-webapps', wid + '.png')
        out['webapp:' + wid] = {'desktop': open(f).read(), 'icon': base64.b64encode(open(icon, 'rb').read()).decode() if os.path.exists(icon) else None}
    return out
def _store_apps():
    try: return sorted(json.load(open(STOREFILE)), key=lambda a: a.get('id', ''))
    except Exception: return []
def local_items():
    s = S.load(); items = {k: s.get(k) for k in SYNC_KEYS if k in s}
    items.update(_webapps()); items['store_apps'] = _store_apps(); return items

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {'snap': {}, 'ts': {}, 'last_sync': 0, 'last_result': ''}
def save_state(st):
    os.makedirs(CONF, exist_ok=True); tmp = STATE + '.tmp'; json.dump(st, open(tmp, 'w')); os.replace(tmp, STATE)

def stamp(st):
    """Give every item a timestamp: changed since last snapshot -> now; never seen -> 0 if default, else settings mtime."""
    now = time.time(); cur = local_items()
    try: fm = os.path.getmtime(S.FILE)
    except OSError: fm = 0
    for k, v in cur.items():
        if k in st['snap']:
            if st['snap'][k] != v: st['ts'][k] = now
        else: st['ts'][k] = 0 if (S.DEFAULTS.get(k) == v or v in (None, [], {})) else fm
    for k in list(st['snap']):
        if k not in cur and st['snap'][k] is not None and k.startswith('webapp:'): cur[k] = None; st['ts'][k] = now   # deleted -> tombstone
    st['snap'] = copy.deepcopy(cur); return cur

def apply_item(k, v):
    if k.startswith('webapp:'):
        wid = k[7:]; d = os.path.join(data_home(), 'applications', f'polder-webapp-{wid}.desktop'); ic = os.path.join(data_home(), 'icons', 'polder-webapps', wid + '.png')
        if v is None:
            for f in (d, ic):
                if os.path.exists(f): os.remove(f)
            return
        os.makedirs(os.path.dirname(d), exist_ok=True); os.makedirs(os.path.dirname(ic), exist_ok=True)
        if v.get('icon'): open(ic, 'wb').write(base64.b64decode(v['icon']))
        open(d, 'w').write(v['desktop'].replace('Icon=' + v['desktop'].split('Icon=')[1].split('\n')[0], 'Icon=' + ic) if 'Icon=' in v['desktop'] and v.get('icon') else v['desktop'])
    elif k == 'store_apps':
        os.makedirs(CONF, exist_ok=True); json.dump(v, open(STOREFILE, 'w'))
    elif k in SYNC_KEYS: S.update(**{k: v})

# ---------- backends ----------
class Folder:
    def __init__(self, path):
        if not path: raise SyncError('Kies eerst een map.')
        if not os.path.isdir(path): raise SyncError(f'Map bestaat niet (niet gekoppeld?): {path}')
        self.d = os.path.join(path, 'polder-sync'); os.makedirs(self.d, exist_ok=True)
    def read(self):
        for n in ('bundle.enc', 'bundle.json'):
            p = os.path.join(self.d, n)
            if os.path.exists(p): return json.load(open(p))
        return None
    def write(self, obj):
        enc = obj.get('format') == 'polder-sync-enc-1'; p = os.path.join(self.d, 'bundle.enc' if enc else 'bundle.json')
        tmp = p + f'.{socket.gethostname()}.tmp'; json.dump(obj, open(tmp, 'w'), indent=1); os.replace(tmp, p)
        other = os.path.join(self.d, 'bundle.json' if enc else 'bundle.enc')
        if os.path.exists(other): os.remove(other)   # never leave a plaintext copy next to the encrypted one

class Git:
    def __init__(self, url):
        if not url: raise SyncError('Vul eerst een git-URL in (of maak een privé GitHub-repo).')
        self.url = url; self.d = os.path.join(os.path.expanduser('~/.cache/osb'), 'sync-git')
    def g(self, *a, check=True):
        r = subprocess.run(['git', '-C', self.d, '-c', 'user.name=Polder Sync', '-c', f'user.email=polder-sync@{socket.gethostname()}', *a],
                           capture_output=True, text=True, timeout=120, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
        if check and r.returncode: raise SyncError(f'git {a[0]} mislukt: ' + (r.stderr.strip() or r.stdout.strip())[-300:])
        return r
    def _prep(self):
        if os.path.isdir(os.path.join(self.d, '.git')) and self.g('remote', 'get-url', 'origin', check=False).stdout.strip() != self.url:
            shutil.rmtree(self.d)
        if not os.path.isdir(os.path.join(self.d, '.git')):
            os.makedirs(os.path.dirname(self.d), exist_ok=True)
            r = subprocess.run(['git', 'clone', '-q', self.url, self.d], capture_output=True, text=True, timeout=120, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
            if r.returncode: raise SyncError('git clone mislukt: ' + r.stderr.strip()[-300:])
        if self.g('ls-remote', '--heads', 'origin', check=False).stdout.strip():
            self.g('fetch', '-q', 'origin'); br = self.g('rev-parse', '--abbrev-ref', 'origin/HEAD', check=False).stdout.strip() or 'origin/main'
            if br == 'origin/HEAD': br = 'origin/main'
            self.g('checkout', '-q', '-B', br.split('/', 1)[1], br); self.g('reset', '-q', '--hard', br)
        else: self.g('checkout', '-q', '-B', 'main', check=False)
    def read(self):
        self._prep()
        for n in ('bundle.enc', 'bundle.json'):
            p = os.path.join(self.d, n)
            if os.path.exists(p): return json.load(open(p))
        return None
    def write(self, obj):
        enc = obj.get('format') == 'polder-sync-enc-1'; n = 'bundle.enc' if enc else 'bundle.json'
        json.dump(obj, open(os.path.join(self.d, n), 'w'), indent=1); self.g('add', n)
        other = 'bundle.json' if enc else 'bundle.enc'
        if os.path.exists(os.path.join(self.d, other)): self.g('rm', '-q', other)
        if self.g('status', '--porcelain').stdout.strip():
            self.g('commit', '-q', '-m', f'Polder Sync van {socket.gethostname()} {time.strftime("%Y-%m-%d %H:%M")}')
            br = self.g('rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
            if self.g('push', '-q', 'origin', br, check=False).returncode:   # someone pushed meanwhile: caller retries the whole sync
                raise SyncError('git push geweigerd (andere pc was sneller); probeer opnieuw.')

def backend(c):
    return Git(c['git_url']) if c['backend'] == 'git' else Folder(c['folder'])

# ---------- sync ----------
def sync(restore=False, c=None):
    """Pull, merge (newest per item wins; restore=True: remote wins everywhere), back up + apply, push. Returns summary str."""
    c = c or cfg(); st = load_state(); be = backend(c); pw = get_pass() if c['encrypt'] else ''
    if c['encrypt'] and not pw: raise SyncError('Versleuteling staat aan maar er is geen wachtzin ingesteld.')
    cur = stamp(st); remote = be.read(); remote_enc = bool(remote) and remote.get('format') == 'polder-sync-enc-1'
    if remote and remote.get('format') == 'polder-sync-enc-1': remote = decrypt(remote, get_pass())
    ritems = (remote or {}).get('items', {})
    merged, pulled = {}, []
    for k in set(cur) | set(ritems):
        lt = st['ts'].get(k, 0) if k in cur else -1; r = ritems.get(k); rt = r['t'] if r else -1
        if r and (rt > lt or (restore and k in ritems)) and r['v'] != cur.get(k):
            merged[k] = r; pulled.append(k)
        elif k in cur and r and r['v'] == cur[k]: merged[k] = r
        elif k in cur: merged[k] = {'v': cur[k], 't': lt, 'd': socket.gethostname()}
        else: merged[k] = r
    if pulled:
        os.makedirs(BACKUPS, exist_ok=True)
        bp = os.path.join(BACKUPS, time.strftime('%Y%m%d-%H%M%S') + '.json'); json.dump({'items': cur, 'ts': st['ts']}, open(bp, 'w'), indent=1)
        for f in sorted(glob.glob(os.path.join(BACKUPS, '*.json')))[:-10]: os.remove(f)   # keep the last 10
        for k in pulled: apply_item(k, merged[k]['v']); st['ts'][k] = merged[k]['t']
        st['snap'] = local_items()
        for k in pulled:
            if merged[k]['v'] is None: st['snap'][k] = None
    bundle = {'format': FORMAT, 'updated': time.time(), 'device': socket.gethostname(), 'items': merged}
    pushed = [k for k in merged if k not in ritems or ritems[k] != merged[k]]
    if pushed or remote is None or remote_enc != bool(c['encrypt']):
        be.write(encrypt(bundle, pw) if c['encrypt'] else bundle)
    st['last_sync'] = time.time(); st['last_result'] = f'{len(pulled)} opgehaald, {len(pushed)} verstuurd'; st['last_error'] = ''
    st['pulled_keys'] = pulled; save_state(st); return st['last_result']

def sync_safe(restore=False):
    try: return True, sync(restore)
    except Exception as e:
        st = load_state(); st['last_error'] = str(e) if isinstance(e, SyncError) else f'{type(e).__name__}: {e}'; save_state(st); return False, st['last_error']

def missing_store_apps():
    """Apps from other pc's (store_apps) that are not installed here -> restore offers them."""
    debs = set(subprocess.run(['dpkg-query', '-W', '-f', '${Package}\n'], capture_output=True, text=True).stdout.split())
    flats = set(subprocess.run(['flatpak', 'list', '--app', '--columns=application'], capture_output=True, text=True).stdout.split()) if shutil.which('flatpak') else set()
    return [a for a in _store_apps() if (a['id'] not in flats if a.get('source') == 'Flathub' else a['id'] not in debs)]

if __name__ == '__main__':
    if sys.argv[1:2] == ['status']: print(json.dumps({k: v for k, v in load_state().items() if k != 'snap'}, indent=1)); sys.exit()
    if sys.argv[1:2] == ['sync']:
        if '--if-enabled' in sys.argv and not cfg()['enabled']: sys.exit(0)
        ok, msg = sync_safe('--restore' in sys.argv); print(msg); sys.exit(0 if ok else 1)
    print(__doc__)
