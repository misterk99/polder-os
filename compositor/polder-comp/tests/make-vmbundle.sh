#!/bin/bash
# Rev 32c: bundle the scenefx build + mesa (llvmpipe/kms_swrast) + foot/grim into compositor/vmbundle, shared into the
# qemu guest via 9p (iso/test-qemu-pcshare.sh). Inside the guest (tty2): sudo mount -t 9p -o trans=virtio,version=9p2000.L
# pcshare /mnt/pcshare && bash /mnt/pcshare/pc/run.sh   (DRM backend + GLES2 renderer; grim result in out/run-*/fx.png)
set -e
H=$(cd $(dirname $0)/.. && pwd); B=$H/../vmbundle; L=/usr/lib/x86_64-linux-gnu
mkdir -p $B/pc/lib/dri $B/pc/lib/gbm $B/pc/bin $B/out; cd $B/pc
cp $H/build-fx/polder-comp bin/; cp /usr/bin/foot /usr/bin/grim /usr/bin/wtype bin/
cp $L/dri/{kms_swrast_dri.so,swrast_dri.so,virtio_gpu_dri.so,libdril_dri.so} lib/dri/; cp $L/gbm/dri_gbm.so lib/gbm/; cp $L/libEGL_mesa.so.0 lib/
export LD_LIBRARY_PATH=$H/../scenefx-install/lib/x86_64-linux-gnu
for f in bin/* lib/dri/*.so lib/gbm/*.so lib/libEGL_mesa.so.0 $L/libgallium-*.so; do ldd $f | awk '$3 ~ /^\// {print $3}'; done | sort -u \
  | grep -vE "/(libc|libm|libpthread|libdl|librt|libudev|libsystemd)\.so" | while read l; do cp -L $l lib/; done
cp -L $L/libgallium-*.so lib/
echo '{ "file_format_version" : "1.0.0", "ICD" : { "library_path" : "/mnt/pcshare/pc/lib/libEGL_mesa.so.0" } }' > lib/50_mesa.json
cp $H/tests/qemu-guest-run.sh run.sh; chmod +x run.sh; du -sh $B
