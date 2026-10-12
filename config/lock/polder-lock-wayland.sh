#!/bin/bash
# Rev 34b: lock screen on polder-comp (Wayland). swaylock speaks ext-session-lock-v1 (the compositor keeps everything
# covered until the locker says 'unlock', and stays locked if the locker dies) and checks the password via PAM.
# Styled with the Polder palette + a darkened, blurred wallpaper. usage: polder-lock-wayland.sh [-f]  (-f: daemonize)
C=$(cd "$(dirname "$0")/.." && pwd); . "$C/palette.env" 2>/dev/null
h(){ echo "${1#\#}"; }
WP="$C/wallpaper.png"; [ -f "$WP" ] || WP="$C/wallpapers/polderheuvel.png"
BG=${XDG_RUNTIME_DIR:-/tmp}/polder-lock-bg.png
if [ ! -f "$BG" ] || [ "$WP" -nt "$BG" ]; then convert "$WP" -resize 25% -blur 0x6 -resize 400% -fill black -colorize 35% "$BG" 2>/dev/null || BG=""; fi
exec swaylock ${BG:+-i "$BG"} -s fill -c "$(h ${SURFACE:-#1f2023})" -F -e \
  --font Roboto --font-size 22 --indicator-radius 72 --indicator-thickness 8 \
  --inside-color "$(h ${SURFACE:-#f8f9fc})dd" --inside-clear-color "$(h ${SURFACE:-#f8f9fc})dd" --inside-ver-color "$(h ${ACCENT_CONTAINER:-#d3e3fd})ee" --inside-wrong-color ffdad6ee \
  --ring-color "$(h ${ACCENT:-#0b57d0})" --ring-ver-color "$(h ${ACCENT:-#0b57d0})" --ring-clear-color "$(h ${OUTLINE:-#d3dbe5})" --ring-wrong-color d93025 \
  --key-hl-color "$(h ${ON_ACCENT_CONTAINER:-#041e49})" --bs-hl-color d93025 --line-color 00000000 --line-clear-color 00000000 --line-ver-color 00000000 --line-wrong-color 00000000 \
  --separator-color 00000000 --text-color "$(h ${ON_SURFACE:-#1f1f1f})" --text-ver-color "$(h ${ON_SURFACE:-#1f1f1f})" --text-wrong-color 8c1d18 --text-clear-color "$(h ${ON_SURFACE:-#1f1f1f})" \
  "$@"
