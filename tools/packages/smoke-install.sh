#!/bin/bash
# Clean-install smoke test of the polder-shell-rs package on Debian trixie: install the built .deb into a fresh
# system, check binaries/desktop entries/dependencies, drive a CLI create -> run -> merge -> rollback -> discard
# cycle as an ordinary user, and launch the Sluis GUI on a headless Wayland compositor (weston).
# Run as root in a disposable debian:trixie container (--privileged, /home on tmpfs, unprivileged user namespaces
# allowed by the host). Usage: smoke-install.sh PACKAGES_DIR
set -euo pipefail
DIR=$(realpath "${1:?Usage: smoke-install.sh PACKAGES_DIR}")
REQUIRE=${POLDER_SLUIS_REQUIRE_OVERLAY:-1}
SKIPS=()
export DEBIAN_FRONTEND=noninteractive
apt-get update
DEBS=("$DIR"/polder-shell-rs_*.deb); [[ -f ${DEBS[0]} ]] || { echo "no polder-shell-rs .deb in $DIR" >&2; exit 2; }
apt-get install -y --no-install-recommends "${DEBS[@]}"
for b in polder-shelf polder-quicksettings polder-phonehub polder-dynamic-color polder-launcher polder-notifyd polder-clipd polder-safeharbor polder-sluis polder-sluisd; do
    test -x "/usr/bin/$b" || { echo "missing /usr/bin/$b" >&2; exit 1; }
done
dpkg -s bubblewrap | grep -q '^Status: install ok installed'
apt-get install -y --no-install-recommends desktop-file-utils weston
desktop-file-validate /usr/share/applications/polder-sluis.desktop /etc/xdg/autostart/polder-sluisd.desktop
id smoke >/dev/null 2>&1 || useradd -m -s /bin/sh smoke
install -d -o smoke -m 700 /tmp/smoke-xdg
as() { runuser -u smoke -- env HOME=/home/smoke XDG_RUNTIME_DIR=/tmp/smoke-xdg PATH=/usr/bin:/bin "$@"; }
getid() { sed -n 's/.*"meta":{[^}]*"id":"\([a-z0-9-]*\)".*/\1/p'; }

as polder-sluisd --help | grep -q 'create <naam> <map>'
as mkdir -p /home/smoke/proj; as sh -c 'echo oud > /home/smoke/proj/f'
ID=$(as polder-sluisd create 'Rook test' /home/smoke/proj | getid); [[ $ID == rook-test ]] || { echo "unexpected id '$ID'" >&2; exit 1; }
as polder-sluisd list | grep -q '"id":"rook-test"'
for bad in ../../etc /etc . .. 'a/b'; do if as polder-sluisd discard "$bad" >/dev/null; then echo "discard accepted '$bad'" >&2; exit 1; fi; done
if as polder-sluisd run "$ID" -- sh -c 'echo nieuw > f'; then
    as polder-sluisd changes "$ID" | grep -q '"path":"f"'
    grep -qx oud /home/smoke/proj/f                                   # mainland untouched until merged
    as polder-sluisd merge "$ID" f | grep -q '"ok":true'; grep -qx nieuw /home/smoke/proj/f
    as polder-sluisd rollback "$ID" "$(ls /home/smoke/.local/share/polder-sluis/polders/$ID/journal | tail -1)" | grep -q '"rolled_back":true'
    grep -qx oud /home/smoke/proj/f
else
    [[ $REQUIRE != 1 ]] || { echo 'polder-sluisd run failed: user-namespace overlayfs unavailable' >&2; exit 1; }
    SKIPS+=("cli run/merge/rollback: bubblewrap user-namespace overlayfs unavailable")
fi
as polder-sluisd discard "$ID" | grep -q '"ok":true'
[[ $(as polder-sluisd list) == '[]' ]]

# GUI launch: the window must still be running after 10 s on a headless compositor
as weston --backend=headless --renderer=pixman --socket=wayland-smoke --idle-time=0 >/tmp/weston.log 2>&1 &
WPID=$!
for _ in $(seq 50); do [[ -S /tmp/smoke-xdg/wayland-smoke ]] && break; sleep 0.2; done
[[ -S /tmp/smoke-xdg/wayland-smoke ]] || { cat /tmp/weston.log; echo 'weston did not start' >&2; exit 1; }
set +e
as env WAYLAND_DISPLAY=wayland-smoke GSK_RENDERER=cairo timeout 10 polder-sluis >/tmp/gui.log 2>&1; rc=$?
set -e
kill "$WPID" 2>/dev/null || true
cat /tmp/gui.log
[[ $rc == 124 ]] || { echo "polder-sluis exited early (rc=$rc)" >&2; exit 1; }
echo "PASS: clean install, CLI cycle, GUI launch (headless weston)"
if ((${#SKIPS[@]})); then printf 'SKIPPED: %s\n' "${SKIPS[@]}"; else echo 'SKIPPED: none'; fi
