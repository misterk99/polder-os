#!/bin/sh
# Lock the Polder OS session. On this prototype box the session user 'box' has no password (account locked),
# so the lock runs as the dedicated test account named in ~/.config/osb/lock-test-user (PAM checks THAT
# account's password). On the ISO this file doesn't exist and the lock runs as the logged-in user.
L=/workspace/osbuilder/config/lock/lock.py
pgrep -f "$L" >/dev/null && exit 0
T=$(cat ~/.config/osb/lock-test-user 2>/dev/null)
if [ -n "$T" ]; then
  cp ~/.config/osb/settings.json /tmp/osb-lock-settings.json; chmod 644 /tmp/osb-lock-settings.json
  xhost +SI:localuser:"$T" >/dev/null 2>&1
  exec sudo -n -u "$T" env DISPLAY="$DISPLAY" OSB_LOCK_TEST_ACCOUNT=1 OSB_SETTINGS=/tmp/osb-lock-settings.json OSB_LOCK_CACHE=/tmp/osb-lockbg HOME=/tmp/osb-lock-home XDG_CACHE_HOME=/tmp/osb-lock-home/.cache \
       XDG_DATA_HOME=/tmp/protohome/.local/share python3 "$L" >>/tmp/osb-lock.log 2>&1
else
  export OSB_LOCK_CACHE=/tmp/osb-lockbg
  exec python3 "$L" >>/tmp/osb-lock.log 2>&1
fi
