# Polder packages and APT archive

Polder keeps Debian's trixie sources enabled and adds a separate signed Polder
archive. The archive currently targets ARM64. The compositor is an `arm64`
package; the desktop and settings payloads are `all` packages. One source
package version in `debian/changelog` controls the three application package
versions and refreshes both X11 and Wayland per-user configuration on next
login. This overlay model follows Debian's
[derivative repository guidance](https://wiki.debian.org/Derivatives/Guidelines#Repositories).

The package set is `polder-compositor`, `polder-desktop`,
`polder-settings`, and `polder-archive-keyring`. The keyring package contains
only the public archive key and the Polder Deb822 source entry, scoped with
`Signed-By`, as described in
[apt-secure](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html#REPOSITORY_CONFIGURATION).
Debian mirrors and their keys remain managed by Debian. The
archive signs `InRelease` and `Release.gpg`; clients verify those metadata
signatures and the package checksums through APT.

The patched `xdg-desktop-portal-wlr` build remains an ISO hook and is not part
of this initial package set. Portal-backend changes therefore still need a
separate packaging change before they can ship through the Polder archive.

## Build and test locally

Build on Debian 13/trixie ARM64, natively or in an ARM64 VM. Install the
build-dependencies listed in `debian/control` plus `devscripts`, `fakeroot`,
`dpkg-dev`, `curl`, `gnupg`, `xz-utils`, and `apt-utils`. The package builder
refuses other distributions and architectures to avoid copying host libraries
into the compositor packages.

To exercise the full signed archive without a production key, create a
disposable key and build into separate empty directories:

```sh
tools/packages/test-key.sh --output build/test-keys/local
tools/packages/build.sh \
  --output build/packages/local \
  --archive-keyring build/test-keys/local/polder-archive-keyring.asc
tools/packages/repository.sh \
  --packages build/packages/local \
  --output build/repository/local \
  --gpg-home build/test-keys/local/gpg-home \
  --signing-key "$(cat build/test-keys/local/fingerprint.txt)" \
  --allow-test-key
tools/packages/test-repository.sh --repository build/repository/local
```

The verification command checks the signed indexes with APT, resolves package
dependencies while retaining Debian as a separate source, and downloads both
binary and source packages. Test archives and their keys are explicitly marked
`TEST-ONLY`; never publish or install them on a production system.

For a local ARM64 Wayland ISO, `tools/testing/build-iso.sh` builds only the
three application packages without a key and gives them to live-build as local
`.deb` files. The ISO does not trust a disposable key. The existing amd64 ISO
build path remains unchanged. A local `.deb` install tests package payload and
build integration; it does not test APT repository authentication, which is
why the separate signed-archive check is required. This local package path uses
live-build's documented [custom-package support](https://live-team.pages.debian.net/live-manual/html/live-manual/customizing-package-installation.en.html).

To make a production ARM64 ISO bootstrap the production archive, build the full
package set with the production **public** key into the default
`build/packages/` directory, then run the ARM64 ISO build. The ISO builder
includes the keyring package only when present and rejects packages marked
`TEST-ONLY`. For example, on an ARM64 Debian build host:

```sh
tools/packages/build.sh --archive-keyring /safe/public/polder-archive-keyring.asc
sudo env POLDER_ARCH=arm64 POLDER_WAYLAND=1 bash iso/build.sh
```

Do not embed a private signing key in an ISO.

## Updating an installed system

On an installed system, `polder-archive-keyring` must first be installed from a
trusted channel, such as a Polder ISO or a separately verified package. Then
APT can authenticate the Polder source using
`/usr/share/keyrings/polder-archive-keyring.asc`. Debian sources are left in
place. Once a production archive is published, the existing package updater can
offer Polder package upgrades; the desktop package opts the Polder archive into
the existing nightly unattended-upgrades policy while retaining Debian's
current update rules. Settings and desktop files refresh in each user profile
at the next login, and user settings remain in their existing home-directory
files.

## Production publishing

Desktop updates also install automatic Store catalog setup. The desktop package
enables Debian app-icon indexes and a metadata-only systemd refresh timer for
Debian and the native-architecture Flathub catalog. Fresh ISO builds preload the
same data. When a catalog is still missing or the network is offline, the Store
keeps cached apps usable, shows setup/retry status, and reloads the catalog after
the background refresh finishes. Users do not need to run setup commands.


The `Polder packages` GitHub Actions workflow validates a disposable-key
archive on ARM64 for pull requests and pushes to `main`. It has a separate
manual publishing path, restricted to `main` and an explicit `publish: true`
dispatch. For a new deployment or fork, configure these prerequisites first:

1. Configure GitHub Pages to use GitHub Actions for `misterk99/polder-os`.
2. Add a dedicated, unprotected OpenPGP signing-only private key as the Actions
   secret `POLDER_REPO_SIGNING_KEY`. The ephemeral runner needs a noninteractive
   signing key; keep its public counterpart available for ISO/bootstrap builds.
   Never commit a private key or put it in an ISO.
3. Review the publishing workflow and GitHub Pages deployment permissions.

The publisher builds the keyring package against the public key exported from
that signing secret, signs the archive metadata, verifies the signed archive,
and deploys it under `/apt/`. Its configured URI is
`https://misterk99.github.io/polder-os/apt/`. The workflow does not publish on
ordinary pushes. For this repository, Pages and the `POLDER_REPO_SIGNING_KEY`
secret are configured. The archive becomes available after the package workflow
is on `main` and a maintainer manually runs **Polder packages** from Actions with
`publish: true`.

For key rotation, publish an overlapping public key in `polder-archive-keyring`
before signing with the replacement key, so installed clients can authenticate
the transition. Never use `trusted=yes`, `apt-key`, or APT's insecure-repository
options.
