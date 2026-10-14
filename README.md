# Polder OS

**NL** – Polder OS is een ChromeOS-geïnspireerde Linux-distributie op basis van Debian 13 (trixie). Je krijgt een lichte, Nederlandstalige desktop met eigen plank, launcher, snelle instellingen, agenda, weer, vergrendelscherm, software-winkel en webapps, maar dan als volwaardige Linux met apt en Flatpak.

**EN** – Polder OS is a ChromeOS-inspired Linux distribution built on Debian 13 (trixie). It has a lightweight desktop (xfwm4 + picom + its own Python/GTK3 components) with a Dutch UI, light and dark themes, and real Linux underneath (apt + Flatpak).

| | |
|---|---|
| ![Desktop](screenshots/31-wallpaper-day.png) | ![Dark theme](screenshots/32-wallpaper-night.png) |
| ![Launcher search](screenshots/28-search-apps.png) | ![Polder Store](screenshots/62-store-home.png) |
| ![Weather + calendar](screenshots/72-weather-popup.png) | ![Welcome app](screenshots/68-welcome-start.png) |

## Features
- Shelf with pinned/running apps, right-click menus, status pills (keyboard, weather, date, time/notifications)
- Launcher with live search: apps, settings, files, calculator, web, "installeer <url> als app"
- Quick Settings (Wi-Fi, volume, dark theme, night light, Do not disturb, media card)
- Notification center (freedesktop daemon, actions, history, badge)
- Calendar popup with real iCal feeds (RRULE/timezones) and weather from Open-Meteo
- Instellingen (Settings) app: theme/accent/wallpaper, notifications, calendars, keyboard, weather, webapps
- Overview + Alt+Tab, window snapping and split view, virtual desks
- ChromeOS-style lock screen (PAM) and LightDM greeter
- Screen capture bar (screenshot/video), clipboard history (Super+V), keyboard shortcut viewer (Ctrl+Alt+/)
- Polder Store: software center for Debian (PackageKit) and Flathub (Flatpak) apps
- Webapps: install any site as its own app with its real icon
- "Welkom bij Polder OS" first-run tour; rounded windows via picom
- Light: all always-running services in one `polder-shell` process (~70 MB PSS)
- Automatic updates (unattended-upgrades + Flatpak timer) with a reboot notification
- Bootable live ISO (Debian live-build) with Calamares installer

## Quick start: prototype session
Needs Debian trixie. The code expects to live at `/workspace/osbuilder` (the ISO build rewrites the paths):
```
git clone https://github.com/misterk99/polder-os /workspace/osbuilder
/workspace/osbuilder/config/start-session.sh     # installs deps, starts Xvfb :55 and the session
```
View `:55` with a VNC/X viewer, or grab it: `ffmpeg -f x11grab -i :55 -frames:v 1 shot.png`.

## Build the ISO
```
sudo apt install live-build qemu-system-x86
cd /workspace/osbuilder/iso
sudo ./build.sh          # → build/polderos-0.30.1-amd64.hybrid.iso (~1 GB)
./test-qemu.sh           # boot it in qemu
```
Live user: `polder` / `live` (autologin). See [CHANGELOG.md](CHANGELOG.md) for the full development log.
The commit history was reconstructed from the development log; intermediate file states were not preserved.

## ARM64 package updates

ARM64 development images install the compositor, desktop, and settings from
versioned Debian packages. Polder's APT archive is designed as a signed overlay
alongside Debian's repositories, so Polder fixes can be delivered as package
updates. See [the package and repository guide](docs/package-updates.md) for
build, verification, key setup, and publishing instructions. The hosted
archive is configured for GitHub Pages and will be populated by the first
successful manual publishing run after the package workflow reaches `main`.

## Wayland development and testing

The released 0.30.1 image uses X11. Current development also includes `polder-comp`,
a wlroots 0.18 compositor, and shared GTK3 components with Wayland paths. The
optional Wayland development image is not a replacement for the tested release.

Run the test tools from Linux or WSL2 with Docker available:

```sh
bash tools/test-linux.sh headless
POLDER_ARCH=amd64 bash tools/test-linux.sh iso
POLDER_ARCH=arm64 bash tools/test-linux.sh iso
POLDER_ARCH=arm64 bash tools/test-linux.sh vm /absolute/path/to/polderos-0.30.1-wayland-dev-arm64.hybrid.iso
```

- `headless` builds against Debian 13 libraries and runs real native Wayland
  clients without using your desktop. It checks input focus, minimize/restore, maximize/restore,
  desktop switching and movement, desktop deletion, screen capture and preview
  pixels. A failed assertion returns a nonzero status.
- `iso` uses a disposable **privileged** Docker container because Debian
  live-build needs mount/chroot. The source checkout is mounted read-only; the
  build runs in a reusable Docker volume (`polder-build-amd64` or
  `polder-build-arm64`) to retain downloaded packages. Building another CPU
  architecture needs working binfmt/QEMU emulation. Package signature
  verification stays on.
- `vm` runs the selected QEMU guest using software emulation, with no host disks,
  shared folders, network, or installation disk. It lets the boot menu start
  automatically and records ten minutes of screenshots and logs. This is evidence for
  visual review, **not an automated desktop pass**. Use the existing interactive
  `iso/test-qemu.sh` on an x86 Linux host for longer sessions and input testing.

Artifacts are stored under `.polder-test/` (ignored by Git). Set
`POLDER_TEST_OUTPUT` to choose an output directory and `POLDER_BUILD_CPUS` to
change the ISO build's four-core CPU limit. The tools handle Windows line
endings in a staged source copy. `POLDER_ARCH` selects `amd64` (Intel/AMD) or
`arm64`; the wrapper defaults to the host architecture. Both headless and ISO
builds use that target architecture; the VM runner itself stays native. An ARM
pass does not establish x86 binary compatibility or GPU performance.

The AMD64 image supports BIOS and UEFI. The ARM64 image targets generic UEFI
optical boot and QEMU's `virt` platform; ARM USB boot is not yet validated.
ARM boards and laptops may require their
own firmware, device trees, kernels, and drivers; these images do not establish
support for every ARM device. The direct `iso/build.sh` command retains amd64 as
its default and uses separate `build/` and `build-arm64/` directories.

Set `POLDER_VM_SECONDS` to change the observation time. If firmware/GRUB boot
stalls, `POLDER_VM_DIRECT_KERNEL=1` extracts the ISO's kernel and initramfs and
boots them with a serial console. This diagnostic bypasses GRUB; a successful
direct boot does not establish that the normal boot menu works.
Add `POLDER_VM_PROBE_SESSION=1` alongside direct-kernel mode to log into the
disposable live guest's serial console as `polder` / `live` and collect scoped
session processes, logs, and portal/audio service states. A missing login or
session reports a diagnostic failure; collected logs still require review.
ARM64 also exposes its serial login with normal UEFI boot, so that path can use
the probe without bypassing GRUB.
With the probe enabled, `POLDER_VM_EXERCISE_SHELL=1` waits for visible screen
content, then opens the launcher and a
terminal, maximizes and closes it, then locks and unlocks the disposable live
account using its documented `live` password. Named screenshots record each
step for visual review; sending a key does not by itself establish success.

For a prepared Debian 13 machine without Docker:

```sh
sudo apt install build-essential meson ninja-build pkg-config libwlroots-0.18-dev \
  libwayland-dev wayland-protocols libxkbcommon-dev libxcb1-dev \
  python3 python3-pil foot wtype grim wlr-randr fonts-dejavu-core
meson setup /tmp/polder-build compositor/polder-comp -Dscenefx=disabled
meson compile -C /tmp/polder-build
python3 compositor/polder-comp/tests/headless-smoke.py \
  --compositor /tmp/polder-build/polder-comp --output-dir .polder-test/headless
```

The optional image can also be built directly with
`sudo env POLDER_ARCH=arm64 POLDER_WAYLAND=1 ./build.sh` from `iso/`. It adds a Wayland session and
selects it for the development image; the greeter also exposes the X11 session.
Direct ISO builds need matching-architecture Debian userspace and the host tools
`live-build debootstrap rsync imagemagick xorriso squashfs-tools dosfstools mtools
isolinux syslinux-common`, plus `grub-efi-arm64-bin` for ARM64. The Docker SDK
provides these. Wayland images assemble boot files outside the runtime chroot so
later package updates cannot separate the boot kernel from its packaged drivers.
Its compositor and shelf helper are compiled inside Debian, with distro GTK
layer-shell/session-lock bindings. SceneFX 0.2.1 is built from a pinned, verified
source archive for rounded corners and shadows. A separate plain compositor is
retained: the session wrapper falls back to pixman only when effects renderer
initialization reports unsupported hardware. `POLDER_EFFECTS=0` selects the plain
compositor explicitly. Window opening has a short fade; Settings offers a live
reduced-motion preference. Maximized windows have no compositor shadow.

The Wayland session now includes native display resolution, scaling, rotation,
and placement controls. An independent 15-second watchdog restores unconfirmed
changes even if Settings exits. Confirmed monitor profiles restore on login and
reconnection. Keyboard layout/variant and idle-lock timeout changes apply live.
Lock acknowledgement waits for the opaque cover to be presented on all active
outputs; explicit sleep waits for acknowledgement, and a crashed locker retains
the compositor's opaque cover while the controller attempts swaylock fallback.

Screenshot, recording, and screen sharing use native Wayland capture. The portal
shows a monitor chooser and requires explicit consent. Debian's 0.7.1 wlr portal
needs a small SHM compatibility patch for software rendering; the verified source,
patch, build helper, and separate activation overrides are in `tools/testing/`
and `iso/src/hooks/0610-polderos-portal.hook.chroot`. The packaged Debian backend
is retained. Reassess this patch when upgrading the portal.

Additional Linux checks are `test-wayland-desktop.py` (output transactions and
live keymaps), `test-settings-ui.py` (actual GTK controls),
`check-wayland-lock.py` (actual lock clients, including two-output coverage),
and `capture-portal-smoke.py` (consent and actual PipeWire frames), all under
`tools/testing/`. The latter tests need the live runtime's GTK/portal packages;
capture frame consumption additionally needs `gir1.2-gstreamer-1.0` and
`gstreamer1.0-pipewire`. Use each script's `--help` for invocation.

Remaining hardware acceptance includes real GPU effects, physical displays and
hotplug, suspend/resume on an ARM device, browser-specific sharing, input methods,
and installer tests on a disposable
disk. Native night light is not implemented; its unsupported Wayland tile is
hidden. Brightness is offered when a hardware backlight exists. Software tests
and QEMU cannot establish hardware compatibility or native GPU performance.

## License
GPL-3.0-or-later, see [LICENSE](LICENSE). The "Polderheuvel" wallpapers are the project's own AI-generated images. Debian packages keep their own licenses.
