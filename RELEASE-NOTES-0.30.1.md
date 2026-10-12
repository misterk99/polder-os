# Polder OS 0.30.1

Een ChromeOS-achtige desktop op Debian 13 (trixie), amd64. Live-ISO met installer (Calamares).

## Nieuw sinds 0.20
- **Polder Assistent** (Super+A): bedient je pc lokaal zonder sleutel (thema, volume, helderheid, wifi, bluetooth, niet storen, apps, agenda, weer, bestanden zoeken, vergrendelen, schermafbeelding). Optioneel een eigen OpenAI-, Gemini- of Claude-sleutel via Instellingen › Assistent; sleutels blijven in de sleutelbos van je pc.
- **Polder Sync**: instellingen, vastgezette apps, webapps, agenda-links en Store-apps synchroniseren via een map (Nextcloud/Dropbox/USB) of een privé GitHub-repo, optioneel versleuteld met een wachtzin. "Herstel van andere pc" in Welkom.
- **Echt afgeronde hoeken** voor alle panelen en vensters (picom + transparante vensters).
- Polder Store, Welkom-rondleiding, Polder Weer, webapps, automatische updates, telefoonkoppeling (KDE Connect) en polder-shell (alles in één lichte dienst).

## Fixes in 0.30.1
- Zoeken in de launcher vindt nu ook de instellingen Weer, Webapps, Telefoon, Assistent en Sync.
- De assistent verdwijnt nadat hij een app heeft geopend.

## Bekend
- Getest in qemu (virtuele machine); nog niet op echte hardware.
- Het opstartmenu wacht op Enter.

Controleer de download met `sha256sum -c SHA256SUMS`.
