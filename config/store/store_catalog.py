"""Catalog helpers shared by the Store UI and its focused tests (no GTK)."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import glob
import os
from pathlib import Path
import json
import time
from urllib.parse import urlparse

STATUS_FILE = Path('/var/lib/polderos/store-catalog/status.json')
REFRESH_UNIT = 'polder-store-catalog.service'
RETRY_SECONDS = 300
REFRESH_SECONDS = 12 * 60 * 60
ICON_ROOTS = ('/var/lib/swcatalog/icons', '/var/lib/app-info/icons', '/usr/share/swcatalog/icons')


def icon_directories(roots=ICON_ROOTS):
    # Recompute after refresh: a clean image may have no icon directories yet.
    return [directory for root in roots for size in ('64x64', '128x128')
            for directory in sorted(glob.glob(root + '/*/' + size))]


def resolve_icons(icons, kinds, directories):
    local = remote = stock = None
    for icon in icons:
        kind = icon.get_kind()
        filename, name = icon.get_filename(), icon.get_name()
        if kind in (kinds.CACHED, kinds.LOCAL):
            candidate = filename if filename and os.path.isfile(filename) else None
            if not candidate:
                basename = os.path.basename(filename or name or '')
                candidate = next((os.path.join(directory, basename) for directory in directories
                                  if basename and os.path.isfile(os.path.join(directory, basename))), None)
            if candidate and (not local or icon.get_width() == 128):
                local = candidate
        elif kind == kinds.REMOTE:
            get_url = getattr(icon, 'get_url', None)
            url = get_url() if callable(get_url) else None
            if not url and name and urlparse(name).scheme in ('http', 'https'):
                url = name  # Compatibility with metadata adapters that expose the URL as the name.
            basename = os.path.basename(urlparse(name or url or '').path)
            candidate = next((os.path.join(directory, basename) for directory in directories
                              if basename and os.path.isfile(os.path.join(directory, basename))), None)
            if candidate and not local:
                local = candidate
            elif url and urlparse(url).scheme in ('http', 'https'):
                remote = url
        elif kind == kinds.STOCK:
            stock = name
    return local, remote, stock


def collect_apps(components, desktop_kind, make_app):
    seen = {}
    for component in components:
        if component.get_kind() != desktop_kind:
            continue
        app = make_app(component)
        # Missing artwork must not hide a real, installable desktop application.
        if app.pkg or app.flatpak:
            seen.setdefault(app.key, app)
    return sorted(seen.values(), key=lambda app: app.name.lower())


def read_status(path=STATUS_FILE):
    try:
        status = json.loads(Path(path).read_text())
        if (isinstance(status, dict) and status.get('schema') == 1
                and status.get('phase') in ('not_started', 'refreshing', 'ready', 'retry')
                and isinstance(status.get('updated_at'), (int, float))):
            return status
    except (OSError, ValueError):
        pass
    return {'schema': 1, 'phase': 'not_started', 'updated_at': 0}


def should_refresh(status, app_count, last_request, now=None):
    now = time.time() if now is None else now
    if last_request and now - last_request < RETRY_SECONDS:
        return False
    age = max(0, now - status.get('updated_at', 0))
    if status.get('phase') == 'refreshing' and age < 420:
        return False
    if status.get('phase') == 'retry' and age < RETRY_SECONDS:
        return False
    return status.get('phase') != 'ready' or not app_count or age >= REFRESH_SECONDS


def status_message(status, app_count):
    phase = status.get('phase')
    if phase == 'refreshing':
        return (_('The app catalog is being updated. You can keep browsing apps.') if app_count
                else _('The app catalog is being prepared automatically…'))
    if phase == 'retry':
        if status.get('reason') == 'busy':
            return _('Another package manager is busy. We will try again automatically.')
        return (_('Updating is not possible right now. Your saved app catalog remains available.') if app_count
                else _('The app catalog is not available yet. We will try again automatically as soon as a connection is available.'))
    if not app_count:
        return _('The app catalog is being prepared automatically. This can take a while on first start.')
    return ''


def catalog_signature(home=None):
    home = Path.home() if home is None else Path(home)
    patterns = ['/var/lib/swcatalog/yaml/*', '/var/lib/swcatalog/xml/*',
                '/var/cache/swcatalog/*', '/var/cache/app-info/*']
    patterns += [root + '/*/' + size for root in ICON_ROOTS for size in ('64x64', '128x128')]
    for root in ('/var/lib/flatpak/appstream', str(home / '.local/share/flatpak/appstream')):
        patterns += [root + '/*/*/active', root + '/*/*/active/appstream.xml*']
    stamps = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                stat = os.stat(path)
                stamps.append((path, stat.st_mtime_ns, stat.st_size))
            except OSError:
                pass
    return tuple(sorted(stamps))
