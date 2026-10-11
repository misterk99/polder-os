#!/usr/bin/env python3
"""Polder webapps (Revision 25): install a website as an app = .desktop file running Chromium in --app mode.
All webapps share one Chromium profile (~/.config/polder-webapps) so logins persist across webapps.
Icon is real: Web App Manifest icon (largest) -> apple-touch-icon / <link rel=icon> -> /favicon.ico.
Window matching: Chromium names --app windows WM_CLASS instance '<host><path with / -> _>' (e.g. 'music.youtube.com', 'outlook.live.com__mail'),
which goes into StartupWMClass so the shelf maps the window to this entry (own icon, pinnable).
CLI: webapps.py install <url> [name] | list | remove <id>"""
import os, re, sys, json, hashlib, subprocess, urllib.request, urllib.parse, urllib.error
from html.parser import HTMLParser
DATA = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
APPS = os.path.join(DATA, 'applications'); ICONS = os.path.join(DATA, 'icons', 'polder-webapps')
PROFILE = os.path.expanduser('~/.config/polder-webapps')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8', 'Accept-Language': 'nl-NL,nl;q=0.9'}
BROWSER = next((b for b in ('chromium', 'chromium-browser', 'google-chrome') if subprocess.run(['sh', '-c', f'command -v {b}'], capture_output=True).returncode == 0), 'chromium')

def norm(url):
    url = url.strip()
    if not re.match(r'^https?://', url): url = 'https://' + url
    p = urllib.parse.urlsplit(url)
    if not p.netloc or '.' not in p.netloc: raise ValueError('Ongeldig webadres')
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))

def wm_instance(url):
    p = urllib.parse.urlsplit(url); path = p.path or '/'
    # observed (Chromium 14x, X11): '/' -> host; '/mail/' -> 'host__mail' (host + '_' + path with '/'->'_', trailing '/' dropped)
    return p.netloc if path.strip('/') == '' else p.netloc + '_' + path.rstrip('/').replace('/', '_')

def _get(url, n=3_000_000, timeout=12):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read(n), r.geturl(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:   # some sites (outlook.live.com) answer 4xx to non-browsers but still send the page
        body = e.read(n)
        if body and 'html' in (e.headers.get_content_type() or ''): return body, e.geturl() or url, 'text/html'
        raise

class _Links(HTMLParser):
    def __init__(self): super().__init__(); self.links = []; self.title = None; self._t = False
    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == 'link' and a.get('href'): self.links.append(((a.get('rel') or '').lower(), a['href'], a.get('sizes') or ''))
        if tag == 'title': self._t = True
    def handle_data(self, d):
        if self._t and self.title is None: self.title = d.strip()
    def handle_endtag(self, tag): self._t = False if tag == 'title' else self._t

def _size(s):
    m = re.findall(r'(\d+)x\d+', s or ''); return max(map(int, m)) if m else 0

def find_icon(url):
    """Returns (icon bytes, source description, page title) — raises if nothing real was found."""
    try: html, final, _ = _get(url)
    except Exception: html, final = b'', url    # page blocked for non-browsers (e.g. outlook.live.com: HTTP 417) -> still try /favicon.ico
    p = _Links(); p.feed(html.decode('utf-8', 'replace')); cands = []
    for rel, href, sizes in p.links:
        if 'manifest' in rel:
            try:
                m = json.loads(_get(urllib.parse.urljoin(final, href))[0]); mbase = urllib.parse.urljoin(final, href)
                for ic in m.get('icons', []):
                    if 'svg' in ic.get('type', '') or 'monochrome' in ic.get('purpose', ''): continue
                    cands.append((1000 + _size(ic.get('sizes')), urllib.parse.urljoin(mbase, ic['src']), 'manifest'))
                p.title = p.title or m.get('short_name') or m.get('name')
            except Exception: pass
        elif 'apple-touch-icon' in rel: cands.append((500 + (_size(sizes) or 180), urllib.parse.urljoin(final, href), 'apple-touch-icon'))
        elif 'icon' in rel.split(): cands.append((_size(sizes) or 32, urllib.parse.urljoin(final, href), 'favicon'))
    cands.append((1, urllib.parse.urljoin(final, '/favicon.ico'), 'favicon.ico'))
    for _, u, src in sorted(cands, reverse=True):
        try:
            data, _, ct = _get(u)
            if len(data) > 100 and 'html' not in ct: return data, f'{src}: {u}', p.title
        except Exception: continue
    raise RuntimeError('Geen pictogram gevonden op de website')

def install(url, name=None):
    url = norm(url); wid = hashlib.sha1(url.encode()).hexdigest()[:8]
    data, src, title = find_icon(url); name = (name or title or urllib.parse.urlsplit(url).netloc).strip()
    os.makedirs(ICONS, exist_ok=True); ext = 'ico' if data[:4] == b'\x00\x00\x01\x00' else 'png' if data[:4] == b'\x89PNG' else 'svg' if b'<svg' in data[:500] else 'img'
    raw = os.path.join(ICONS, f'{wid}.src.{ext}'); png = os.path.join(ICONS, wid + '.png')   # .src: ImageMagick sniffs the real format; png = os.path.join(ICONS, wid + '.png')
    open(raw, 'wb').write(data)
    # largest frame of .ico, square, 128px
    frames = subprocess.run(['identify', '-format', '%w %p\n', raw], capture_output=True, text=True, timeout=20).stdout.split('\n')
    best = max((tuple(map(int, f.split())) for f in frames if f.strip()), default=(0, 0))[1]   # largest frame of an .ico
    subprocess.run(['convert', '-background', 'none', f'{raw}[{best}]', '-resize', '128x128', '-gravity', 'center', '-extent', '128x128', 'png32:' + png], timeout=20, check=True)
    os.remove(raw)
    os.makedirs(APPS, exist_ok=True); desk = os.path.join(APPS, f'polder-webapp-{wid}.desktop')
    open(desk, 'w').write(f"""[Desktop Entry]
Type=Application
Name={name}
Comment=Webapp: {url}
Exec={BROWSER} --user-data-dir={PROFILE} --app={url} --class=PolderWebApp-{wid}
Icon={png}
Terminal=false
Categories=Network;WebApp;
StartupWMClass={wm_instance(url)}
X-Polder-WebApp={wid}
X-Polder-WebApp-Url={url}
X-Polder-WebApp-IconSource={src}
""")
    subprocess.run(['update-desktop-database', APPS], timeout=20, capture_output=True)
    return {'id': wid, 'name': name, 'url': url, 'icon': png, 'icon_source': src, 'desktop': desk}

def list_apps():
    out = []
    if not os.path.isdir(APPS): return out
    for f in sorted(os.listdir(APPS)):
        if f.startswith('polder-webapp-') and f.endswith('.desktop'):
            kv = dict(l.rstrip('\n').split('=', 1) for l in open(os.path.join(APPS, f)) if '=' in l)
            out.append({'id': kv.get('X-Polder-WebApp'), 'name': kv.get('Name'), 'url': kv.get('X-Polder-WebApp-Url'), 'icon': kv.get('Icon'), 'desktop': os.path.join(APPS, f)})
    return out

def remove(wid):
    for a in list_apps():
        if a['id'] == wid:
            os.remove(a['desktop'])
            try: os.remove(a['icon'])
            except OSError: pass
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb')); import osbsettings as S
            s = S.load(); did = os.path.basename(a['desktop'])
            if did in s.get('pinned', []): s['pinned'].remove(did); S.save(s)
            subprocess.run(['update-desktop-database', APPS], timeout=20, capture_output=True); return True
    return False

if __name__ == '__main__':
    c = sys.argv[1:]
    if c[:1] == ['install']: print(json.dumps(install(c[1], ' '.join(c[2:]) or None), ensure_ascii=False))
    elif c[:1] == ['list']: print(json.dumps(list_apps(), ensure_ascii=False, indent=1))
    elif c[:1] == ['remove']: print(remove(c[1]))
