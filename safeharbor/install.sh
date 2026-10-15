#!/bin/bash
# Install Polder SafeHarbor into a root filesystem: install.sh [DESTDIR]   (default /)
# Needs on the target: snapper, btrfs-progs, inotify-tools (grub-btrfsd), grub, initramfs-tools, python3, polkitd.
# Layout requirement (installer's job, see docs/safeharbor.md): btrfs subvolumes @ @home @snapshots @var_log @cache.
set -e
H=$(cd "$(dirname "$0")" && pwd); D=${1:-}
inst() { install -D -m "$1" "$2" "$D$3"; }
inst 755 $H/helper/polder-safeharbor-helper /usr/libexec/polder-safeharbor-helper
inst 755 $H/apt/apt-pre /usr/lib/polder-safeharbor/apt-pre
inst 755 $H/apt/apt-post /usr/lib/polder-safeharbor/apt-post
inst 644 $H/apt/80polder-safeharbor /etc/apt/apt.conf.d/80polder-safeharbor
inst 755 $H/systemd/boot-check /usr/lib/polder-safeharbor/boot-check
inst 644 $H/systemd/polder-safeharbor-boot.service /usr/lib/systemd/system/polder-safeharbor-boot.service
inst 644 $H/systemd/polder-safeharbor-boot-ok.service /usr/lib/systemd/system/polder-safeharbor-boot-ok.service
mkdir -p $D/etc/systemd/system/sysinit.target.wants $D/etc/systemd/system/multi-user.target.wants
ln -sf /usr/lib/systemd/system/polder-safeharbor-boot.service $D/etc/systemd/system/sysinit.target.wants/
ln -sf /usr/lib/systemd/system/polder-safeharbor-boot-ok.service $D/etc/systemd/system/multi-user.target.wants/
inst 755 $H/initramfs/hook /etc/initramfs-tools/hooks/polder-safeharbor
inst 755 $H/initramfs/local-bottom /etc/initramfs-tools/scripts/local-bottom/polder-safeharbor
inst 644 $H/polkit/org.polderos.safeharbor.policy /usr/share/polkit-1/actions/org.polderos.safeharbor.policy
inst 644 $H/polkit/50-polder-safeharbor.rules /usr/share/polkit-1/rules.d/50-polder-safeharbor.rules
[ -e $D/etc/snapper/configs/root ] || inst 640 $H/snapper/root /etc/snapper/configs/root
mkdir -p $D/etc/default
cat > $D/etc/default/snapper <<'S'
# snapper: root config is managed by Polder SafeHarbor; its apt hook replaces snapper's own (80snapper)
SNAPPER_CONFIGS="root"
DISABLE_APT_SNAPSHOT="yes"
S
[ -e $D/etc/default/polder-safeharbor ] || printf '# Polder SafeHarbor: snapshots before apt / unattended-upgrades\nSAFEHARBOR_AUTO=yes\n' > $D/etc/default/polder-safeharbor
# grub-btrfs (vendored, not in trixie) + Polder menu settings
inst 755 $H/vendor/grub-btrfs/41_snapshots-btrfs /etc/grub.d/41_snapshots-btrfs
{ cat $H/vendor/grub-btrfs/config; echo; cat $H/grub/grub-btrfs-config; } > $H/.cfg.tmp && inst 644 $H/.cfg.tmp /etc/default/grub-btrfs/config && rm $H/.cfg.tmp
inst 755 $H/vendor/grub-btrfs/grub-btrfsd /usr/bin/grub-btrfsd
inst 644 $H/vendor/grub-btrfs/grub-btrfsd.service /usr/lib/systemd/system/grub-btrfsd.service
ln -sf /usr/lib/systemd/system/grub-btrfsd.service $D/etc/systemd/system/multi-user.target.wants/
inst 644 $H/vendor/grub-btrfs/LICENSE /usr/share/doc/polder-safeharbor/grub-btrfs.LICENSE
mkdir -p $D/etc/default/grub.d
printf '# Polder SafeHarbor: show the menu briefly so earlier versions are reachable\nGRUB_TIMEOUT=5\nGRUB_TIMEOUT_STYLE=menu\n' > $D/etc/default/grub.d/50-polder-safeharbor.cfg
inst 644 $H/xdg/polder-safeharbor-check.desktop /etc/xdg/autostart/polder-safeharbor-check.desktop
inst 644 $H/xdg/polder-safeharbor.desktop /usr/share/applications/polder-safeharbor.desktop
B=$H/../shell/polder-shelf/target/release/polder-safeharbor; [ -x "$B" ] && inst 755 "$B" /usr/bin/polder-safeharbor
echo "Polder SafeHarbor installed into ${D:-/}"
