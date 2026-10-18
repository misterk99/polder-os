#!/bin/bash
# Build the Rust crate and run the Polder Sluis engine tests on Debian trixie, offline against Debian's crate
# packages, as an unprivileged user with bubblewrap user-namespace overlayfs (the same mechanism users get).
# Run as root in a disposable trixie container started with --privileged on a host that allows unprivileged user
# namespaces (see .github/workflows/polder-packages.yml). Environment-based skips are recorded in $SKIP_LOG; with
# POLDER_SLUIS_REQUIRE_OVERLAY=1 (the default here) a missing capability fails the run instead of skipping.
set -euo pipefail
SRC=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${WORK:-/work}
SKIP_LOG=${SKIP_LOG:-$WORK/sluis-skips.txt}
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates cargo rustc pkgconf python3 libgtk-4-dev libgtk4-layer-shell-dev \
    librust-gtk4-dev librust-gtk4-layer-shell-dev librust-glib-dev librust-serde-dev librust-serde-derive-dev \
    librust-serde-json-dev librust-libc-dev bubblewrap
install -d -o nobody -g nogroup "$WORK/home" "$WORK/tmp" "$WORK/cargo" "$WORK/target"
: > "$SKIP_LOG"; chown nobody:nogroup "$SKIP_LOG"
cat > "$WORK/cargo/config.toml" <<'TOML'
[source.crates-io]
replace-with = "debian"
[source.debian]
directory = "/usr/share/cargo/registry"
[net]
offline = true
TOML
# a private, writable copy of the crate (the checkout is owned by another uid)
rm -rf "$WORK/crate"; mkdir -p "$WORK/crate/shell" "$WORK/crate/config"
cp -a "$SRC/shell/polder-shelf" "$WORK/crate/shell/"; rm -rf "$WORK/crate/shell/polder-shelf/target"
cp -a "$SRC/config/locale" "$WORK/crate/config/"
chown -R nobody:nogroup "$WORK/crate"
as_user() { runuser -u nobody -- env HOME="$WORK/home" TMPDIR="$WORK/tmp" CARGO_HOME="$WORK/cargo" CARGO_TARGET_DIR="$WORK/target" \
    POLDER_SLUIS_REQUIRE_OVERLAY="${POLDER_SLUIS_REQUIRE_OVERLAY:-1}" POLDER_SLUIS_SKIP_LOG="$SKIP_LOG" "$@"; }
cd "$WORK/crate/shell/polder-shelf"
echo "kernel: $(uname -r); unprivileged_userns_clone=$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo n/a)"
as_user cargo build --release --offline -j2 --bins
as_user cargo test --release --offline -j2 --bin polder-sluisd -- --test-threads=2
as_user env POLDER_LANG=en cargo test --release --offline -j2 --bin polder-sluisd -- --test-threads=2
as_user cargo test --release --offline -j2 --bin polder-sluis -- --test-threads=2
as_user env POLDER_SLUISD="$WORK/target/release/polder-sluisd" python3 "$SRC/tools/testing/test-sluis-cli.py"
if [[ -s $SKIP_LOG ]]; then echo "Skipped (environment):"; cat "$SKIP_LOG"; else echo "Skipped (environment): none"; fi
