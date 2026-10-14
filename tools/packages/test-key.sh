#!/bin/bash
# Disposable local trust root, never a production key.
set -euo pipefail
OUTPUT=
while (($#)); do
    case $1 in
        --output) OUTPUT=${2:?}; shift 2 ;;
        --help|-h) echo 'Usage: test-key.sh --output EMPTY_DIRECTORY'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ -n $OUTPUT ]] || { echo '--output is required.' >&2; exit 2; }
mkdir -p "$OUTPUT"
OUTPUT=$(realpath "$OUTPUT")
[[ -z $(find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Output directory must be empty.' >&2; exit 2; }
mkdir -m700 "$OUTPUT/gpg-home"
gpg --homedir "$OUTPUT/gpg-home" --batch --pinentry-mode loopback --passphrase '' \
    --quick-generate-key 'Polder OS TEMPORARY test archive <test@polderos.invalid>' ed25519 sign 1d
FINGERPRINT=$(gpg --homedir "$OUTPUT/gpg-home" --batch --with-colons --list-keys | awk -F: '$1=="fpr" {print $10; exit}')
gpg --homedir "$OUTPUT/gpg-home" --batch --armor --export "$FINGERPRINT" > "$OUTPUT/polder-archive-keyring.asc"
printf '%s\n' "$FINGERPRINT" > "$OUTPUT/fingerprint.txt"
printf 'DO NOT PUBLISH\n' > "$OUTPUT/polder-archive-keyring.asc.test-only"
printf 'DO NOT PUBLISH\n' > "$OUTPUT/TEST-ONLY"
printf '%s\n' "$FINGERPRINT"
