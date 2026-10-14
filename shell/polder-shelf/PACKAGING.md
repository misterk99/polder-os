# Building polder-shelf on Debian 13 (trixie), offline from Debian's crate packages

Build deps (all in trixie main, amd64 and arm64):

    apt install cargo rustc libgtk-4-dev libgtk4-layer-shell-dev \
        librust-gtk4-dev librust-gtk4-layer-shell-dev librust-serde-json-dev librust-libc-dev

Use the vendored Debian registry instead of crates.io (this is what dh-cargo does):

    mkdir -p /tmp/cargo-debian && cat > /tmp/cargo-debian/config.toml <<'TOML'
    [source.crates-io]
    replace-with = "debian"
    [source.debian]
    directory = "/usr/share/cargo/registry"
    [net]
    offline = true
    TOML
    CARGO_HOME=/tmp/cargo-debian cargo build --release --manifest-path shell/polder-shelf/Cargo.toml

Runtime deps: libgtk-4-1, libgtk4-layer-shell0, polder-toplevels (polder-compositor package), python3 for the
helpers it launches (launcher, calendar, quick settings, weather, capture).

Planned packaging (NOT yet in debian/control, so the current CI is unchanged): a new binary package
`polder-shelf` with `Build-Depends: dh-cargo` plus the list above, installing `target/release/polder-shelf` and `target/release/polder-quicksettings` to
`/usr/bin/`. Once that exists, the session picks it up when `POLDER_SHELF=rust` is set.
Tested: Rust 1.85 / gtk4-rs 0.9.6 / gtk4-layer-shell 0.4.0 on x86_64; arm64 not yet built.
