#!/bin/bash
# Starts the ChromeOS-style prototype on a separate display (default :55). Idempotent after reboot
# (recreates everything that lived in /tmp).
D=${1:-:55}; C=/workspace/osbuilder/config
Xvfb $D -screen 0 1366x768x24 +extension RANDR >/tmp/proto-xvfb.log 2>&1 &
sleep 1; export DISPLAY=$D
# isolated config dir + own dbus so the host desktop (:1) is untouched
export XDG_CONFIG_HOME=/tmp/protohome/.config; X=$XDG_CONFIG_HOME
mkdir -p $X/gtk-3.0 $X/xfce4/xfconf/xfce-perchannel-xml $X/Thunar
cp $C/gtkrc-settings.ini $X/gtk-3.0/settings.ini
# Revision 12: packages that may vanish after a reboot (ICS parsing for Agenda)
python3 -c "import icalendar, recurring_ical_events" 2>/dev/null || sudo -n apt-get install -y python3-icalendar python3-recurring-ical-events >/tmp/osb-apt.log 2>&1
# Revision 16: lock screen (PAM) + greeter bindings
python3 -c "import pam" 2>/dev/null || sudo -n apt-get install -y --no-install-recommends python3-pampy gir1.2-lightdm-1 >>/tmp/osb-apt.log 2>&1
mkdir -p /tmp/osb-lockbg && chmod 1777 /tmp/osb-lockbg
# Box-only: the session user 'box' has no password (locked account), so the lock screen authenticates the dedicated
# test account named in ~/.config/osb/lock-test-user. Recreate it after a box reset (password documented in README Rev 16).
T=$(cat ~/.config/osb/lock-test-user 2>/dev/null)
if [ -n "$T" ] && ! id "$T" >/dev/null 2>&1 && passwd -S "$USER" 2>/dev/null | grep -q " L "; then
  sudo -n useradd -M -d /nonexistent -s /usr/sbin/nologin -c "Polder OS lock test" "$T" && echo "$T:Polder-Test-2026" | sudo -n chpasswd
fi
# settings.json (defaults on first run) -> palette.env -> build-theme.sh (gtk theme, xfwm4 theme, rofi, qs.css, tint2)
mkdir -p ~/.config/osb; [ -f ~/.config/osb/settings.json ] || python3 -c "import sys; sys.path.insert(0,'$C/osb'); import osbsettings as S; S.save(S.load())"
python3 $C/osb/apply.py palette
# Instellingen in the launcher, replacing xfce4-settings-manager in that role
export XDG_DATA_HOME=/tmp/protohome/.local/share; A=$XDG_DATA_HOME/applications   # isolated from the host desktop
mkdir -p $A; cp $C/settings/instellingen.desktop $A/
cp $C/files/files.desktop $A/   # 'Bestanden' as a real desktop id (files.desktop) for pins/launcher
cp $C/store/polder-store.desktop $A/   # Revision 22: Polder Store
# Revision 22 (box-only): PackageKit/Flatpak need a system bus + polkitd, which this container does not run by itself
[ -S /run/dbus/system_bus_socket ] || { sudo -n mkdir -p /run/dbus; sudo -n dbus-daemon --system --fork; }
pgrep -x polkitd >/dev/null || sudo -n sh -c "nohup /usr/lib/polkit-1/polkitd --no-debug >/tmp/polkitd.log 2>&1 &"
for p in packagekit appstream flatpak gir1.2-appstream-1.0; do dpkg -s $p >/dev/null 2>&1 || { sudo -n apt-get install -y --no-install-recommends packagekit appstream flatpak gir1.2-appstream-1.0 >>/tmp/osb-apt.log 2>&1; break; }; done
sed 's|^Exec=/usr/bin/chromium|Exec=/usr/bin/chromium --user-data-dir=/tmp/protohome/chromium --no-first-run|' /usr/share/applications/chromium.desktop > $A/chromium.desktop 2>/dev/null
command -v xclip >/dev/null || sudo -n apt-get install -y --no-install-recommends xclip >>/tmp/osb-apt.log 2>&1
# Revision 18: capture bar (cairo overlay, ffmpeg) + MPRIS test player
python3 -c "import gi; gi.require_foreign('cairo')" 2>/dev/null || sudo -n apt-get install -y --no-install-recommends python3-gi-cairo >>/tmp/osb-apt.log 2>&1
command -v mpv >/dev/null || sudo -n apt-get install -y --no-install-recommends mpv mpv-mpris >>/tmp/osb-apt.log 2>&1
for p in /usr/share/applications/xfce-*settings*.desktop /usr/share/applications/xfce4-{accessibility,color,mime}-settings.desktop /usr/share/applications/xfce4-settings-editor.desktop /usr/share/applications/{rofi,rofi-theme-selector,tint2,tint2conf,picom,x11vnc,thunar-settings,plank}.desktop; do [ -f "$p" ] && { grep -v "^NoDisplay" "$p"; echo NoDisplay=true; } > $A/$(basename $p); done
cp $C/files/bookmarks $X/gtk-3.0/; cp $C/files/thunar.xml $X/xfce4/xfconf/xfce-perchannel-xml/; cp $C/files/uca.xml $X/Thunar/
# Files sample content
H="/tmp/osb-files/Mijn bestanden"; mkdir -p "$H"/{Downloads,Muziek,Afbeeldingen,"Video's"}
if [ -z "$(ls "$H/Downloads")" ]; then
  for n in "Screenshot 2026-10-09 at 14.02.11" "Screenshot 2026-10-10 at 09.15.40" vakantie-zeeland wallpaper-blauw; do
    convert -size 400x267 plasma:fractal "$H/Downloads/$n.png"; done
  convert -size 300x200 xc:'#8ab4f8' "$H/Downloads/boarding-pass.pdf"; echo notities > "$H/Downloads/notities.txt"
fi
eval $(dbus-launch --sh-syntax); echo "$DBUS_SESSION_BUS_ADDRESS" > /tmp/osb-session-bus
# xsettings daemon: lets running GTK apps switch theme live (build-theme.sh alternates PolderOS-GTK-1/2)
xfsettingsd --sm-client-disable >/tmp/osb-xfsettingsd.log 2>&1 &
sleep 1; xfconf-query -c xsettings -p /Net/ThemeName -n -t string -s PolderOS-GTK-$(cat ~/.config/osb/gtkslot) 2>/dev/null || xfconf-query -c xsettings -p /Net/ThemeName -s PolderOS-GTK-$(cat ~/.config/osb/gtkslot)
xfconf-query -c xsettings -p /Net/IconThemeName -n -t string -s Papirus 2>/dev/null || xfconf-query -c xsettings -p /Net/IconThemeName -s Papirus
xfconf-query -c xsettings -p /Gtk/FontName -n -t string -s "Roboto 10" 2>/dev/null || xfconf-query -c xsettings -p /Gtk/FontName -s "Roboto 10"
xfwm4 --display=$D --compositor=off --sm-client-disable >/tmp/proto-wm.log 2>&1 &
sleep 1
xfconf-query -c xfwm4 -p /general/theme -n -t string -s PolderOS 2>/dev/null || xfconf-query -c xfwm4 -p /general/theme -s PolderOS
xfconf-query -c xfwm4 -p /general/button_layout -n -t string -s "|HMC" 2>/dev/null || xfconf-query -c xfwm4 -p /general/button_layout -s "|HMC"
xfconf-query -c xfwm4 -p /general/title_font -n -t string -s "Roboto Medium 10" 2>/dev/null
# Revision 9: free Alt+Tab from xfwm4 (needs xfwm4 restart to drop its grab), 2 desks
for p in "/xfwm4/custom/<Alt>Tab" "/xfwm4/custom/<Alt><Shift>Tab" "/xfwm4/default/<Alt>Tab" "/xfwm4/default/<Alt><Shift>Tab"; do
  xfconf-query -c xfce4-keyboard-shortcuts -p "$p" -n -t string -s empty 2>/dev/null || xfconf-query -c xfce4-keyboard-shortcuts -p "$p" -s empty; done
xfwm4 --display=$D --compositor=off --sm-client-disable --replace >/tmp/proto-wm.log 2>&1 &
sleep 1; wmctrl -n 2
# Revision 10: drag-to-edge tiling in xfwm4 (keyd adds preview + Alt+[ ] = - shortcuts)
xfconf-query -c xfwm4 -p /general/tile_on_move -n -t bool -s true 2>/dev/null || xfconf-query -c xfwm4 -p /general/tile_on_move -s true
picom --config $C/picom.conf -b   # Revision 23: rounded app windows (capture composited output with ffmpeg x11grab, not import)
feh --bg-fill $C/wallpaper.png
# Revision 27: polder-shell = notify + shelf + launcher + clipboard + settingsd + keyd in ONE process (one GTK loop).
# Supervisor restarts it if it exits; POLDER_SHELL=0 starts the old separate processes instead (fallback).
if [ "${POLDER_SHELL:-1}" = 1 ]; then
  rm -f /tmp/polder-shell.pid
  (while true; do python3 $C/shell/polder-shell.py >>/tmp/polder-shell.log 2>&1; rm -f /tmp/polder-shell.pid; sleep 2; done) &
else
  python3 $C/notify/osb-notifyd.py >/tmp/osb-notifyd.log 2>&1 &
  python3 $C/shelf/shelf.py >/tmp/osb-shelf.log 2>&1 &
  python3 $C/clip/clipd.py >/tmp/osb-clipd.log 2>&1 &
  python3 $C/wm/keyd.py >/tmp/osb-keyd.log 2>&1 &
  python3 $C/osb/osb-settingsd.py >/tmp/osb-settingsd.log 2>&1 &
  python3 $C/launcher/launcher.py >/tmp/osb-launcher.log 2>&1 &   # Revision 14: resident launcher (Super / launcher button toggle it)
fi
sleep 1
tint2 -c $C/tint2rc >/tmp/proto-tint2.log 2>&1 &
# Revision 17: own GTK app shelf (pins + running apps + right-click menu) replaces tint2-shelf-apps.rc; clipboard history daemon
rm -f /tmp/osb-shelf.pid /tmp/osb-clipd.pid
for k in '<Alt>Print' '<Shift>Print' 'Print'; do xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/$k" -r 2>/dev/null; done   # Print -> our capture bar (keyd)
(sleep 3; OSB_LOCK_CACHE=/tmp/osb-lockbg python3 $C/lock/lockui.py --prerender >/tmp/osb-lockbg.log 2>&1) &   # Revision 16: blurred lock bg   # Revision 12: live settings, auto theme, ICS sync
(sleep 4; command -v kdeconnectd >/dev/null && QT_QPA_PLATFORM=offscreen kdeconnectd >/tmp/kdeconnectd.log 2>&1) &   # Revision 28: Telefoon (KDE Connect, ~41 MB PSS)
(sleep 6; python3 $C/welcome/welkom.py --first-run) &   # Revision 24: Welkom bij Polder OS (only until welcome_done)
