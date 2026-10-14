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
