#!/bin/bash
# Continuous tint2 executor: re-renders the time pill when minute / unread count / DND changes.
D=$(dirname "$0"); last=""
while true; do
  k="$(date +%H%M) $(stat -c %Y /tmp/osb-notify/state.json 2>/dev/null) $(md5sum /tmp/osb-notify/state.json 2>/dev/null | cut -c1-8) $(stat -c %Y ~/.config/osb/settings.json /workspace/osbuilder/config/palette.env 2>/dev/null | tr '\n' ' ')"
  if [ "$k" != "$last" ]; then
    p=$("$D/render-status.sh" tray); n=/tmp/osb-status/tray-$(date +%s%N).png; mv "$p" "$n"
    rm -f $(ls /tmp/osb-status/tray-*.png | grep -v "$n") 2>/dev/null
    echo "$n"; last="$k"
  fi
  sleep 1
done
