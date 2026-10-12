# Changelog

_History reconstructed from the development log; intermediate file states were not preserved. Each revision lists its main changes._

## Rev 1: Initial ChromeOS-style desktop prototype

- **xfwm4** window manager (Arc theme, Roboto title font)
- **tint2** x2: full-width translucent shelf (launcher button left, systray + clock pill right)
- **rofi** (drun) styled as ChromeOS launcher (rounded, search bar, icon grid)
- **feh** wallpaper, **Roboto** font, **Arc** GTK theme, **Papirus** icons
- **Chromium** pinned first on the shelf
- `start-session.sh` – starts prototype on separate display (default `:55`, Xvfb 1366x768) with isolated XDG_CONFIG_HOME + own dbus so the host desktop is untouched
- `tint2rc` – outer shelf (launcher button E, free space F, systray S, clock C)
- `tint2-shelf-apps.rc` – centered pinned apps (L) + taskbar (T)

## Rev 2: shelf visibility + launcher corners

- Shelf is now a solid dark bar `#2b2c2f` full width (both tint2 panels use the same colour so the
- tint2 gotcha: background blocks (`rounded = ...`) MUST come before `panel_background_id` etc.,
- Launcher (rofi) window is square with white background: under Xvfb the compositor output is not
- `picom.conf` (shadows, corner-radius 10) included for the real ISO (Xorg); install `picom`.

## Rev 3: rounded launcher + ChromeOS status area

- **Rounded launcher without compositor**: rofi `window` has `background-image: launcher-bg.png`
- **Status area** (`status/render-status.sh kb|media|date|tray`): renders pill PNGs shown by tint2 executors:
- **Quick settings**: clicking the time pill runs `status/quick-settings.sh` (rofi menu, theme
- Outer shelf uses `panel_layer = bottom` so the centered app panel stays on top after clicks.

## Rev 4: Files app, ChromeOS style

- `run-files.sh` – launches Thunar with HOME=`/tmp/osb-files/Mijn bestanden` (so breadcrumb reads
- `files.desktop` – "Bestanden", pinned on the shelf (replaces thunar.desktop in tint2-shelf-apps.rc).
- `bookmarks` – sidebar: Recent (recent:///), Audio, Afbeeldingen, Video's, Downloads.
- `thunar.xml` – xfconf channel: details (list) view default, columns Name/Size/Type/Date modified,
- `gtk.css` – white UI, Roboto, light-blue selection (#d2e3fc / #1967d2), flat toolbar, rounded white menus.
- `uca.xml` – custom action "Zippen" in the context menu.

## Rev 5: Quick Settings panel


## Rev 6: one unified palette


## Rev 7: notification center

- Quick Settings (`qs.py`) opens a history stack above the panel: header "Meldingen (n)" + "Alles wissen",
- "Niet storen" tile calls SetDnd: pop-ups suppressed, notifications still stored; time pill shows a bell-off icon.
- Shelf badge: `status/tray-watch.sh` (tint2 continuous executor) re-renders the time pill within ~1 s when

## Rev 8: aligned notification column + click actions

- One column, 420 px wide, right edge x=1355 (10 px margin), bottom y=705 (10 px above the 52 px shelf):
- Actions (freedesktop spec): capability "actions"; `-A key=Label` buttons are rendered on cards; clicking a

## Rev 9: Overview + Alt+Tab

- Overview: fullscreen blurred+darkened wallpaper (shelf stays visible), desks bar "Bureau 1..n" + "+ Nieuw bureau"
- Alt+Tab: centered rounded strip (backdrop = screen region behind it), MRU order, keyboard grabbed: Tab/Shift+Tab/arrows
- start-session.sh now rebuilds everything that lived in /tmp after a reboot (theme, Thunar config, sample files),

## Rev 10: window snapping + split view

- `wm/snap.py left|right|max|min [wid]`: half-screen snap within the work area (1366x716, above the 52 px shelf),
- `wm/keyd.py`: Alt+[ / Alt+] snap left/right, Alt+= maximize/restore, Alt+- minimize (ChromeOS shortcuts).
- Drag to edge: keyd polls the pointer (60 ms); a drag only counts if the press started in a window's titlebar band

## Rev 11: Calendar popup

- `config/calendar/cal.py` (Python/GTK3, ~200 lines): opened by clicking the date pill (`execp_lclick_command` in `tint2rc`). Unified palette, 24px rounded panel (wallpaper-backdrop trick), 360px wide, right edge …
- Dutch: month names, `ma … zo` headers, week starts Monday, day header like "vrijdag 16 oktober", "Vandaag", "Geen evenementen".
- Header: month/year, ↑/↓ month buttons, "Vandaag". Grid: always 6 rows (constant height), today = accent circle, selected day = accent-container circle, other-month days dimmed, dot under days with events. Mouse …
- Events: minimal ICS parser for `~/.local/share/osb/calendar.ics` (DTSTART date/datetime, DTEND, SUMMARY, LOCATION). Event area has a fixed height (max 2 cards + "+N meer") so the panel never jumps. Sample file …
- Closes on Escape, clicking the date pill again (pidfile toggle `/tmp/osb-cal.pid`), or focus loss. Mutually exclusive with QS (each kills the other's pidfile process; `qs.py` patched).
- Not supported: recurring events (RRULE), time zones (TZID ignored, times taken as local), multi-day spans, editing events, online calendars.
- Click-outside closing: xfwm4 doesn't move focus when you click the bare desktop, so the calendar grabs the pointer and closes on any press outside the panel. Side effect: while the calendar is open, a click on the …

## Rev 12: Instellingen app, real settings, dark theme, ICS feeds

- **One settings file:** `~/.config/osb/settings.json` (`config/osb/osbsettings.py`: defaults, palettes, accent colours, layouts).
- **Instellingen** (`config/settings/instellingen.py`, GTK3, single instance): left nav with rounded accent-container selection, content cards. It's in the launcher (`instellingen.desktop`), and the QS gear button …
- *Personalisatie*: Licht / Donker / Automatisch, 5 accent presets (blauw, groen, paars, roze, oranje), 5 wallpapers (`config/wallpapers/`).
- *Meldingen*: pop-ups on/off (the daemon reads settings for every notification), keep history while pop-ups are off, Niet storen (same D-Bus state as the QS tile), pop-up duration 3/6/10/15s, test button.
- *Agenda*: add iCal/ICS links (http/https/webcal) with a name and colour, delete them, auto-refresh 15m–3h, "Nu vernieuwen". Status is shown honestly: last sync, number of items, or the actual error …
- *Toetsenbord en taal*: layout through setxkbmap; the shelf pill follows it. *Datum en tijd*: 24-hour clock and "datum op plank" toggles. *Over*: version, Debian version, kernel, memory, screen.
- **Dark palette and live switching:** `apply.py` writes `palette.env` (now GENERATED) and runs `build-theme.sh`. Then it reloads tint2 (SIGUSR1; pill PNGs get content-hash names because tint2 caches images by path), …
- **Calendar:** `config/calendar/feeds.py` uses python3-icalendar + recurring-ical-events. It handles RRULE/RDATE/EXDATE, TZID converted to Europe/Amsterdam (DST-correct), floating times, and all-day and multi-day …

## Rev 13: rebrand to Polder OS

- Everything user-visible now says **Polder OS 0.13**: QS version pill, Instellingen "Over Polder OS" (with logo), notification server info, ICS User-Agent. The xfwm4 theme is now `PolderOS`, and the GTK themes are …
- Internal paths (`/workspace/osbuilder`, `config/osb/`, `~/.config/osb`, `/tmp/osb-*`) are unchanged on purpose, so start-session.sh and running services keep working.
- ISO plan, `/etc/os-release`: `NAME="Polder OS"`, `PRETTY_NAME="Polder OS 0.13"`, `ID=polderos`, `ID_LIKE=debian`, `VERSION_ID=0.13`, `HOME_URL=` (to be filled in).
- **Polderheuvel** wallpaper (`config/wallpapers/make-polder.py`, original procedural PIL artwork that pays homage to "Bliss" without using it): rolling green hill, blue sky, soft clouds, a straight sloot, a distant …
- Logo `config/brand/polderos-logo.png` (white windmill sails on blue over a green polder strip), used as the launcher button (launcher-icon.png) and on the Over page.

## Rev 14: real launcher search

- **Why a Python/GTK launcher instead of rofi:** `config/launcher/launcher.py` is a small resident GTK3 app. Rofi can't do ChromeOS-style grouped sections with headers and mixed result types in one list, and it …
- Measured with xdotool, from Super press to window visible: 29–33 ms when warm, 151 ms on the first show. RSS is about 59 MB idle and about 78 MB after searching.
- Started by start-session.sh. The Super tap (keyd.py) and the shelf launcher button both toggle it. F3 still opens Overview.
- **Empty query** shows the app grid (Gio.AppInfo, i.e. the real .desktop files; NoDisplay respected). Infrastructure apps are hidden with NoDisplay overrides in the isolated XDG_DATA_HOME: rofi, tint2, picom, …
- **Typing** shows grouped results, all real:
- **Rekenmachine**: safe AST evaluation; supports + - * x / ^ % ( ) and decimal commas. Enter copies the result to the clipboard and shows a notification.
- **Apps**: fuzzy match on name, generic name, keywords and id.
- **Instellingen**: 9 deep links (thema/donker, achtergrond, accent, meldingen, niet storen, agenda, toetsenbord, datum, over) that open `instellingen.py <section>`.

## Rev 15: Polderheuvel photo wallpapers

- The procedural Polderheuvel is replaced by the user's AI-generated photos: a day scene (sloot, windmill, cows, clouds) and a night scene (Milky Way, sunset glow, same polder).
- Polderheuvel is still the default and first in the picker; the dark theme auto-uses `-avond`. The procedural generator was moved to `config/brand/make-polder-procedural.py` (no longer used). The simple gradient …
- All rounded-corner backdrops are regenerated: apply.py deletes the old crops; the launcher, QS, calendar, notifications and snap preview re-crop from wallpaper.png. Contrast is fine because the shelf and panels are …

## Rev 16: lock screen + login greeter (ChromeOS-style)

- `config/lock/lockui.py`: shared UI — blurred+dimmed current wallpaper (pre-rendered by `osb/apply.py` on every
- `config/lock/lock.py`: real lock. Fullscreen override-redirect window, full keyboard+pointer seat grab (retried until it
- Triggers: Super+L (`wm/keyd.py`), QS lock button, auto-lock after idle (`osb-settingsd.py`, XScreenSaver idle via
- `config/lock/lock-now.sh` is the single entry point. **Box-only test arrangement:** the box user `box` has no password
- `config/lock/polderos-greeter.py`: LightDM greeter (liblightdm-gobject) with user pods side by side, password, auto-selects
- Screenshots: 35-lock-light, 36-lock-dark, 37-lock-wrongpw, 38-login-preview (PREVIEW, not a real LightDM run).

## Rev 17: pinning apps + clipboard history

- **Shelf choice:** tint2 can't show per-icon context menus, so the centred app area (`tint2-shelf-apps.rc`, now unused) is
- Pins: `settings.json` `pinned` (desktop ids); shelf picks changes up within 0.7 s. Launcher grid + search results:
- `config/osb/popmenu.py`: shared rounded menu; its window background is a grab of the real screen area underneath, so the
- Clipboard: `config/clip/clipd.py` (resident, ~72 MB) records CLIPBOARD text + images (max 10, `~/.cache/osb/clipboard/`),
- Files: `files/files.desktop` + a Chromium .desktop override (shared profile) are installed into `$XDG_DATA_HOME/applications`.
- Screenshots: 39-shelf-menu, 40-launcher-pin, 41-clipboard.

## Rev 18: screen capture bar + media controls (MPRIS)

- `config/capture/capture.py` (on demand, exits afterwards; ~86 MB RSS only while the bar is open): opened by Print,
- Video: ffmpeg x11grab (libx264 ultrafast, zerolatency, 2 threads, 20 fps; ~68 MB RSS while recording) of full screen /
- `config/osb/mpris.py`: small Gio D-Bus MPRIS client (no new process). QS shows a media card (art if the player gives a
- Test media: `Mijn bestanden/Muziek/TEST-sinustoon-440Hz.ogg` (ffmpeg sine, titled "Testtoon 440 Hz (TEST)"), played by
- Screenshots: 42-capture-bar, 43-capture-region, 44-recording, 45-media-qs-light, 46-media-qs-dark, 47-lock-media-dark

## Rev 19: Sneltoetsen (keyboard shortcut overview)

- `config/wm/shortcut_table.py` is the single source: `keyd.py` now builds its X grabs from `KEYD` (sym + modifiers →
- Viewer: rounded centred window (backdrop = real screen grab), left nav Populair / Vensters en bureaus / Systeem /

## Rev 20: desktop right-click menu

- xfwm4 owns ButtonPress on the root window, so the shelf process (`shelf/shelf.py`) now also owns a full-screen

## Rev 21: first bootable ISO (Debian live-build, trixie amd64)

- Our code in `/usr/share/polderos/config` (+ VERSION). The session copies it per user to `~/.local/share/polderos`
- `/usr/share/xsessions/polderos.desktop` → `/usr/share/polderos/polderos-session`: no Xvfb, no test account, no samples,
- LightDM with our greeter (`/usr/share/xgreeters/polderos-greeter.desktop`), user-session + autologin-session = polderos.
- Live user: `polder`, password `live` (live-config default), autologin. Boot params: nl_NL locale, us keyboard, Europe/Amsterdam.
- Branding: /usr/lib/os-release NAME="Polder OS" VERSION="0.20" ID=polderos ID_LIKE=debian; GRUB boot menu (BIOS+EFI)
- Installer: calamares + calamares-settings-debian, branding.desc rebranded to Polder OS (Debian slideshow still).
- Removed vs. prototype: poldertest user, sample files, Spotify.
- ISO: `iso/build/polderos-0.20-amd64.hybrid.iso`, 1,055,830,016 bytes (1.06 GB),

## Rev 22: Polder Store (software center)

- Catalog: AppStream pool (Debian DEP-11 + Flathub appstream). Only DESKTOP_APP components with a real icon file and a
- Pages: Ontdekken (Uitgelicht + category chips + grid), search (AppStream search), detail page (icon, summary, developer,
- Backends: Debian packages through PackageKit (PackageKitGlib on the system bus → polkit authorisation like any distro);
- ISO: packages packagekit packagekit-tools appstream gir1.2-packagekitglib-1.0 gir1.2-appstream-1.0 gir1.2-flatpak-1.0
- Box-only: the container has no system bus/polkitd → start-session.sh starts `dbus-daemon --system` and polkitd via sudo,
- Tested on :55: home, search 'mines'/'xournal', detail, Installeren gnome-mines via PackageKit (progress bar, notification,

## Rev 23: rounded app windows (picom)

- `config/picom.conf`: xrender backend, corner-radius 12, subtle shadows (radius 16, opacity 0.22). Excluded from corner
- Enabled in `config/start-session.sh` (:55) and `iso/src/polderos-session` (ISO; not rebuilt per user request).
- Screenshots of composited output must use `ffmpeg -f x11grab` (ImageMagick `import -window root` shows uncomposited pixels).
- Verified on :55: Thunar + Instellingen rounded, shelf/QS/notification stack draw normally with picom running (66-rounded-windows.png).
- ISO VM check (existing 0.20 ISO, picom started by hand from tty2 with the same exclusions as inline options, xrender):

## Rev 24: Welkom bij Polder OS (eerste start)

- `config/welcome/welkom.py` (Python/GTK3, Dutch, palette light+dark, rounded by picom): 7 steps with progress dots and Volgende / Terug / Overslaan:
- Finishing, Overslaan or Escape sets `welcome_done: true` in `~/.config/osb/settings.json`. `--first-run` exits immediately when done.
- Launched by `start-session.sh` and `iso/src/polderos-session` (`welkom.py --first-run`, 6 s after session start). Re-open: Instellingen › Over › "Welkom bij Polder OS", launcher search "welkom".
- Screenshots: 68-welcome-start, 69-welcome-theme (dark applied live from the tour), 70-welcome-done.

## Rev 25: Polder Weer + webapps

- `config/weather/weather.py`: Open-Meteo forecast + geocoding (free, no key; best_match uses KNMI HARMONIE for NL). Cache `~/.cache/osb/weather.json`; data older than 2 h or a failed fetch = "unavailable" (never …
- Fetched by `osb-settingsd.py` every 30 min and right after the location changes; it then sends SIGUSR1 to tint2 so the pill updates.
- Shelf: tint2 executor `render-status.sh weather` (Papirus `weather-*-symbolic` icon + "12°") left of the date pill; prints nothing (pill hidden) without fresh data.
- Click: `cal.py --weather` = calendar popup with a weather card on top (`weather/wxcard.py`): now, description, feels-like, wind in Bft + direction, rain chance, rain next 2 h (minutely_15 bars or "Droog de komende …
- Instellingen › Weer: current location (default Amsterdam), status/last update, city search (Open-Meteo geocoding, Dutch names) → `weather_loc` in settings.json.
- `config/webapps/webapps.py` (install/list/remove, CLI too): icon comes from the site itself: Web App Manifest (largest) → apple-touch-icon / `<link rel=icon>` → `/favicon.ico` (largest .ico frame), saved as 128 px …
- Creates `$XDG_DATA_HOME/applications/polder-webapp-<id>.desktop`: `chromium --user-data-dir=~/.config/polder-webapps --app=URL --class=PolderWebApp-<id>`. All webapps share one profile, which is separate from the …
- Window matching: Chromium names `--app` windows with WM_CLASS instance `<host>` or `<host>_<path with / → _>` (`music.youtube.com`, `outlook.live.com__mail`). That is the StartupWMClass. The `--class` only takes …

## Rev 26: automatic updates

- ISO: `unattended-upgrades` (security + stable updates, nightly via apt-daily timers, never auto-reboots) and `polder-flatpak-update.timer` (daily `flatpak update --system`).
- `config/osb/updates.py`: shared logic. `osb-settingsd` watches `/var/run/reboot-required` and sends the notification "Opnieuw opstarten om bij te werken" with the action "Nu opnieuw opstarten"; it also writes `/tmp/osb-update.json`.
- Indicators: an up-arrow on the shelf time pill and an "Update" pill in the Quick Settings header (reboot only on the ISO).
- Instellingen › Over › Updates: automatic-updates toggle (root helper `polder-autoupdate` via pkexec + polkit policy), last update (unattended-upgrades log or apt history), "Nu controleren" (PackageKit refresh + update count, plus Flatpak count), link to Polder Store › Updates (`store.py updates`).

## Rev 27: polder-shell (merged services)

- `config/shell/polder-shell.py`: notifications, shelf (+ desktop window), launcher, clipboard history, settings daemon and hotkeys (keyd) run in ONE process with one GTK main loop. settingsd and keyd run in threads; their actions reach the main loop via `GLib.idle_add`.
- Each module starts in its own try/except; thread modules are restarted after a crash. The session scripts run a supervisor loop that restarts polder-shell; `POLDER_SHELL=0` starts the old separate processes.
- One IPC channel replaces the per-process SIGUSR1/SIGUSR2 toggles: unix socket `osb/shellipc.py` with `launcher | clip | clip-clear | notify-reload | ping`. Callers updated (`launcher-toggle.sh`, `clip-toggle.sh` with fallback, keyd, Instellingen, apply.py).
- Memory (PSS): 175 MB for the six Python services → 61–72 MB for polder-shell (184 → ~75 MB including tint2 + picom).

## Rev 28 – Telefoonkoppeling (KDE Connect)
- `kdeconnectd` (package `kdeconnect`, no recommends) starts with the session (~41 MB PSS); firewall: open 1714–1764 TCP/UDP.
- Instellingen › Telefoon: devices from the daemon over D-Bus (`osb/phone.py`), Koppelen/Accepteren with verification key, paired card with battery, feature toggles (meldingen, klembord, bestanden, batterij, telefoon zoeken), ring.
- QS 'Telefoon' tile with battery %, only when a phone is paired. Thunar action 'Naar telefoon sturen'.
- Tested without a phone only (empty state, daemon, D-Bus); pairing/notifications/clipboard/sharing untested.

## Rev 29: Polder Assistent

- **Super+A** opens the assistant panel (polder-shell module, standalone fallback)
- Offline Dutch/English intents that really act: theme, apps, calendar, volume, brightness, wifi, bluetooth, niet storen, lock, screenshot, weather, file search
- Instellingen › Assistent: optional OpenAI / Gemini / Claude key (keyring or 0600 file), model, real connection test
- Cloud answers stream and can call the same system actions (confirmation for lock and turning wifi/bluetooth off)

## Rev 29.1: echt afgeronde assistent

- Assistant panel uses a real ARGB window: transparent corners composited by picom over any window (wallpaper-backdrop only as no-compositor fallback)

## Rev 29.2: alle vensters echt afgerond

- Shared `osb/rgba.py`: real ARGB transparent corners for launcher, quick settings/notification centre, calendar/weather, toasts, Alt+Tab, snap preview, clipboard, shortcuts, capture bar and pop-up menus (wallpaper backdrop only as no-compositor fallback)
- App windows stay picom-rounded; audit contact sheet `screenshots/rounding-audit.png`
