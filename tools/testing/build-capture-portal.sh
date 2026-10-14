#!/bin/sh
# Build the trixie-compatible portal with the small SHM compatibility patch.
# Prerequisites beyond the compositor SDK: libpipewire-0.3-dev, libinih-dev.
# Usage: build-capture-portal.sh WORK_DIRECTORY DESTINATION_ROOT
set -eu
[ "$#" -eq 2 ] || { echo "Usage: $0 WORK_DIRECTORY DESTINATION_ROOT" >&2; exit 2; }
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p -- "$1" "$2"
work=$(CDPATH= cd -- "$1" && pwd)
dest=$(CDPATH= cd -- "$2" && pwd)
version=0.7.1
checksum=4bddc236aa9d1a2b33e7f0bef09a8712ded51e8bc335a2b6c8cd1d088863e676
archive="$work/xdg-desktop-portal-wlr-$version.tar.gz"
if [ ! -f "$archive" ]; then
    curl --fail --location --retry 3 \
        "https://codeload.github.com/emersion/xdg-desktop-portal-wlr/tar.gz/refs/tags/v$version" \
        --output "$archive"
fi
printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status
source_dir=$(mktemp -d "$work/source.XXXXXX")
tar -xzf "$archive" --strip-components=1 -C "$source_dir"
# Windows checkout line endings must not change the patch context.
tr -d '\r' < "$here/xdg-desktop-portal-wlr-0.7.1-shm.patch" > "$source_dir/polder-shm.patch"
patch --directory "$source_dir" --strip=1 < "$source_dir/polder-shm.patch"
meson setup "$source_dir/build" "$source_dir" --prefix=/usr/local --sysconfdir=/etc \
    --libexecdir=libexec --buildtype=release -Dstrip=true -Dman-pages=disabled \
    -Dsystemd=disabled -Dsd-bus-provider=libsystemd
ninja -C "$source_dir/build" -j "${POLDER_BUILD_JOBS:-2}"

# Keep Debian's packaged backend and metadata available; override only activation.
install -Dm755 "$source_dir/build/xdg-desktop-portal-wlr" "$dest/usr/local/libexec/xdg-desktop-portal-wlr"
install -Dm644 "$source_dir/LICENSE" "$dest/usr/local/share/doc/polderos-portal/LICENSE"
mkdir -p "$dest/usr/local/share/dbus-1/services" "$dest/etc/systemd/user/xdg-desktop-portal-wlr.service.d"
cat > "$dest/usr/local/share/dbus-1/services/org.freedesktop.impl.portal.desktop.wlr.service" <<'EOF'
[D-BUS Service]
Name=org.freedesktop.impl.portal.desktop.wlr
Exec=/usr/local/libexec/xdg-desktop-portal-wlr
SystemdService=xdg-desktop-portal-wlr.service
EOF
cat > "$dest/etc/systemd/user/xdg-desktop-portal-wlr.service.d/polderos.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/libexec/xdg-desktop-portal-wlr
EOF
{
    printf 'xdg-desktop-portal-wlr %s + Polder SHM compatibility\nsource_sha256=%s\n' "$version" "$checksum"
    printf 'patch_sha256='
    sha256sum "$source_dir/polder-shm.patch" | cut -d ' ' -f1
} > "$dest/usr/local/share/doc/polderos-portal/build.txt"
printf 'Installed portal backend and activation overrides under %s\n' "$dest"
