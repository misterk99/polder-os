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

## polder-phonehub (Rust) – Telefoon-hub

Phone Hub / Phone Link style panel on KDE Connect, talking to the real kdeconnectd D-Bus API (`src/kdc.rs`;
interfaces from KDE Connect 24.12 `core/` and `plugins/`). Opened from the `Telefoon` tile in Rust QS and in qs.py
(tile shown whenever KDE Connect is installed/running; launches `polder-phonehub` if installed, else Instellingen).
- paired phone: name, reachable state, battery % + charging (battery plugin), cellular type + signal bars (connectivity_report)
- Telefoon zoeken (findmyphone.ring), Bestand sturen (GTK file chooser -> share.shareUrls), Klembord delen toggle
  (setPluginEnabled kdeconnect_clipboard), Foto's en bestanden (sftp.mountAndWait + getDirectories: newest four
  camera photos, shared folders, all files; opened in the file manager)
- phone notifications (notifications.activeNotifications): dismiss when dismissable, inline reply only when the
  phone provides a replyId (notification.sendReply)
- states: KDE Connect not installed / not running (Starten: D-Bus activation or the daemon binary) / no device
  visible (hint + Opnieuw zoeken) / pairing (Koppelen, code, Annuleren) / incoming request (Accepteren / Weigeren) /
  paired but unreachable; Ontkoppelen
- toggle like QS (`$OSB_RUNDIR/polder-phonehub.pid`), Escape, outside click, live palette

`tests/mock-kdeconnect.py` is a TEST FIXTURE ONLY: a fake kdeconnectd with made-up data for headless tests
(`--state paired|unpaired|request|none`); it is never installed. `POLDER_KDECONNECTD` overrides the daemon binary.

## polder-launcher (Rust port of config/launcher/launcher.py)
Resident GTK4 layer-shell launcher, same PID file (`$OSB_RUNDIR/osb-launcher.pid`) and SIGUSR1 toggle as launcher.py, so
`launcher/launcher-toggle.sh` drives either. Opt in with `POLDER_LAUNCHER_IMPL=rust` or `~/.config/osb/launcher-impl` = `rust`
(note: `POLDER_LAUNCHER` itself is polder-comp's Super-key command). Parity: app grid (5 per row, `app_order` drag & drop,
right-click pin/unpin/open/sort), search groups Webapp (`installeer <url> [als app] [naam]` via webapps.py), Rekenmachine
(`src/calc.rs`, Python semantics, unit-tested), Apps, Instellingen sections, Bestanden (index of `$OSB_FILES_HOME`), Internet;
Up/Down/Enter/Escape, hides on focus loss, live palette. Tests: `tests/components-session.sh`, `tests/pc-drag.c`.
