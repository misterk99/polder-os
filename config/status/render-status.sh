#!/bin/bash
# Renders ChromeOS-style status pills as PNGs for tint2 executors.
# usage: render-status.sh kb|media|date|tray  -> prints PNG path
OUT=/tmp/osb-status; mkdir -p $OUT
S=/usr/share/icons/Papirus/24x24/symbolic
BG='#e8eef7'; FG='#1f1f1f'; BADGE_FG='#f8f9fc'; FONT=/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Medium.ttf; H=36
icon(){ local T=/tmp/osb-i-$(basename $2); rsvg-convert -w 20 -h 20 "$1" -o $T && convert $T -fill "$FG" -colorize 100 png32:"$2"; }
pill(){ # $1 text $2 out  (text-only pill)
  local K=$(basename $2 .png)
  convert -background none -font $FONT -pointsize 15 -fill "$FG" label:"$1" /tmp/osb-t-$K.png
  W=$(( $(identify -format %w /tmp/osb-t-$K.png) + 28 ))
  convert -size ${W}x$H xc:none -fill "$BG" -draw "roundrectangle 0,0 $((W-1)),$((H-1)) 18,18" \
    /tmp/osb-t-$K.png -gravity center -composite png32:"$2"; }
SET=~/.config/osb/settings.json
setting(){ python3 -c "import json,sys;d=json.load(open('$SET')) if __import__('os').path.exists('$SET') else {};print(int(d.get('$1',$2)))" 2>/dev/null || echo $2; }
# tint2 caches images by path -> publish every rendering under a content-hash name so theme/text changes show up
uniq(){ local h=$(md5sum < $OUT/$1.png | cut -c1-10); rm -f $OUT/$1-*.png; mv $OUT/$1.png $OUT/$1-$h.png; echo $OUT/$1-$h.png; }
case $1 in
 kb)   L=$(setxkbmap -query 2>/dev/null | awk '/layout/{print toupper($2)}'); pill "${L:-US}" $OUT/kb.png; uniq kb;;
 date) if [ "$(setting show_date 1)" = 0 ]; then echo; exit 0; fi   # 'Datum op plank' uit -> no pill
   M=(jan feb mrt apr mei jun jul aug sep okt nov dec); pill "$(date +%-d) ${M[$(( $(date +%-m)-1 ))]}" $OUT/date.png; uniq date;;
 weather) R=$(timeout 5 python3 $(dirname $0)/../weather/weather.py pill 2>/dev/null)   # Revision 25: hides when no fresh real data
   if [ -z "$R" ]; then echo; exit 0; fi
   icon $(ls $S/*/${R%% *}-symbolic.svg | head -1) /tmp/osb-wx.png
   convert -background none -font $FONT -pointsize 15 -fill "$FG" label:"${R#* }" /tmp/osb-wxt.png
   convert -background none /tmp/osb-wx.png \( -size 6x20 xc:none \) /tmp/osb-wxt.png -gravity center +append /tmp/osb-wxrow.png
   W=$(( $(identify -format %w /tmp/osb-wxrow.png) + 26 ))
   convert -size ${W}x$H xc:none -fill "$BG" -draw "roundrectangle 0,0 $((W-1)),$((H-1)) 18,18" /tmp/osb-wxrow.png -gravity center -composite png32:$OUT/weather.png; uniq weather;;
 media) icon $(ls $S/*/music-playlist-symbolic.svg | head -1) /tmp/osb-media.png
   convert -size 44x$H xc:none -fill "$BG" -draw "roundrectangle 0,0 43,35 18,18" /tmp/osb-media.png -gravity center -composite png32:$OUT/media.png; echo $OUT/media.png;;
 tray)
   N=$(python3 -c "import json;print(json.load(open('/tmp/osb-notify/state.json')).get('unread',0))" 2>/dev/null || echo 0)
   DND=$(python3 -c "import json;print(int(json.load(open('/tmp/osb-notify/state.json')).get('dnd',False)))" 2>/dev/null || echo 0)
   # wifi/battery icons only when real hardware info exists (no placeholders)
   PARTS=""
   if command -v nmcli >/dev/null && q=$(nmcli -t -f IN-USE,SIGNAL dev wifi 2>/dev/null | awk -F: '$1=="*"{print $2}') && [ -n "$q" ]; then
     SIG=excellent; [ $q -lt 80 ] && SIG=good; [ $q -lt 60 ] && SIG=ok; [ $q -lt 30 ] && SIG=weak
     icon $S/status/network-wireless-signal-$SIG-symbolic.svg /tmp/osb-wifi.png; PARTS="$PARTS ( -size 10x20 xc:none ) /tmp/osb-wifi.png"; fi
   f=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)
   if [ -n "$f" ]; then BL=$(( ($(cat $f/capacity)+5)/10*10 )); icon $S/status/battery-level-$BL-symbolic.svg /tmp/osb-bat.png; PARTS="$PARTS ( -size 4x20 xc:none ) /tmp/osb-bat.png"; fi
   TF=%H:%M; [ "$(setting clock24 1)" = 0 ] && TF=%-I:%M
   convert -background none -font $FONT -pointsize 15 -fill "$FG" label:"$(date +$TF)" -gravity west -extent "$(( $(convert -background none -font $FONT -pointsize 15 label:"$(date +$TF)" -format %w info:)+12 ))x20" /tmp/osb-time.png
   BADGE=/tmp/osb-n.png
   if [ "$DND" = 1 ]; then rsvg-convert -w 20 -h 20 $S/status/notifications-disabled-symbolic.svg -o /tmp/osb-dnd0.png; convert /tmp/osb-dnd0.png -fill "$FG" -colorize 100 png32:/tmp/osb-n.png
   elif [ "$N" = 0 ]; then BADGE="( -size 1x20 xc:none )"; fi
   [ "$DND" != 1 ] && [ "$N" != 0 ] && convert -size 20x20 xc:none -fill "$FG" -draw "circle 10,10 10,1" -font $FONT -pointsize 12 -fill "$BADGE_FG" -gravity center -annotate +0+0 "$N" png32:/tmp/osb-n.png
   convert -background none /tmp/osb-time.png $BADGE $PARTS +append /tmp/osb-row.png
   W=$(( $(identify -format %w /tmp/osb-row.png) + 28 ))
   convert -size ${W}x$H xc:none -fill "$BG" -draw "roundrectangle 0,0 $((W-1)),$((H-1)) 18,18" /tmp/osb-row.png -gravity center -composite png32:$OUT/tray.png
   echo $OUT/tray.png;;
esac
