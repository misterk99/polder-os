#!/bin/bash
# Polder OS ISO build (Debian live-build, trixie amd64). Usage: sudo ./build.sh   (log: build/build.log)
set -e
ISO=$(cd "$(dirname "$0")" && pwd); P=$ISO/..; B=$ISO/build; VER=0.30.1
mkdir -p $B; cd $B
lb clean >/dev/null 2>&1 || true
rm -rf config
lb config --distribution trixie --architectures amd64 --binary-images iso-hybrid \
  --archive-areas "main contrib non-free-firmware" --mirror-bootstrap http://deb.debian.org/debian \
  --mirror-binary http://deb.debian.org/debian --mirror-chroot http://deb.debian.org/debian --mirror-chroot-security http://deb.debian.org/debian-security --mirror-binary-security http://deb.debian.org/debian-security --security true --updates true \
  --apt-recommends false --apt-options "--yes -o Acquire::Retries=10" \
  --debian-installer none --firmware-chroot false --firmware-binary false \
  --bootappend-live "boot=live components quiet splash locales=nl_NL.UTF-8 keyboard-layouts=us timezone=Europe/Amsterdam username=polder user-fullname=Polder hostname=polderos" \
  --iso-application "Polder OS" --iso-volume "POLDEROS_${VER//./_}" --iso-publisher "Polder OS" \
  --bootloaders grub-pc,grub-efi --image-name polderos-$VER --memtest none --cache true
cp $ISO/src/polderos.list.chroot config/package-lists/
# our code + session + branding
R=config/includes.chroot; mkdir -p $R/usr/share/polderos $R/usr/share/xsessions $R/usr/share/xgreeters $R/etc/lightdm/lightdm.conf.d $R/usr/local/bin
rsync -a --delete --exclude __pycache__ --exclude spotify-run.sh --exclude 'osb-desk-*' $P/config/ $R/usr/share/polderos/config/
echo $VER > $R/usr/share/polderos/VERSION
install -m755 $ISO/src/polderos-session $R/usr/share/polderos/polderos-session
G=$P/config/iso/greeter
sed 's|^Exec=.*|Exec=/usr/share/polderos/polderos-session|' $G/polderos.desktop > $R/usr/share/xsessions/polderos.desktop
sed 's|^Exec=.*|Exec=python3 /usr/share/polderos/config/lock/polderos-greeter.py|' $G/polderos-greeter.desktop > $R/usr/share/xgreeters/polderos-greeter.desktop
{ cat $G/50-polderos.conf; echo autologin-session=polderos; } > $R/etc/lightdm/lightdm.conf.d/50-polderos.conf
cp -a $ISO/src/rootfs/. $R/
cp $ISO/src/hooks/* config/hooks/normal/
# boot menus: title + wallpaper
mkdir -p config/bootloaders; cp -a /usr/share/live/build/bootloaders/grub-pc config/bootloaders/
convert $P/config/wallpapers/polderheuvel.png -resize 800x600! -fill black -colorize 35% config/bootloaders/grub-pc/splash.png
sed -i 's/^title-text:.*/title-text: "Polder OS 0.30.1"/' config/bootloaders/grub-pc/live-theme/theme.txt
date +%s > build.start
lb build
