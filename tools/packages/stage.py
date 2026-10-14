#!/usr/bin/env python3
"""Stage only package-owned files; debian/*.install is the binary manifest."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--version', required=True)
parser.add_argument('--destination', type=Path, required=True)
args = parser.parse_args()
dest = args.destination


def copy(source, target, mode=None):
    target = dest / target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(mode or 0o644)


def write(target, text, mode=0o644):
    path = dest / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(mode)


digest = hashlib.sha256(args.version.encode())
for path in sorted(Path('config').rglob('*')):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
        continue
    if path.name == 'spotify-run.sh' or path.name.startswith('osb-desk-'):
        continue
    digest.update(str(path).encode())
    digest.update(path.read_bytes())
    copy(path, 'usr/share/polderos/' + path.as_posix(),
         0o755 if path.suffix == '.sh' or path.name == 'polder-autoupdate' else 0o644)

# VERSION historically also invalidates X11's per-user configuration. Use the
# source package version so every desktop/settings update refreshes both sessions.
write('usr/share/polderos/VERSION', args.version + '\n')
write('usr/share/polderos/WAYLAND_CONFIG_VERSION', digest.hexdigest() + '\n')
for name in ('polderos-session', 'polderos-wayland-session', 'polderos-wayland-components'):
    copy('iso/src/' + name, 'usr/share/polderos/' + name, 0o755)
copy('iso/src/polder-compositor', 'usr/bin/polder-compositor', 0o755)
copy('iso/src/polder-store-catalog-refresh', 'usr/libexec/polder-store-catalog-refresh', 0o755)
for session, target in (('polderos.desktop', 'xsessions'), ('polderos-wayland.desktop', 'wayland-sessions'), ('polderos-greeter.desktop', 'xgreeters')):
    text = (Path('config/iso/greeter') / session).read_text()
    if target == 'xsessions':
        text = text.replace('/usr/share/polderos/start-session.sh', '/usr/share/polderos/polderos-session')
    if target == 'xgreeters':
        text = '\n'.join('Exec=python3 /usr/share/polderos/config/lock/polderos-greeter.py' if line.startswith('Exec=') else line for line in text.splitlines()) + '\n'
    write('usr/share/' + target + '/' + session, text)
write('etc/lightdm/lightdm.conf.d/50-polderos.conf', '[Seat:*]\ngreeter-session=polderos-greeter\nuser-session=polderos\n')
write('etc/apt/apt.conf.d/52polderos-unattended-upgrades',
      'Unattended-Upgrade::Origins-Pattern {\n'
      '  "origin=PolderOS,codename=${distro_codename},label=Polder OS";\n'
      '};\n')
copy('iso/src/rootfs/etc/polkit-1/rules.d/49-polderos-store.rules', 'etc/polkit-1/rules.d/49-polderos-store.rules')
copy('iso/src/rootfs/etc/apt/apt.conf.d/60polder-store-appstream', 'etc/apt/apt.conf.d/60polder-store-appstream')
copy('iso/src/rootfs/usr/share/polkit-1/actions/nl.polderos.autoupdate.policy', 'usr/share/polkit-1/actions/nl.polderos.autoupdate.policy')
for unit in ('polder-flatpak-update.service', 'polder-flatpak-update.timer'):
    copy('iso/src/rootfs/etc/systemd/system/' + unit, 'usr/lib/systemd/system/' + unit)
for unit in ('polder-store-catalog.service', 'polder-store-catalog.timer'):
    copy('iso/src/rootfs/usr/lib/systemd/system/' + unit, 'usr/lib/systemd/system/' + unit)
write('usr/bin/polder-settings', '#!/bin/sh\nexec python3 "${POLDER_CONFIG:-${XDG_DATA_HOME:-$HOME/.local/share}/polderos}/settings/instellingen.py" "$@"\n', 0o755)
text = Path('config/settings/instellingen.desktop').read_text()
text = '\n'.join('Exec=polder-settings' if line.startswith('Exec=') else line for line in text.splitlines()) + '\n'
write('usr/share/applications/polder-settings.desktop', text)
if os.environ.get('POLDER_COMPONENTS_ONLY') != '1':
    copy('debian/keyring/polder-archive-keyring.asc', 'usr/share/keyrings/polder-archive-keyring.asc')
    copy('debian/keyring/polder.sources', 'etc/apt/sources.list.d/polder.sources')
