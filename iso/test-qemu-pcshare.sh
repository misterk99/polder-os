#!/bin/bash
# Rev 32c: boot the ISO with virtio-gpu + a 9p share of compositor/vmbundle (mount tag pcshare) to run polder-comp/scenefx on GLES2
D=$(cd $(dirname $0) && pwd); ISO=${1:-$(ls -t $D/build/*.iso | head -1)}
exec timeout 3h qemu-system-x86_64 -accel tcg -cpu max -m 4096 -smp 4 -vga virtio -display vnc=127.0.0.1:21 \
  -cdrom "$ISO" -boot d -monitor unix:/tmp/qmon.sock,server,nowait -usb -device usb-tablet \
  -virtfs local,path=$D/../compositor/vmbundle,mount_tag=pcshare,security_model=none,id=pcs
