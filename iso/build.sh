#!/bin/bash
# Polder OS ISO build (Debian live-build, trixie). Usage: sudo ./build.sh
# Opt-in Wayland development image: sudo env POLDER_WAYLAND=1 ./build.sh
# Generic ARM64 UEFI/QEMU image: sudo env POLDER_ARCH=arm64 POLDER_WAYLAND=1 ./build.sh
# Board-specific firmware/boot support is outside this generic ARM64 image target.
# The Wayland image builds both SceneFX effects and a plain wlroots fallback.
set -e
ISO=$(cd "$(dirname "$0")" && pwd); P=$ISO/..; VER=0.30.1
ARCH=${POLDER_ARCH:-amd64}
case "$ARCH" in
  amd64) BOOTLOADERS=grub-pc,grub-efi; BOOT_PACKAGES=(grub-efi-amd64 grub-pc-bin); B=$ISO/build ;;
  arm64) BOOTLOADERS=grub-efi; BOOT_PACKAGES=(grub-efi-arm64); B=$ISO/build-arm64 ;;
  *) echo 'POLDER_ARCH must be amd64 or arm64' >&2; exit 2 ;;
esac
PACKAGED=0
PACKAGE_DIR=${POLDER_PACKAGE_DIR:-$P/build/packages}
if [ "$ARCH" = arm64 ]; then
  for package in polder-compositor polder-desktop polder-settings; do
    matches=("$PACKAGE_DIR"/"$package"_*.deb)
    if [ ! -f "${matches[0]}" ] || [ "${#matches[@]}" -ne 1 ]; then
      echo "Missing one built $package package in $PACKAGE_DIR; see docs/package-updates.md." >&2
      exit 2
    fi
    expected_arch=all
    [ "$package" != polder-compositor ] || expected_arch=arm64
    if [ "$(dpkg-deb -f "${matches[0]}" Package)" != "$package" ] || \
       [ "$(dpkg-deb -f "${matches[0]}" Architecture)" != "$expected_arch" ]; then
      echo "Wrong package name or architecture for ${matches[0]} (expected $package/$expected_arch)." >&2
      exit 2
    fi
  done
  KEYRING_PACKAGES=("$PACKAGE_DIR"/polder-archive-keyring_*.deb)
  if [ -f "${KEYRING_PACKAGES[0]}" ]; then
    if [ "${#KEYRING_PACKAGES[@]}" -ne 1 ] || [ -f "$PACKAGE_DIR/TEST-ONLY" ]; then
      echo 'Refusing ambiguous or TEST-ONLY archive keyring package in ISO input.' >&2
      exit 2
    fi
    if [ "$(dpkg-deb -f "${KEYRING_PACKAGES[0]}" Package)" != polder-archive-keyring ] || \
       [ "$(dpkg-deb -f "${KEYRING_PACKAGES[0]}" Architecture)" != all ]; then
      echo "Wrong package name or architecture for ${KEYRING_PACKAGES[0]}." >&2
      exit 2
    fi
  fi
  PACKAGED=1
fi
case ${POLDER_WAYLAND:-0} in 0|1) ;; *) echo 'POLDER_WAYLAND must be 0 or 1' >&2; exit 2 ;; esac
BUILD_WITH_CHROOT=true
if [ "${POLDER_WAYLAND:-0}" = 1 ]; then
  # live-build's chrooted binary stage can upgrade the kernel after squashfs is
  # created. Host-side assembly keeps the boot files and module tree together.
  BUILD_WITH_CHROOT=false
  BUILD_ARCH=$(dpkg --print-architecture)
  if [ "$BUILD_ARCH" != "$ARCH" ]; then
    echo "Wayland ISO assembly needs $ARCH build userspace (found $BUILD_ARCH); use the matching Docker SDK." >&2
    exit 2
  fi
  for tool in lb debootstrap rsync convert mksquashfs unsquashfs xorriso grub-mkimage mcopy mkfs.msdos; do
    command -v "$tool" >/dev/null || { echo "Missing Wayland ISO host tool: $tool" >&2; exit 2; }
  done
  HOST_BOOT_FILES=(/usr/lib/ISOLINUX/isohdpfx.bin)
  if [ "$ARCH" = amd64 ]; then
    HOST_BOOT_FILES+=(/usr/lib/grub/i386-pc/vga.mod /usr/lib/grub/i386-pc/boot_hybrid.img
      /usr/lib/grub/x86_64-efi/configfile.mod /usr/lib/grub/i386-efi/configfile.mod)
  else
    HOST_BOOT_FILES+=(/usr/lib/grub/arm64-efi/configfile.mod)
  fi
  for boot_file in "${HOST_BOOT_FILES[@]}"; do
    [ -f "$boot_file" ] || { echo "Missing Wayland ISO host boot file: $boot_file" >&2; exit 2; }
  done
fi
IMAGE_NAME=polderos-$VER
[ "${POLDER_WAYLAND:-0}" = 0 ] || IMAGE_NAME=$IMAGE_NAME-wayland-dev
mkdir -p "$B"; cd "$B"
lb clean >/dev/null 2>&1 || true
rm -rf config
lb config --distribution trixie --architectures "$ARCH" --linux-flavours "$ARCH" --binary-images iso-hybrid \
  --archive-areas "main contrib non-free-firmware" --mirror-bootstrap http://deb.debian.org/debian \
  --mirror-binary http://deb.debian.org/debian --mirror-chroot http://deb.debian.org/debian --mirror-chroot-security http://deb.debian.org/debian-security --mirror-binary-security http://deb.debian.org/debian-security --security true --updates true \
  --apt-recommends false --apt-options "--yes -o Acquire::Retries=10" \
  --debian-installer none --firmware-chroot false --firmware-binary false --build-with-chroot "$BUILD_WITH_CHROOT" \
  --bootappend-live "boot=live components quiet splash locales=nl_NL.UTF-8 keyboard-layouts=us timezone=Europe/Amsterdam username=polder user-fullname=Polder hostname=polderos" \
  --iso-application "Polder OS" --iso-volume "POLDEROS_${VER//./_}_${ARCH^^}" --iso-publisher "Polder OS" \
  --bootloaders "$BOOTLOADERS" --image-name "$IMAGE_NAME" --memtest none --cache true
cp "$ISO/src/polderos.list.chroot" config/package-lists/
printf '%s\n' "linux-image-$ARCH" "${BOOT_PACKAGES[@]}" > config/package-lists/polderos-architecture.list.chroot
# our code + session + branding
G=$P/config/iso/greeter
R=config/includes.chroot; mkdir -p "$R/usr/share/xsessions" "$R/usr/share/xgreeters" "$R/etc/lightdm/lightdm.conf.d" "$R/usr/local/bin"
if [ "$PACKAGED" = 1 ]; then
  mkdir -p config/packages.chroot
  for package in polder-compositor polder-desktop polder-settings; do
    cp "${PACKAGE_DIR}/${package}_"*.deb config/packages.chroot/
  done
  if [ -f "${KEYRING_PACKAGES[0]}" ]; then
    cp "${KEYRING_PACKAGES[0]}" config/packages.chroot/
  fi
else
  mkdir -p "$R/usr/share/polderos"
  rsync -a --delete --exclude __pycache__ --exclude spotify-run.sh --exclude 'osb-desk-*' "$P/config/" "$R/usr/share/polderos/config/"
  echo "$VER" > "$R/usr/share/polderos/VERSION"
  install -m755 "$ISO/src/polderos-session" "$R/usr/share/polderos/polderos-session"
  sed 's|^Exec=.*|Exec=/usr/share/polderos/polderos-session|' "$G/polderos.desktop" > "$R/usr/share/xsessions/polderos.desktop"
  sed 's|^Exec=.*|Exec=python3 /usr/share/polderos/config/lock/polderos-greeter.py|' "$G/polderos-greeter.desktop" > "$R/usr/share/xgreeters/polderos-greeter.desktop"
  { cat "$G/50-polderos.conf"; echo autologin-session=polderos; } > "$R/etc/lightdm/lightdm.conf.d/50-polderos.conf"
fi
cp -a "$ISO/src/rootfs/." "$R/"
if [ "$PACKAGED" != 1 ]; then
  install -Dm755 "$ISO/src/polder-store-catalog-refresh" "$R/usr/libexec/polder-store-catalog-refresh"
fi
for hook in "$ISO/src/hooks/"*; do
  if [ "${POLDER_WAYLAND:-0}" != 1 ] && [ "$(basename "$hook")" = 0610-polderos-portal.hook.chroot ]; then
    continue
  fi
  cp "$hook" config/hooks/normal/
done
chmod 755 config/hooks/normal/*.hook.*
if [ "${POLDER_WAYLAND:-0}" = 1 ]; then
  # This opt-in development image boots the new session; the greeter also offers X11.
  sed -i 's/^user-session=.*/user-session=polderos-wayland/; s/^autologin-session=.*/autologin-session=polderos-wayland/' "$R/etc/lightdm/lightdm.conf.d/50-polderos.conf"
  cp "$ISO/src/polderos-wayland.list.chroot" config/package-lists/
  mkdir -p "$R/usr/share/wayland-sessions"
  if [ "$PACKAGED" != 1 ]; then
    mkdir -p "$R/usr/local/src/polder-comp"
    install -m755 "$ISO/src/polderos-wayland-session" "$ISO/src/polderos-wayland-components" "$R/usr/share/polderos/"
    install -m755 "$ISO/src/polder-compositor" "$R/usr/local/bin/"
    install -m755 "$P/tools/testing/build-scenefx.sh" "$R/usr/local/src/"
    rsync -a --exclude '/build*/' --exclude '*.o' "$P/compositor/polder-comp/" "$R/usr/local/src/polder-comp/"
  fi
  mkdir -p "$R/usr/local/src/polder-portal"
  install -m755 "$P/tools/testing/build-capture-portal.sh" "$R/usr/local/src/polder-portal/"
  install -m644 "$P/tools/testing/xdg-desktop-portal-wlr-0.7.1-shm.patch" "$R/usr/local/src/polder-portal/"
  install -m644 "$G/polderos-wayland.desktop" "$R/usr/share/wayland-sessions/"
  mkdir -p "$R/usr/share/xdg-desktop-portal"
  cat > "$R/usr/share/xdg-desktop-portal/polderos-portals.conf" <<'PORTALS'
[preferred]
default=gtk
org.freedesktop.impl.portal.ScreenCast=wlr
org.freedesktop.impl.portal.Screenshot=wlr
PORTALS
  mkdir -p "$R/etc/xdg/xdg-desktop-portal-wlr" "$R/etc/systemd/logind.conf.d"
  cat > "$R/etc/xdg/xdg-desktop-portal-wlr/PolderOS" <<'CHOOSER'
[screencast]
max_fps=30
chooser_type=dmenu
chooser_cmd=python3 /usr/share/polderos/config/capture/portal-chooser.py
CHOOSER
  printf '[Login]\nInhibitDelayMaxSec=15s\n' > "$R/etc/systemd/logind.conf.d/50-polderos-lock.conf"
fi
# live-build uses the grub-pc template directory for both BIOS and UEFI, including ARM64.
# boot menus: title + wallpaper
mkdir -p config/bootloaders; cp -a /usr/share/live/build/bootloaders/grub-pc config/bootloaders/
# The stock template has no timeout; a live image should start without a keypress.
sed -i '/^set default=0/a set timeout=5\nset timeout_style=menu' config/bootloaders/grub-pc/config.cfg
if [ "$ARCH" = arm64 ]; then
  # These PC graphics modules do not exist in GRUB's arm64-efi package.
  sed -i '/insmod efi_uga/d; /insmod video_bochs/d; /insmod video_cirrus/d' config/bootloaders/grub-pc/config.cfg
fi
convert "$P/config/wallpapers/polderheuvel.png" -resize 800x600! -fill black -colorize 35% config/bootloaders/grub-pc/splash.png
sed -i 's/^title-text:.*/title-text: "Polder OS 0.30.1"/' config/bootloaders/grub-pc/live-theme/theme.txt
date +%s > build.start
lb build
