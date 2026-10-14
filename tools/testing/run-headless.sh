#!/bin/bash
set -euo pipefail
python3 /src/tools/testing/stage-source.py /src /work/source
python3 /work/source/tools/testing/test-session-settings.py
python3 /work/source/tools/testing/test-vm-probe.py
python3 /work/source/tools/testing/test-display-watchdog.py
meson setup /work/build /work/source/compositor/polder-comp -Dscenefx=disabled
meson compile -C /work/build
python3 /work/source/compositor/polder-comp/tests/headless-smoke.py \
  --compositor /work/build/polder-comp --output-dir /out
python3 /work/source/tools/testing/test-wayland-desktop.py \
  --compositor /work/build/polder-comp --output-dir /out
