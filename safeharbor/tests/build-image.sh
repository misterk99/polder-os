#!/bin/bash
# Build the SafeHarbor test VM disk (amd64, BIOS GRUB) the way it was tested on 2026-10-15.
# Needs: debootstrap, btrfs-progs >= 6.x (mkfs.btrfs --rootdir --subvol), gdisk, sudo. No btrfs kernel module needed on
# the build host: the filesystem is made in userspace and GRUB is installed from inside the VM (first boot: vm.sh direct).
set -e
W=${W:-/workspace/sh-test}; R=$(cd "$(dirname "$0")/../.." && pwd); U=5a1e4a7b-0c1d-4e2f-9a3b-70d3e5afe001
mkdir -p $W && cd $W && echo $U > uuid
[ -f key ] || ssh-keygen -q -t ed25519 -N '' -f key
# polkitd needs a system bus + logind at configure time: not in --include, installed afterwards
sudo debootstrap --variant=minbase --include=linux-image-amd64,grub-pc,btrfs-progs,snapper,inotify-tools,openssh-server,sudo,initramfs-tools,systemd-sysv,udev,dbus,libpam-systemd,apt-utils,unattended-upgrades,nano,less,curl,iproute2,ifupdown,isc-dhcp-client,kmod,python3,gawk,libnotify-bin,gpgv trixie root http://deb.debian.org/debian
sudo cp /etc/resolv.conf root/etc/; for m in proc sys dev; do sudo mount --bind /$m root/$m; done
sudo chroot root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq polkitd pkexec
sudo tee root/etc/fstab >/dev/null <<F
UUID=$U /            btrfs subvol=@,compress=zstd:1        0 0
UUID=$U /home        btrfs subvol=@home,compress=zstd:1    0 0
UUID=$U /.snapshots  btrfs subvol=@snapshots,compress=zstd:1 0 0
UUID=$U /var/log     btrfs subvol=@var_log,compress=zstd:1 0 0
UUID=$U /var/cache   btrfs subvol=@cache,compress=zstd:1   0 0
F
echo polder-test | sudo tee root/etc/hostname >/dev/null
printf 'auto lo\niface lo inet loopback\nallow-hotplug eth0\niface eth0 inet dhcp\n' | sudo tee root/etc/network/interfaces >/dev/null
sudo mkdir -p root/root/.ssh && sudo cp key.pub root/root/.ssh/authorized_keys
sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=ttyS0,115200 net.ifnames=0"/' root/etc/default/grub
printf 'GRUB_TERMINAL="console serial"\nGRUB_SERIAL_COMMAND="serial --speed=115200"\nGRUB_DISABLE_OS_PROBER=true\n' | sudo tee -a root/etc/default/grub >/dev/null
sudo bash $R/safeharbor/install.sh $W/root
sudo chroot root bash -c 'useradd -m -s /bin/bash -G sudo gebruiker; mkdir -p /.snapshots; ln -sf /usr/share/zoneinfo/Europe/Amsterdam /etc/localtime; update-initramfs -u -k all'
for m in dev sys proc; do sudo umount root/$m; done; echo "nameserver 10.0.2.3" | sudo tee root/etc/resolv.conf >/dev/null
sudo cp root/boot/vmlinuz-* vmlinuz; sudo cp root/boot/initrd.img-* initrd; sudo chown $USER vmlinuz initrd
# flat subvolume layout
sudo mkdir -p stage && sudo mv root stage/@ && cd stage && sudo mkdir -p @home @snapshots @var_log @cache
sudo bash -c 'shopt -s dotglob; mv @/home/* @home/ 2>/dev/null; mv @/var/log/* @var_log/; mv @/var/cache/* @cache/; rm -f @cache/apt/archives/*.deb'
cd $W && rm -f disk.img && truncate -s 8G disk.img && sgdisk -n1:2048:6143 -t1:EF02 -n2:6144:0 -t2:8300 disk.img >/dev/null
E=$(sgdisk -i2 disk.img | awk '/Last sector/{print $3}'); truncate -s $(( (E-6144+1)*512 )) part.img
sudo mkfs.btrfs -q -U $U -L polder --rootdir stage --subvol rw:@ --subvol rw:@home --subvol rw:@snapshots --subvol rw:@var_log --subvol rw:@cache part.img
dd if=part.img of=disk.img bs=1M seek=3 conv=notrunc,sparse status=none && rm part.img
echo "Next: ./vm.sh direct, then in the VM: grub-install /dev/vda && update-grub; reboot via ./vm.sh (GRUB)."
