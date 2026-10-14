#!/bin/bash
# Run from Linux/WSL. Source stays read-only; all build products go to containers.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODE=${1:-headless}
ARCH=$(uname -m)
case "$ARCH" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "Unsupported host: $ARCH" >&2; exit 2 ;; esac
# Build/test binaries for the requested target. QEMU itself stays native.
TARGET_ARCH=${POLDER_ARCH:-$ARCH}
case "$TARGET_ARCH" in amd64|arm64) ;; *) echo 'POLDER_ARCH must be amd64 or arm64' >&2; exit 2 ;; esac
[ "$MODE" = vm ] || ARCH=$TARGET_ARCH
PLATFORM=linux/$ARCH
case "$ARCH" in amd64) BASE_IMAGE=amd64/debian:trixie-slim ;; arm64) BASE_IMAGE=arm64v8/debian:trixie-slim ;; esac
IMAGE=${POLDER_TEST_IMAGE:-polder-test:trixie-$ARCH}
OUT=${POLDER_TEST_OUTPUT:-"$ROOT/.polder-test/$MODE-$(date +%Y%m%d-%H%M%S)"}
case "$MODE" in headless|iso|vm) ;; *) echo 'Usage: bash tools/test-linux.sh headless|iso|vm [ISO path]' >&2; exit 2 ;; esac
mkdir -p "$OUT"
OUT=$(cd -- "$OUT" && pwd)
docker build --platform "$PLATFORM" --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$IMAGE" -f "$ROOT/tools/testing/Dockerfile" "$ROOT/tools/testing"
printf 'Test artifacts: %s\n' "$OUT"
COMMON=(--rm --platform "$PLATFORM" --mount "type=bind,src=$ROOT,dst=/src,readonly" --mount "type=bind,src=$OUT,dst=/out")
# Read entry scripts completely before launch so edits cannot change a running shell's input.
case "$MODE" in
  headless)
    docker run "${COMMON[@]}" "$IMAGE" bash -c "$(cat "$ROOT/tools/testing/run-headless.sh")" 2>&1 | tee "$OUT/run.log"
    ;;
  iso)
    # live-build needs mount/chroot. This permission is scoped to its disposable container.
    docker run "${COMMON[@]}" --privileged --cpus "${POLDER_BUILD_CPUS:-4}" --env "POLDER_ARCH=$TARGET_ARCH" \
      --mount "type=volume,src=polder-build-$TARGET_ARCH,dst=/work" \
      "$IMAGE" bash -c "$(cat "$ROOT/tools/testing/build-iso.sh")" 2>&1 | tee "$OUT/build.log"
    ;;
  vm)
    ISO=$(realpath -- "${2:?Supply the ISO path}")
    VM_ARGS=(--arch "$TARGET_ARCH" --seconds "${POLDER_VM_SECONDS:-600}")
    [ "${POLDER_VM_DIRECT_KERNEL:-0}" != 1 ] || VM_ARGS+=(--direct-kernel)
    [ "${POLDER_VM_PROBE_SESSION:-0}" != 1 ] || VM_ARGS+=(--probe-session)
    [ "${POLDER_VM_EXERCISE_SHELL:-0}" != 1 ] || VM_ARGS+=(--exercise-shell)
    docker run "${COMMON[@]}" --mount "type=bind,src=$ISO,dst=/image.iso,readonly" \
      "$IMAGE" python3 /src/tools/testing/vm-smoke.py --iso /image.iso --output /out "${VM_ARGS[@]}" \
      2>&1 | tee "$OUT/run.log"
    ;;
esac
