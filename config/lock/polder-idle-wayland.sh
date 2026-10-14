#!/bin/sh
# The watcher applies settings changes live; idle=0 still protects suspend.
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$D/idle-wayland.py"
