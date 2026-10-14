#!/bin/bash
# Build a static signed Debian archive; private keys stay in the supplied home.
set -euo pipefail
PACKAGES= OUTPUT= GPG_HOME= KEY=
SUITE=trixie
ALLOW_TEST=0
usage() { echo 'Usage: repository.sh --packages DIR --output EMPTY_DIR --gpg-home DIR --signing-key FINGERPRINT [--suite trixie] [--allow-test-key]'; }
while (($#)); do
    case $1 in
        --packages) PACKAGES=${2:?}; shift 2 ;;
        --output) OUTPUT=${2:?}; shift 2 ;;
        --gpg-home) GPG_HOME=${2:?}; shift 2 ;;
        --signing-key) KEY=${2:?}; shift 2 ;;
        --suite) SUITE=${2:?}; shift 2 ;;
        --allow-test-key) ALLOW_TEST=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[[ -d $PACKAGES && -n $OUTPUT && -d $GPG_HOME && $KEY =~ ^[[:xdigit:]]{40,64}$ && $SUITE == trixie ]] || { usage >&2; exit 2; }
PACKAGES=$(realpath "$PACKAGES")
GPG_HOME=$(realpath "$GPG_HOME")
for cmd in apt-ftparchive dpkg-deb gpg dscverify gzip xz; do command -v "$cmd" >/dev/null; done
TEST=0
[[ ! -f $PACKAGES/TEST-ONLY ]] || TEST=1
shopt -s nullglob
DEBS=("$PACKAGES"/*.deb)
DSCS=("$PACKAGES"/*.dsc)
(( ${#DEBS[@]} && ${#DSCS[@]} )) || { echo 'Binary and source package artifacts are both required.' >&2; exit 2; }
for deb in "${DEBS[@]}"; do
    arch=$(dpkg-deb -f "$deb" Architecture)
    [[ $arch == arm64 || $arch == all ]] || { echo "Unsupported package architecture: $arch" >&2; exit 2; }
    [[ $(dpkg-deb -f "$deb" X-Polder-Test-Key) != yes ]] || TEST=1
    if [[ $(dpkg-deb -f "$deb" Package) == polder-archive-keyring ]]; then
        # Refuse an archive whose bootstrap package trusts a different key.
        fingerprints=$(dpkg-deb --fsys-tarfile "$deb" | tar -xOf - ./usr/share/keyrings/polder-archive-keyring.asc | \
            gpg --batch --show-keys --with-colons | awk -F: '$1=="fpr" {print $10}')
        grep -Fxiq "$KEY" <<< "$fingerprints" || { echo 'Archive keyring package does not contain the signing key.' >&2; exit 2; }
    fi
done
if gpg --homedir "$GPG_HOME" --batch --with-colons --list-keys "$KEY" | grep -q 'Polder OS TEMPORARY test'; then TEST=1; fi
(( ! TEST || ALLOW_TEST )) || { echo 'Test signing keys/keyrings are refused. Use --allow-test-key for local validation only.' >&2; exit 2; }
mkdir -p "$OUTPUT"
OUTPUT=$(realpath "$OUTPUT")
[[ -z $(find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Archive output must be empty; build separately before publishing.' >&2; exit 2; }
POOL="$OUTPUT/pool/main/p/polderos"
mkdir -p "$POOL" "$OUTPUT/dists/$SUITE/main/binary-arm64" "$OUTPUT/dists/$SUITE/main/source" "$OUTPUT/build-records"
cp "${DEBS[@]}" "$POOL/"
for dsc in "${DSCS[@]}"; do
    cp "$dsc" "$POOL/"
    # Read the Files stanza rather than guessing the names of source tarballs.
    while read -r filename; do
        [[ $filename != */* && -f $PACKAGES/$filename ]] || { echo 'Missing or unsafe .dsc source filename.' >&2; exit 2; }
        cp "$PACKAGES/$filename" "$POOL/"
    done < <(awk '/^Files:/{infiles=1; next} infiles && /^ /{print $3; next} infiles{exit}' "$dsc")
    (cd "$PACKAGES" && dscverify --nosigcheck "$dsc")
done
RECORDS=("$PACKAGES"/*.changes "$PACKAGES"/*.buildinfo)
(( ! ${#RECORDS[@]} )) || cp "${RECORDS[@]}" "$OUTPUT/build-records/"
cd "$OUTPUT"
apt-ftparchive packages pool > "dists/$SUITE/main/binary-arm64/Packages"
apt-ftparchive sources pool > "dists/$SUITE/main/source/Sources"
for index in "dists/$SUITE/main/binary-arm64/Packages" "dists/$SUITE/main/source/Sources"; do
    gzip -n -9 -c "$index" > "$index.gz"
    xz -9 -c "$index" > "$index.xz"
done
apt-ftparchive -o APT::FTPArchive::Release::Origin=PolderOS \
    -o APT::FTPArchive::Release::Label='Polder OS' \
    -o APT::FTPArchive::Release::Suite="$SUITE" \
    -o APT::FTPArchive::Release::Codename="$SUITE" \
    -o APT::FTPArchive::Release::Architectures=arm64 \
    -o APT::FTPArchive::Release::Components=main \
    -o APT::FTPArchive::Release::Description='Polder OS packages for Debian trixie' \
    release "dists/$SUITE" > "dists/$SUITE/Release"
# apt-ftparchive does not emit this field from its Release option namespace.
printf 'Valid-Until: %s\n' "$(date -u -d '+365 days' -R)" >> "dists/$SUITE/Release"
gpg --homedir "$GPG_HOME" --batch --local-user "$KEY" --digest-algo SHA256 --clearsign \
    --output "dists/$SUITE/InRelease" "dists/$SUITE/Release"
gpg --homedir "$GPG_HOME" --batch --local-user "$KEY" --digest-algo SHA256 --armor --detach-sign \
    --output "dists/$SUITE/Release.gpg" "dists/$SUITE/Release"
gpg --homedir "$GPG_HOME" --batch --armor --export "$KEY" > polder-archive-keyring.asc
[[ -s polder-archive-keyring.asc ]] || { echo 'Signing key public export failed.' >&2; exit 1; }
(( ! TEST )) || printf 'Temporary archive: DO NOT PUBLISH.\n' > TEST-ONLY
printf 'Signed APT archive: %s\n' "$OUTPUT"
