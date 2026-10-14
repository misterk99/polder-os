# polder-shelf (Rust)

Rust/GTK4 port of `config/shelf/shelf.py` (Wayland path) for polder-comp: a `wlr-layer-shell` bar (namespace
`polder-shelf`, bottom, exclusive 52 px) plus the wallpaper desktop surface (`polder-desktop`, background layer).

Feature parity with the Python shelf:
- launcher button (`launcher/launcher-toggle.sh`), pinned apps from `settings.json` `pinned`, running unpinned apps
- running dot + active highlight, via wlr-foreign-toplevel (helper `polder-toplevels`); polder-comp only advertises
  the current desk's windows, so per-desk filtering comes from the compositor
- left click: launch / activate / minimise, middle click: new window, right click: rounded menu
  (Vastzetten/Losmaken, Nieuw venster, Sluiten (n vensters)) as an overlay layer surface
- recording pill (same PID-lifetime check as `capture_backend.recording_state`, stop via `capture_backend`),
  MPRIS media pill (play/pause)
- keyboard, weather (`weather.py pill`), date (`cal.py`), quick settings pill (clock, DND/unread badge, update,
  wifi/volume/battery icons only when the hardware/info really exists)
- live theme: reloads CSS when `palette.env` changes; live pin changes when `settings.json` changes
- desktop right-click menu (Achtergrond en stijl, Bestanden openen, Instellingen, Sneltoetsen), live wallpaper
- same single-instance PID file (`$OSB_RUNDIR/osb-shelf.pid`) as the Python shelf, so only one runs

Opt-in in the session (`iso/src/polderos-wayland-components`): `POLDER_SHELF=rust` or
`echo rust > ~/.config/osb/shelf-impl`. The Python shelf stays the default and the fallback.

Environment: `POLDER_CONFIG` (config dir), `OSB_RUNDIR`, `OSB_SETTINGS`, `POLDER_TOPLEVELS`.

## polder-quicksettings (Rust)

Second binary of this crate: port of `config/quicksettings/qs.py` (Wayland path), overlay layer surface
`polder-quicksettings` anchored bottom-right above the shelf.
- toggle: running it again closes the open panel (same `$OSB_RUNDIR/osb-qs.pid` as qs.py); closes on Escape, on
  focus loss and when polder-comp dismisses it on an outside click; a click on the shelf pill closes, not reopens
- notification history card (Meldingen (n), Alles wissen, per-card close, card click / action buttons -> `Invoke`)
  through the real osb-notifyd D-Bus service; marks read on open; compact one-row toggles while notifications exist
- header: date, `Update` pill (reboot only in the ISO session), version from `osbsettings.VERSION`
- MPRIS media card (art, title, artist · player, previous / play-pause / next)
- tiles only when they really work: Wifi (nmcli), Bluetooth (bluetoothctl), Donker thema (writes settings.json theme),
  Toetsenbord (layout name, opens Instellingen), Schermopname (capture bar), Niet storen (SetDnd), Telefoon (KDE Connect)
- sliders: volume (pactl/amixer, starts at the real sink volume), brightness only with a real backlight (brightnessctl)
- footer: power dialog (Afmelden / Opnieuw opstarten / Uitschakelen / Slaapstand; real only with POLDEROS_ISO), lock,
  avatar with the user's real initial, battery %, Instellingen
- live palette reload while open

Switch: `POLDER_QS=rust` or `echo rust > ~/.config/osb/qs-impl`; both shelves (Rust and Python) then launch
`polder-quicksettings` from PATH, else qs.py. `OSB_NOTIFY_DIR` overrides `/tmp/osb-notify` (tests).

Tests: `tests/headless-session.sh` (headless polder-comp + private D-Bus + real osb-notifyd with clean data),
`tests/pc-click.c` (real clicks via wlr-virtual-pointer), `tests/fakeplayer.py` (MPRIS test player).
