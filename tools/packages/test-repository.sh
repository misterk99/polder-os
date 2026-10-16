#!/bin/bash
# Verify archive trust, indexes, downloads and dependency resolution without root.
set -euo pipefail
REPO=
while (($#)); do
    case $1 in
        --repository) REPO=${2:?}; shift 2 ;;
        --help|-h) echo 'Usage: test-repository.sh --repository DIR (rootless; no host installation)'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ -d $REPO ]] || { echo '--repository must name a signed archive.' >&2; exit 2; }
REPO=$(realpath "$REPO")
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
chmod 755 "$WORK"
gpg --batch --dearmor --output "$WORK/keyring.gpg" "$REPO/polder-archive-keyring.asc"
gpgv --keyring "$WORK/keyring.gpg" "$REPO/dists/trixie/InRelease"
gpgv --keyring "$WORK/keyring.gpg" "$REPO/dists/trixie/Release.gpg" "$REPO/dists/trixie/Release"
mkdir -p "$WORK/lists/partial" "$WORK/cache/archives/partial" "$WORK/sources"
touch "$WORK/status"
# Debian remains a separate source so actual trixie runtime dependencies resolve.
cat > "$WORK/sources/polder.sources" <<EOF
Types: deb deb-src
URIs: file:$REPO
Suites: trixie
Components: main
Architectures: arm64
Signed-By: $WORK/keyring.gpg
EOF
cat > "$WORK/sources/debian.sources" <<EOF
Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie
Components: main
Architectures: arm64
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
APT=(-o Dir::Etc::sourcelist=- -o "Dir::Etc::sourceparts=$WORK/sources"
     -o "Dir::State::lists=$WORK/lists" -o "Dir::State::status=$WORK/status"
     -o "Dir::Cache=$WORK/cache" -o APT::Architecture=arm64
     -o APT::Architectures=arm64 -o Debug::NoLocking=1
     -o "APT::Sandbox::User=$(id -un)")
apt-get "${APT[@]}" update --error-on=any
apt-get "${APT[@]}" --simulate --no-install-recommends install polder-compositor polder-desktop polder-settings polder-shell-rs
cd "$WORK"
apt-get "${APT[@]}" download polder-compositor polder-desktop polder-settings polder-shell-rs
apt-get "${APT[@]}" source --download-only polderos
for deb in ./*.deb; do dpkg-deb --info "$deb" >/dev/null; done
echo 'PASS: trusted signed indexes, Debian runtime dependency resolution, binary and source downloads.'
