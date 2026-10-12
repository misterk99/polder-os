#!/bin/bash
# runs inside the qemu guest (Polder OS live, virtio-gpu); bundle shared read/write via 9p at /mnt/pcshare
P=/mnt/pcshare/pc; O=/mnt/pcshare/out/run-$(date +%s); mkdir -p $O
export LD_LIBRARY_PATH=$P/lib LIBGL_DRIVERS_PATH=$P/lib/dri GBM_BACKENDS_PATH=$P/lib/gbm __EGL_VENDOR_LIBRARY_FILENAMES=$P/lib/50_mesa.json
export XDG_RUNTIME_DIR=/tmp/pcrt; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export WLR_RENDERER=gles2 POLDER_BG=${POLDER_BG:-#c0392b} POLDER_TERMINAL="$P/bin/foot" WLR_BACKENDS=${WLR_BACKENDS:-drm,libinput} POLDER_NO_XWAYLAND=1
$P/bin/polder-comp > $O/pc.log 2>&1 &
sleep 15; export WAYLAND_DISPLAY=wayland-0
ls -l /dev/dri > $O/dri.txt; id >> $O/dri.txt
$P/bin/foot > $O/foot.log 2>&1 & sleep 15
GDK_BACKEND=wayland thunar $P > $O/thunar.log 2>&1 & sleep 40
$P/bin/grim $O/fx.png; echo done > $O/done
