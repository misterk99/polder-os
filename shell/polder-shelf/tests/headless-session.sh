#!/bin/bash
# Clean QS test session: own dbus, own notify daemon + dir, own settings. usage: run2.sh <rust|python> <out>
set -u
T=/workspace/rustshelf-test; R=/workspace/polder-os-repo; KIND=$1; OUT=$2
S=$T/q-$KIND; pkill -f "$S/" 2>/dev/null; [ -f $S/dbus.pid ] && kill $(cat $S/dbus.pid) 2>/dev/null; sleep 0.5; rm -rf $S
mkdir -p $S/run $S/home/.config/osb $S/osb $S/notify; chmod 700 $S/run; cp -r $R/config $S/config
grep -rl "/tmp/osb-notify" $S/config | xargs sed -i "s#/tmp/osb-notify#$S/notify#g"
sed -i "s#/tmp/osb-qs.pid#$S/osb/osb-qs.pid#g; s#/tmp/osb-cal.pid#$S/osb/osb-cal.pid#g" $S/config/quicksettings/qs.py
echo '{"pinned": ["google-chrome.desktop", "foot.desktop", "thunar.desktop"], "theme": "light"}' > $S/home/.config/osb/settings.json
eval $(dbus-daemon --session --fork --print-address=1 --print-pid=1 | { read a; read p; echo "export DBUS_SESSION_BUS_ADDRESS=$a; echo $p > $S/dbus.pid"; })
export HOME=$S/home XDG_RUNTIME_DIR=$S/run OSB_RUNDIR=$S/osb POLDER_CONFIG=$S/config POLDER_TOPLEVELS=$T/bin/polder-toplevels OSB_NOTIFY_DIR=$S/notify
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=0 POLDER_LAUNCHER=true POLDER_DESKS=2 POLDER_NO_XWAYLAND=1 POLDER_KEYS=/dev/null XKB_DEFAULT_LAYOUT=us
export GTK_THEME=Adwaita GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 POLDER_COMP=1 POLDER_QS=$KIND PATH=$R/shell/polder-shelf/target/release:$PATH
$T/bin/polder-comp-pixman > $S/comp.log 2>&1 &
for i in $(seq 50); do W=$(ls $S/run | grep -m1 '^wayland-[0-9]*$'); [ -n "$W" ] && break; sleep 0.2; done
export WAYLAND_DISPLAY=$W
python3 $S/config/notify/osb-notifyd.py > $S/notifyd.log 2>&1 &
sleep 2
notify-send -a Bestanden -i system-file-manager-symbolic "Download voltooid" "rapport-2026.pdf staat in Downloads"
notify-send -a Systeem "Updates" "Alles is bijgewerkt"
if [ $KIND = rust ]; then polder-shelf > $S/shelf.log 2>&1 & else python3 $S/config/shelf/shelf.py > $S/shelf.log 2>&1 & fi
sleep 3
foot -a foot -T Terminal -o colors.background=203040 > /dev/null 2>&1 &
sleep 2
export -p | grep -E "HOME|XDG_RUNTIME|OSB_|POLDER_|WAYLAND|DBUS|PATH=|GTK|GSK|NO_AT" > $S/env
grim $T/$OUT.png
