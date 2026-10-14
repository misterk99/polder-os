#!/bin/bash
# Material You test session: isolated config copy + real osb-settingsd. usage: run4.sh <wallpaper> <theme>; leaves session running, env in $S/env
set -u
T=/workspace/rustshelf-test; R=/workspace/polder-os-repo; S=$T/ss
pkill -f "$S/" 2>/dev/null; [ -f $S/dbus.pid ] && kill $(cat $S/dbus.pid) 2>/dev/null; pkill -f thunar; sleep 0.5; rm -rf $S
mkdir -p $S/run $S/home/.config/osb $S/osb $S/notify; chmod 700 $S/run; cp -r $R/config $S/config
grep -rlI "/workspace/osbuilder/config\|/tmp/protohome\|/tmp/osb-notify" $S/config | xargs sed -i "s#/workspace/osbuilder/config#$S/config#g; s#/tmp/protohome#$S/home#g; s#/tmp/osb-notify#$S/notify#g"
sed -i "s#/tmp/osb-qs.pid#$S/osb/osb-qs.pid#g; s#/tmp/osb-cal.pid#$S/osb/osb-cal.pid#g" $S/config/quicksettings/qs.py
echo "{\"pinned\": [\"google-chrome.desktop\", \"foot.desktop\", \"thunar.desktop\"], \"theme\": \"$2\", \"wallpaper\": \"$1\", \"welcome_done\": true}" > $S/home/.config/osb/settings.json
eval $(dbus-daemon --session --fork --print-address=1 --print-pid=1 | { read a; read p; echo "export DBUS_SESSION_BUS_ADDRESS=$a; echo $p > $S/dbus.pid"; })
export HOME=$S/home XDG_RUNTIME_DIR=$S/run XDG_DATA_HOME=$S/home/.local/share OSB_RUNDIR=$S/osb POLDER_CONFIG=$S/config POLDER_TOPLEVELS=$T/bin/polder-toplevels OSB_NOTIFY_DIR=$S/notify
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=0 POLDER_LAUNCHER=$S/config/launcher/launcher-toggle.sh POLDER_DESKS=2 POLDER_NO_XWAYLAND=1 POLDER_KEYS=/dev/null XKB_DEFAULT_LAYOUT=us
export GSK_RENDERER=cairo GTK_A11Y=none NO_AT_BRIDGE=1 POLDER_COMP=1 POLDER_QS=rust OSB_FILES_HOME=$S/home POLDER_LAUNCHER_IMPL=${LIMPL:-rust} POLDER_NOTIFY_IMPL=${NIMPL:-rust} POLDER_CLIP_IMPL=${CIMPL:-rust} PATH=$R/shell/polder-shelf/target/release:$PATH
python3 $S/config/osb/apply.py palette > $S/apply.log 2>&1   # like start-session.sh
$T/bin/polder-comp-pixman > $S/comp.log 2>&1 &
for i in $(seq 50); do W=$(ls $S/run | grep -m1 '^wayland-[0-9]*$'); [ -n "$W" ] && break; sleep 0.2; done
export WAYLAND_DISPLAY=$W
if [ "$POLDER_NOTIFY_IMPL" = rust ]; then polder-notifyd > $S/notifyd.log 2>&1 & else python3 $S/config/notify/osb-notifyd.py > $S/notifyd.log 2>&1 & fi
python3 $S/config/osb/osb-settingsd.py > $S/settingsd.log 2>&1 &
polder-shelf > $S/shelf.log 2>&1 &
if [ "$POLDER_CLIP_IMPL" = rust ]; then polder-clipd > $S/clipd.log 2>&1 & else python3 $S/config/clip/clipd.py > $S/clipd.log 2>&1 & fi
sleep 3
export -p | grep -E "HOME|XDG_|OSB_|POLDER_|WAYLAND|DBUS|PATH=|GSK|NO_AT|GTK" > $S/env
