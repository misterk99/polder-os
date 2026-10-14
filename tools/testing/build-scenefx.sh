#!/bin/bash
# Build the pinned effects library against the system wlroots 0.18 SDK.
# Usage: build-scenefx.sh /absolute/work-directory [/absolute/install-prefix]
# Requires: build-essential meson ninja-build pkg-config curl ca-certificates
# libwlroots-0.18-dev libwayland-dev wayland-protocols libdrm-dev
# libxkbcommon-dev libpixman-1-dev libegl-dev libgles-dev libgbm-dev.
set -euo pipefail

readonly VERSION=0.2.1
readonly COMMIT=87c0e8b6d5c86557a800445e8e4c322f387fe19c
readonly SHA256=8bca18dd0a082a064042ecd9b77de17cf729d398d2ba0c703bd672fb9b39c109
WORK=${1:?Usage: build-scenefx.sh /absolute/work-directory [/absolute/install-prefix]}
PREFIX=${2:-/usr/local}
case "$WORK:$PREFIX" in /*:/*) ;; *) echo 'Work directory and prefix must be absolute.' >&2; exit 2 ;; esac
mkdir -p "$WORK" "$PREFIX"
exec 9>"$WORK/build.lock"
flock -n 9 || { echo 'Another SceneFX build is using this directory.' >&2; exit 1; }

# Refuse dependency subprojects: the compositor and effects library must use
# the same distro wlroots, rather than a silently downloaded second copy.
pkg-config --atleast-version=0.18.1 wlroots-0.18
pkg-config --max-version=0.18.99 wlroots-0.18
pkg-config --atleast-version=1.23 wayland-server
pkg-config --atleast-version=1.35 wayland-protocols
pkg-config --atleast-version=2.4.122 libdrm
pkg-config --atleast-version=0.42 pixman-1
pkg-config --exists xkbcommon egl glesv2 gbm wayland-scanner

ARCHIVE="$WORK/scenefx-$COMMIT.tar.gz"
if [[ ! -f "$ARCHIVE" ]]; then
    curl --fail --location --retry 2 \
        "https://codeload.github.com/wlrfx/scenefx/tar.gz/$COMMIT" -o "$ARCHIVE.part"
    printf '%s  %s\n' "$SHA256" "$ARCHIVE.part" | sha256sum --check --status
    mv "$ARCHIVE.part" "$ARCHIVE"
fi
printf '%s  %s\n' "$SHA256" "$ARCHIVE" | sha256sum --check

SOURCE="$WORK/scenefx-$COMMIT"
if [[ ! -d "$SOURCE" ]]; then
    tar -xzf "$ARCHIVE" -C "$WORK"
fi
BUILD="$WORK/build-$COMMIT"
MESON_ARGS=(--wrap-mode=nofallback --buildtype=release --prefix "$PREFIX"
    --libdir lib -Dexamples=false -Drenderers=gles2)
if [[ -f "$BUILD/meson-private/coredata.dat" ]]; then
    meson setup --reconfigure "${MESON_ARGS[@]}" "$BUILD" "$SOURCE"
else
    meson setup "${MESON_ARGS[@]}" "$BUILD" "$SOURCE"
fi
meson compile -C "$BUILD" -j 2
meson install -C "$BUILD" --no-rebuild
install -Dm644 "$SOURCE/LICENSE" "$PREFIX/share/doc/scenefx-$VERSION/LICENSE"
printf 'SceneFX %s\ncommit=%s\nsource_sha256=%s\n' "$VERSION" "$COMMIT" "$SHA256" \
    > "$PREFIX/share/doc/scenefx-$VERSION/build.txt"
printf 'SceneFX %s installed in %s\n' "$VERSION" "$PREFIX"
printf 'PKG_CONFIG_PATH=%s/lib/pkgconfig\nLD_LIBRARY_PATH=%s/lib\n' "$PREFIX" "$PREFIX"
