#!/bin/bash
# Assemble a complete source package and build on Debian trixie ARM64.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
OUTPUT="$ROOT/build/packages"
KEY=
COMPONENTS=0
URL=${POLDER_REPOSITORY_URL:-https://misterk99.github.io/polder-os/apt}
usage() {
    cat <<'EOF'
Usage: build.sh [--output DIR] [--archive-keyring PUBLIC.asc]
                [--repository-url HTTPS_URL] [--components-only]
Run on Debian 13/trixie arm64, as an ordinary user, with build dependencies
installed (see debian/control). Additional tools: dpkg-dev, curl, gnupg, xz-utils.
--components-only excludes the keyring and requires no signing/trust key.
Builds never use a private key. Output includes source, .changes and .buildinfo.
Outputs are created in an empty directory; existing package artifacts are refused.
EOF
}
while (($#)); do
    case $1 in
        --output) OUTPUT=${2:?}; shift 2 ;;
        --archive-keyring) KEY=${2:?}; shift 2 ;;
        --repository-url) URL=${2:?}; shift 2 ;;
        --components-only) COMPONENTS=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
. /etc/os-release
[[ ${ID:-} == debian && ${VERSION_CODENAME:-} == trixie ]] || { echo 'Build in Debian trixie; host library builds are unsupported.' >&2; exit 2; }
[[ $(dpkg --print-architecture) == arm64 ]] || { echo 'An ARM64 Debian environment is required (native or emulated).' >&2; exit 2; }
for cmd in dpkg-buildpackage dpkg-parsechangelog curl gpg tar xz python3; do command -v "$cmd" >/dev/null; done
[[ $URL == https://* && $URL != *[$'\n\r\t ']* ]] || { echo 'Repository URL must be a single HTTPS URL.' >&2; exit 2; }
if (( ! COMPONENTS )); then
    [[ -f $KEY ]] || { echo 'Supply --archive-keyring PUBLIC.asc or use --components-only.' >&2; exit 2; }
    KEY=$(realpath "$KEY")
    grep -q '^-----BEGIN PGP PUBLIC KEY BLOCK-----$' "$KEY" || { echo 'Expected an armored public key.' >&2; exit 2; }
    ! grep -q 'PRIVATE KEY' "$KEY" || { echo 'Private key material must never enter a source package.' >&2; exit 2; }
    gpg --batch --show-keys "$KEY" >/dev/null
fi
mkdir -p "$OUTPUT"
OUTPUT=$(realpath "$OUTPUT")
[[ -z $(find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Output directory must be empty.' >&2; exit 2; }
VERSION=$(dpkg-parsechangelog -l "$ROOT/debian/changelog" -S Version)
UPSTREAM=${VERSION%-*}
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(dpkg-parsechangelog -l "$ROOT/debian/changelog" -S Timestamp)
export POLDER_COMPONENTS_ONLY=$COMPONENTS
SOURCE="$OUTPUT/polderos-$UPSTREAM"
mkdir -p "$SOURCE/.package-sources/scenefx"
# Copy the working source (including current authorized edits), not just HEAD.
tar -C "$ROOT" --exclude=__pycache__ --exclude='*.pyc' -cf - \
    config compositor iso/src tools/packages LICENSE | tar -C "$SOURCE" -xf -
# A Windows checkout may contain CRLF. Normalize copied UTF-8 text before
# creating the orig source, so quilt and installed shell shebangs work on Linux.
python3 - "$SOURCE" <<'PY'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob('*'):
    if not path.is_file():
        continue
    data = path.read_bytes()
    if b'\x00' in data or b'\r\n' not in data:
        continue
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        continue
    path.write_bytes(data.replace(b'\r\n', b'\n'))
PY
COMMIT=87c0e8b6d5c86557a800445e8e4c322f387fe19c
SHA256=8bca18dd0a082a064042ecd9b77de17cf729d398d2ba0c703bd672fb9b39c109
ARCHIVE="$OUTPUT/scenefx.tar.gz"
curl --fail --location --retry 2 "https://codeload.github.com/wlrfx/scenefx/tar.gz/$COMMIT" -o "$ARCHIVE"
printf '%s  %s\n' "$SHA256" "$ARCHIVE" | sha256sum --check
tar -xzf "$ARCHIVE" --strip-components=1 -C "$SOURCE/.package-sources/scenefx"
rm "$ARCHIVE"
tar -C "$OUTPUT" --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
    -cJf "$OUTPUT/polderos_$UPSTREAM.orig.tar.xz" "polderos-$UPSTREAM"
cp -a "$ROOT/debian" "$SOURCE/debian"
find "$SOURCE/debian" -type f -exec chmod 644 {} +
chmod 755 "$SOURCE/debian/rules"
printf 'no\n' > "$SOURCE/debian/archive-test-key"
if (( COMPONENTS )); then
    printf 'This source build intentionally excludes the archive keyring.\n' > "$SOURCE/debian/components-only"
fi
if (( ! COMPONENTS )); then
    mkdir -p "$SOURCE/debian/keyring"
    cp "$KEY" "$SOURCE/debian/keyring/polder-archive-keyring.asc"
    if [[ -f $KEY.test-only ]] || gpg --batch --show-keys --with-colons "$KEY" | grep -q 'Polder OS TEMPORARY test'; then
        printf 'yes\n' > "$SOURCE/debian/archive-test-key"
        printf 'Temporary test keyring: DO NOT PUBLISH OR INSTALL IN PRODUCTION.\n' > "$OUTPUT/TEST-ONLY"
    fi
    cat > "$SOURCE/debian/keyring/polder.sources" <<EOF
Types: deb deb-src
URIs: ${URL%/}/
Suites: trixie
Components: main
Architectures: arm64
Signed-By: /usr/share/keyrings/polder-archive-keyring.asc
EOF
fi
cd "$SOURCE"
dpkg-buildpackage --build=full --no-sign -sa
printf 'Packages and preserved source artifacts: %s\n' "$OUTPUT"
