# Debian packages and signed archive

Use Debian 13/trixie ARM64, either natively or in an ARM64 container. The package
builder itself needs no root privileges. Install the build tools as administrator
once, then run the commands below as an ordinary user:

```sh
sudo apt-get update
sudo apt-get install build-essential debhelper dpkg-dev meson ninja-build pkgconf \
  python3 libwlroots-0.18-dev libwayland-dev wayland-protocols libxkbcommon-dev \
  libxcb1-dev libdrm-dev libpixman-1-dev libegl-dev libgles-dev libgbm-dev \
  curl ca-certificates gnupg xz-utils apt-utils devscripts
bash tools/packages/build.sh --components-only --output build/components
```

Use a Linux filesystem for the output directory. With a Windows bind mount in
Docker, set `--output /home/your-build-user/packages` inside the container and
copy the final artifacts out afterwards; Windows filesystem timestamps can cause
Meson clock-skew failures.

This emits `polder-compositor` (arm64), `polder-desktop` and `polder-settings`
(all), alongside `.dsc`, `.orig.tar.xz`, `.debian.tar.xz`, `.changes` and
`.buildinfo`. The unpacked source, including `debian/` and a pinned, verified
SceneFX source archive, remains in the output directory. `debian/changelog`
owns the version. Every output directory must be empty before running a builder.
Debhelper also emits the compositor's standard `-dbgsym` package.
Component-only sources include a marker so rebuilding their `.dsc` preserves
the intentional exclusion of the archive keyring.

To build the fourth package, provide the production **public** key export and
the archive's actual HTTPS URL:

```sh
bash tools/packages/build.sh --output build/packages \
  --archive-keyring /safe/public/polder-archive-keyring.asc \
  --repository-url https://your-approved-host.example/apt
bash tools/packages/repository.sh --packages build/packages \
  --output build/repository --gpg-home /safe/private/gnupg \
  --signing-key YOUR_FULL_SIGNING_KEY_FINGERPRINT
bash tools/packages/test-repository.sh --repository build/repository
```

`POLDER_REPOSITORY_URL` can supply the default URL; otherwise it defaults to
`https://misterk99.github.io/polder-os/apt`. Configure the approved host before
publishing. The keyring package installs an armored public key in
`/usr/share/keyrings/` and a Deb822 source with `Signed-By`; Debian sources stay
available. Signing reads the supplied GPG home and never copies it into the
archive. Use a pre-unlocked GPG agent for protected signing keys. Keep private
keys outside the repository and all build output.

The static output contains `pool/main/p/polderos/`,
`dists/trixie/main/binary-arm64/Packages{,.gz,.xz}`,
`dists/trixie/main/source/Sources{,.gz,.xz}`, `Release`, `InRelease`,
`Release.gpg`, an exported public key and `build-records/` with `.changes` and
`.buildinfo`. Publish the whole output atomically over HTTPS. Release metadata
expires after 365 days; regenerate and sign it before expiry, even when package
versions have not changed. Keep previous package versions available when
updating an existing public archive; do not remove payloads referenced by
clients' still-cached indexes.

For a disposable local/CI archive:

```sh
bash tools/packages/test-key.sh --output build/test-key
bash tools/packages/build.sh --output build/test-packages \
  --archive-keyring build/test-key/polder-archive-keyring.asc
bash tools/packages/repository.sh --packages build/test-packages \
  --output build/test-repository --gpg-home build/test-key/gpg-home \
  --signing-key "$(cat build/test-key/fingerprint.txt)" --allow-test-key
bash tools/packages/test-repository.sh --repository build/test-repository
```

The helper produces `gpg-home/`, `polder-archive-keyring.asc`,
`polder-archive-keyring.asc.test-only`, `fingerprint.txt`, and `TEST-ONLY`.
Test-keyring packages carry `X-Polder-Test-Key: yes`, and their build/archive
directories carry `TEST-ONLY`. The archive builder refuses them unless explicitly
passed `--allow-test-key`. Never publish these archives or put the test keyring
in an ISO. Use `--components-only` for ISO builds without a production trust key.

The repository test uses temporary APT lists, cache and status. It verifies both
signatures, fetches trusted indexes, resolves installation against Debian
trixie with an empty simulated installed system, and downloads both binaries
and source. It never installs packages into the host. Run an actual installation
only in a disposable container/VM for integration validation.

SceneFX 0.2.1 is built from commit
`87c0e8b6d5c86557a800445e8e4c322f387fe19c`, whose archive SHA256 is pinned in
`build.sh`. It receives an explicit ABI SONAME via a Debian patch and installs
inside `/usr/lib/aarch64-linux-gnu/polderos/`, owned by `polder-compositor`.
The effects executable has that installed RUNPATH; Debian's library packages
provide all other runtime dependencies. The plain binary keeps the software
renderer fallback. No host libraries or Meson fallback subprojects are bundled.

Settings retains the shared modules supplied by `polder-desktop`, and depends on
the identical package version. Desktop recommends that same settings version,
avoiding a dependency cycle. Release settings changes with a new changelog
version; this upgrades the desktop's `VERSION` and configuration hash together,
refreshing both session types' per-user configuration on their next login.
The patched capture portal remains an ISO integration feature, outside these
packages. This archive supplies Debian's standard portal as its dependency.
The desktop adds `52polderos-unattended-upgrades` for the signed `PolderOS`
origin and `Polder OS` label, preserving Debian's existing unattended-upgrades
settings and sources.
