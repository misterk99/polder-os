# Packaging the Rust crate (`polder-shell-rs`)

All binaries of this crate ship in the Debian binary package **`polder-shell-rs`** (`Architecture: any`), built by
the regular `polderos` source package (`debian/control`, `debian/rules`, `debian/polder-shell-rs.install`):

| file | purpose |
|---|---|
| `/usr/bin/polder-sluis` | Polder Sluis app (GTK 4) |
| `/usr/bin/polder-sluisd` | Sluis service + JSON command line (`polder-sluisd --help`) |
| `/usr/bin/polder-shelf`, `polder-quicksettings`, `polder-launcher`, `polder-notifyd`, `polder-clipd`, `polder-phonehub`, `polder-dynamic-color`, `polder-safeharbor` | native shell components |
| `/usr/share/applications/polder-sluis.desktop` | app entry (from `config/sluis/`) |
| `/etc/xdg/autostart/polder-sluisd.desktop` | `polder-sluisd daemon` (single instance: the Wayland session also supervises it; a lock in `$XDG_RUNTIME_DIR` prevents doubles) |

`Depends: ${shlibs:Depends}, bubblewrap` (Sluis runs programs in bubblewrap with unprivileged user-namespace
overlayfs; fuse-overlayfs is not used). `Recommends: polder-desktop` (translations in
`/usr/share/polderos/config/locale`, session integration), `libnotify-bin`, `foot | xfce4-terminal`.
`polder-desktop` in turn recommends `polder-shell-rs`.

## Offline build from Debian crates (Debian policy: no network, no crates.io)

`Build-Depends-Arch` (all in trixie main): `cargo rustc libgtk-4-dev libgtk4-layer-shell-dev librust-gtk4-dev
librust-gtk4-layer-shell-dev librust-glib-dev librust-serde-dev librust-serde-derive-dev librust-serde-json-dev
librust-libc-dev`.
`debian/rules` writes `debian/cargo-home/config.toml` that replaces crates.io with the vendored registry
`/usr/share/cargo/registry` (`[net] offline = true`, the same mechanism dh-cargo uses) and runs
`cargo build --release --offline` into `obj-rust/`. To build by hand:

    mkdir -p /tmp/cargo-debian && cat > /tmp/cargo-debian/config.toml <<'TOML'
    [source.crates-io]
    replace-with = "debian"
    [source.debian]
    directory = "/usr/share/cargo/registry"
    [net]
    offline = true
    TOML
    CARGO_HOME=/tmp/cargo-debian cargo build --release -j2 --manifest-path shell/polder-shelf/Cargo.toml

`tools/packages/build.sh` includes `shell/polder-shelf` (without `target/`) in the orig tarball.
Tested with Rust 1.85, gtk4-rs 0.9.6, gtk4-layer-shell 0.4.0, glib 0.20.9 (trixie).

## CI (`.github/workflows/polder-packages.yml`)

* **validate** (debian:trixie, arm64): builds all packages incl. `polder-shell-rs`, signs and verifies a test archive
  (`test-repository.sh` resolves and downloads `polder-shell-rs` too) and uploads the `.deb`s.
* **sluis** (arm64 host + disposable `debian:trixie --privileged` containers, after relaxing Ubuntu's AppArmor
  restriction on unprivileged user namespaces):
  * `tools/ci/sluis-tests.sh`: builds the crate offline and runs the Sluis engine tests as an unprivileged user with
    real bubblewrap user-namespace overlayfs, in Dutch and English. Tests that need overlayfs call
    `overlay_or_skip()`; skips are written to `sluis-skips.txt` and the job summary, and CI sets
    `POLDER_SLUIS_REQUIRE_OVERLAY=1`, so a missing capability fails instead of silently skipping.
  * `tools/packages/smoke-install.sh`: clean install of the built `polder-shell-rs` on a fresh trixie, checks
    binaries, `bubblewrap`, `desktop-file-validate`, runs `polder-sluisd --help` and a CLI
    create → run → merge → rollback → discard cycle as a normal user (malicious ids refused), then starts
    `polder-sluis` on headless weston and requires it to still be running after 10 s.

## SafeHarbor system part

`polder-safeharbor` (GUI) is in `polder-shell-rs`; the system part from `safeharbor/` (`safeharbor/install.sh`, see
`docs/safeharbor.md`) is not packaged yet and suits a separate `polder-safeharbor` package with Depends: snapper,
btrfs-progs, inotify-tools, python3, polkitd, pkexec, grub-pc | grub-efi-arm64 | grub-efi-amd64, initramfs-tools.
