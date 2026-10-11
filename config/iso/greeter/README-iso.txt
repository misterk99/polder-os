Polder OS login/lock for the ISO
- packages: lightdm, gir1.2-lightdm-1, python3-gi, python3-pampy, imagemagick (+ Roboto, Papirus)
- copy config/ to /usr/share/polderos/ ; install the files here to the paths in their header comments
- /etc/os-release: NAME="Polder OS"  ID=polderos  ID_LIKE=debian
- lock screen runs as the logged-in user (no ~/.config/osb/lock-test-user on the ISO); pam_unix checks
  the user's own password through the setgid unix_chkpwd helper, so no root is needed.
- 'Uitschakelen'/'Afmelden' on the lock screen: map to `systemctl poweroff` / `loginctl terminate-session`
  (disabled in the prototype); greeter uses LightDM.shutdown()/restart().
