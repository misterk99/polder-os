#!/bin/bash
# Launch Thunar as "Files" in the prototype, isolated HOME/config and own dbus (doesn't touch host xfconf)
export HOME="/tmp/osb-files/Mijn bestanden" XDG_CONFIG_HOME=/tmp/protohome/.config XDG_DATA_HOME=/tmp/protohome/.local/share DISPLAY=${DISPLAY:-:55}
mkdir -p "$XDG_CONFIG_HOME/Thunar"; cp /workspace/osbuilder/config/files/uca.xml "$XDG_CONFIG_HOME/Thunar/"
exec dbus-run-session -- thunar "${1:-$HOME/Downloads}"
