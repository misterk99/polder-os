#!/bin/bash
# vm.sh [direct]  — 1 GB, KVM, serial -> serial.log, QMP on qmp.sock, ssh on localhost:2222
cd ${W:-/workspace/sh-test}
K=()
[ "$1" = direct ] && K=(-kernel vmlinuz -initrd initrd -append "root=UUID=$(cat uuid) rootflags=subvol=@ ro console=ttyS0,115200 net.ifnames=0")
exec qemu-system-x86_64 -enable-kvm -m 1024 -smp 2 -drive file=disk.img,format=raw,if=virtio \
  -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:2222-:22 -vga std -display none \
  -serial file:serial.log -qmp unix:qmp.sock,server,nowait "${K[@]}"
