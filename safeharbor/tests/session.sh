#!/bin/bash
# Minimal headless Polder session for SafeHarbor screenshots
T=/workspace/rustshelf-test; R=/workspace/polder-os-repo; S=/workspace/sh-test/ss
pkill -f "$S/" 2>/dev/null; pkill -f polder-comp-pixman; pkill polder-shelf; pkill polder-notifyd; pkill polder-safeharb; sleep 0.5; rm -rf $S
mkdir -p $S/run $S/home/.config/osb $S/osb $S/notify; chmod 700 $S/run; cp -r $R/config $S/config
echo '{"theme": "light", "welcome_done": true}' > $S/home/.config/osb/settings.json
eval $(dbus-daemon --session --fork --print-address=1 --print-pid=1 | { read a; read p; echo "export DBUS_SESSION_BUS_ADDRESS=$a; echo $p > $S/dbus.pid"; })
export HOME=$S/home XDG_RUNTIME_DIR=$S/run OSB_RUNDIR=$S/osb POLDER_CONFIG=$S/config POLDER_TOPLEVELS=$T/bin/polder-toplevels OSB_NOTIFY_DIR=$S/notify
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=0 POLDER_DESKS=2 POLDER_NO_XWAYLAND=1 POLDER_KEYS=/dev/null XKB_DEFAULT_LAYOUT=us
export GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 POLDER_COMP=1 PATH=$R/shell/polder-shelf/target/release:$T/bin:$PATH
python3 $S/config/osb/apply.py palette > $S/apply.log 2>&1
$T/bin/polder-comp-pixman > $S/comp.log 2>&1 &
for i in $(seq 50); do W=$(ls $S/run | grep -m1 '^wayland-[0-9]*$'); [ -n "$W" ] && break; sleep 0.2; done
export WAYLAND_DISPLAY=$W
polder-notifyd > $S/notifyd.log 2>&1 &
polder-shelf > $S/shelf.log 2>&1 &
sleep 2
export -p | grep -E "HOME|XDG_|OSB_|POLDER_|WAYLAND|DBUS|PATH=|GSK|NO_AT|GTK" > $S/env
