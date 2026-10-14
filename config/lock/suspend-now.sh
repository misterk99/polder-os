#!/bin/sh
# Explicit suspend must never proceed when the session could not be secured.
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo 'Suspend requires a Wayland session with acknowledged locking.' >&2
  exit 1
fi
"$D/lock-now.sh" -f
exec systemctl suspend
