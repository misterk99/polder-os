#!/bin/bash
# ChromeOS-style quick settings popup (rofi). Placeholder actions where no hardware exists.
C=/workspace/osbuilder/config
ch=$(printf '%s\n' "  Wi-Fi: aan" "  Bluetooth: uit" "  Volume 70%" "  Helderheid 80%" "  Niet storen" "  Instellingen" "  Vergrendelen" "  Uitschakelen" | rofi -dmenu -i -p "Snelle instellingen" -theme $C/quick-settings.rasi)
case "$ch" in
 *Instellingen*) xfce4-settings-manager 2>/dev/null & ;;
 *Volume*) command -v pavucontrol >/dev/null && pavucontrol & ;;
 *Uitschakelen*) echo "would run: systemctl poweroff" ;;
esac
