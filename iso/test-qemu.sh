#!/bin/bash
# Boot the ISO in qemu TCG (no working KVM on this box). VNC on 127.0.0.1:5921, monitor socket iso/qemu.mon
ISO=${1:-$(ls -t $(dirname $0)/build/*.iso | head -1)}; D=$(cd $(dirname $0) && pwd)
exec timeout 3h qemu-system-x86_64 -accel tcg -cpu max -m 3072 -smp 4 -vga virtio -display vnc=127.0.0.1:21 \
  -cdrom "$ISO" -boot d -monitor unix:/tmp/qmon.sock,server,nowait -netdev user,id=n0 -device virtio-net,netdev=n0 \
  -usb -device usb-tablet
