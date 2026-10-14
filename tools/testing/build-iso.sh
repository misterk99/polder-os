#!/bin/bash
set -euo pipefail
exec 9>/work/iso-build.lock
flock -n 9 || { echo 'Another ISO build is using this architecture cache.' >&2; exit 1; }
python3 /src/tools/testing/stage-source.py /src /work/source
cd /work/source/iso
POLDER_WAYLAND=1 bash ./build.sh
case ${POLDER_ARCH:-amd64} in amd64) BUILD=build ;; arm64) BUILD=build-arm64 ;; esac
find "$BUILD" -maxdepth 1 -name '*.iso' -exec cp -v '{}' /out/ \;
sha256sum /out/*.iso > /out/SHA256SUMS
