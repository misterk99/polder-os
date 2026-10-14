# Polder OS development log

Updated 14 October 2026. Repository: <https://github.com/misterk99/polder-os>.
This records completed work, validation and remaining limitations. The original
filename is retained so existing references keep working.

## Current state

- Development targets ARM64. Intel/AMD work was explicitly deferred.
- Wayland integration and the package-update infrastructure are merged into
  `main` through [PR #1](https://github.com/misterk99/polder-os/pull/1).
- Automatic Store initialization is merged through
  [PR #2](https://github.com/misterk99/polder-os/pull/2).
- Signed revision `0.30.1-1polder2` is published at
  <https://misterk99.github.io/polder-os/apt/> for Debian trixie ARM64.
- The local Windows ARM64 VM has that revision installed. Its timer refreshed
  Debian and Flathub catalogs automatically after the upgrade.
- Source, build/test scripts and this log are on GitHub. Large ISOs, VM disks,
  raw screenshots/logs and caches remain local. Private signing material is
  excluded from the repository and images.
- The public `v0.30.1` ISO release from 12 October predates these changes. A new
  public Wayland ISO release has not been published.

## Wayland desktop integration

Implemented and tested during 13–14 October 2026:

| Area | Completed work and main files |
| --- | --- |
| Session | `iso/src/polderos-wayland-session` initializes user configuration; `polderos-wayland-components` supervises desktop services. The optional Wayland image selects this session and retains the X11 greeter choice. Runtime files are scoped to the session. |
| Displays | `compositor/polder-comp/polder-comp.c` supports output configuration, validated apply/rollback, fractional scaling and per-monitor work areas. `config/osb/wayland_display.py` stores profiles and supplies an independent 15-second preview watchdog. Settings exposes resolution, scale, rotation and placement. |
| Keyboard/settings | Physical layouts apply live without replacing virtual keyboards' own maps. `wayland_control.py`, `apply.py` and `osb-settingsd.py` connect Settings to the compositor. Reopening Settings focuses the existing window and selects the requested page. |
| Lock/sleep | `config/lock/lock-session.py` brokers acknowledged locking and GTK-to-swaylock fallback. Acknowledgement waits for an opaque cover on every output. Failed lockers leave the compositor cover intact. Idle settings reload live; suspend waits for lock acknowledgement. |
| Capture/sharing | `config/capture/capture_backend.py` manages screenshots, clipboard and recording. `portal-chooser.py` requires monitor selection/consent. The patched portal supports software rendering. |
| Appearance | Window-opening fade, live reduced-motion preference, and maximized windows without shadows/rounding. The wrapper selects a separate plain renderer when effects initialization is unsupported. |
| Build/test | `tools/test-linux.sh` supplies ARM-aware Docker headless, ISO and VM workflows. Staging normalizes Windows line endings. Image assembly preserves matching kernel, initramfs and modules. |

Specific regressions fixed:

- Display rollback waits and retries when blocked by the lock screen.
- New virtual keyboards receive an initial keymap only while their own map is
  absent, preventing invalid-keymap locker crashes.
- The GTK lock window no longer requests the whole virtual desktop as its
  minimum size on unequal monitors.
- Lock acknowledgement waits for output presentation. Locked emergency shortcuts
  cannot terminate the compositor, and output reconfiguration is refused while locked.
- Launcher toggles use GLib's idle loop to avoid stalling GTK.
- Clipboard capture no longer leaves `wl-copy` holding subprocess output pipes.
- Portal tests change visible content and compare distinct captured frames;
  process liveness alone is not treated as successful sharing.

## Versioned packages and signed updates

Added a Debian source package producing:

| Package | Contents |
| --- | --- |
| `polder-compositor` (`arm64`) | Plain/effects compositors, toplevel helper, wrapper and private SceneFX library. |
| `polder-desktop` (`all`) | Sessions, shared desktop/configuration, policies and update services. |
| `polder-settings` (`all`) | Settings application with a matching desktop version dependency. |
| `polder-archive-keyring` (`all`) | Public archive key and an APT source restricted with `Signed-By`. |

`debian/changelog` controls package versions. Debian repositories stay enabled;
Polder's signed archive adds Polder packages alongside them. Desktop version
stamps refresh generated user configuration on the next login. The Polder origin
is included in unattended-upgrade configuration.

`tools/packages/` provides unprivileged package builds, disposable-key tests,
repository generation, signature verification, dependency checks, and binary/source
download checks. The workflow runs on Debian trixie ARM64 for PRs and `main`.
Production publication is a separate manual dispatch with `publish: true`.

GitHub Pages and the Actions secret `POLDER_REPO_SIGNING_KEY` are configured.
The production public-key fingerprint is
`6315578A738FA4D818C9E64194B6C90A22001AFF`. Only the public key enters packages.
The SceneFX archive verification issue in CI was corrected; subsequent ARM64
build, archive verification and publication runs passed.

| Revision | Verified publication |
| --- | --- |
| `0.30.1-1polder1` | Initial signed set; [production run 38557184389](https://github.com/misterk99/polder-os/actions/runs/38557184389) passed. |
| `0.30.1-1polder2` | Store initialization; [PR validation 38579227400](https://github.com/misterk99/polder-os/actions/runs/38579227400) and [production run 38579535677](https://github.com/misterk99/polder-os/actions/runs/38579535677) passed. |

The revision 2 public `InRelease` signature and package-index checksum were
checked again on 14 October. See [the package guide](docs/package-updates.md)
for build, bootstrap, publication and key rotation. The custom portal backend
remains an ISO payload, outside this initial Debian package set.

## Automatic Polder Store setup

The Store initially appeared empty because Debian app-icon indexes and the native
Flathub catalog were not initialized. An immediate VM repair was followed by a
packaged fix so users do not need terminal setup commands.

Revision `0.30.1-1polder2` adds:

- `/usr/libexec/polder-store-catalog-refresh`: fixed metadata-only commands for
  Debian indexes, AppStream cache and native Flathub catalogs, with locking,
  bounded timeouts, status reporting and failure retries.
- `60polder-store-appstream`: enables Debian app-icon downloads.
- `polder-store-catalog.service` and `.timer`: automatic boot/periodic refresh
  and failure retries. Installation starts timers asynchronously so network work
  cannot block its own package upgrade.
- A polkit rule for active local sessions to start only the fixed refresh unit.
- Loading/retry messages, reload while open, and cached apps retained offline.
  Missing artwork no longer hides installable apps.
- Correct remote-icon URL handling and a queued reload when metadata changes
  during an existing load.
- ISO build wiring to preload catalogs and enable the same runtime fallback.

| Native ARM64 check | Result |
| --- | --- |
| Focused tests | All 17 passed; included in package CI. |
| Real clean GTK/AppStream/Flatpak runtime | Open Store went from zero apps to 4,846 Debian/Flathub apps without restarting. Screenshots inspected. |
| Offline behavior | Simulated refresh failure retained all 4,846 cached apps and showed retry status. |
| Package build | Revision 2 built. Payload permissions, icon configuration and generated timer-only installation starts checked. |
| Running VM upgrade | All four packages upgraded through the public signed feed. Timer enabled/started automatically; helper exited 0 with all sources `ready`. |
| VM catalog | 4,883 installable desktop components, including 2,896 Flatpak components, present at verification. Upstream catalog counts vary. |

Current-session Store files were updated after confirming they matched the old
package defaults and the Store was closed. Ordinary desktop upgrades refresh
generated configuration on the next login. The base ISO was not rebuilt for this
fix; clean-start validation used an isolated ARM64 runtime instead.

Evidence: `.polder-test/store-catalog-tests/unittest.log` and
`.polder-test/store-catalog-check/` contain tests, screenshots, package inspection
and VM upgrade/refresh logs. Debian's broad `sudo_on_live.rules` also applies in
the live VM, so unrelated-unit denial could not be established using that account.
The new fixed-unit rule was reviewed separately.

## Local Windows ARM64 VM

Created a persistent development VM on the Surface Laptop 7/Snapdragon X host:

| Item | Configuration / verified behavior |
| --- | --- |
| Location | `C:\Users\kyle_\Virtual Machines\Polder OS ARM64` |
| Start | Windows desktop shortcut `Polder OS ARM64`; launcher `Start-Polder.ps1`. |
| Runtime | QEMU 11.1.2 ARM64 using Windows Hypervisor Platform hardware acceleration. |
| Resources | Four virtual CPUs, 4 GB RAM, 24 GB growing persistence disk; private NAT networking. |
| Persistence | Saved marker survived normal shutdown and relaunch. `persistence.qcow2` contains saved changes. |
| Desktop | Visible Wayland session and usable startup display verified; user confirmed it works. |
| Updates | Signed Debian/Polder APT access and revision 2 upgrade verified. Store apps visible, confirmed by the user. |
| Graphics | Mesa llvmpipe software rendering. Maximized startup, initially paused, establishes usable virtual monitor dimensions before resuming. |

Base `Polder-ARM64.iso` SHA-256:
`95b1a6e1e8ac60061f4123e803184803276ee5ccf4f53022dccd2e99319be8de`.
Revision 2 resides in the persistence overlay. The development live account is
`polder`, password `live`. `README.txt`, `verification.json`, launch arguments,
screenshots and serial logs are saved beside the VM. No host folders or physical
disks are shared.

Live resolution changes were rejected by the virtual display backend; resizing
the QEMU window scales the view. This local VM is separate from a public release;
its disk and screenshots are not in Git.

## Earlier ARM64 test and image evidence

Native Linux integration results from 13 October remain under ignored
`.polder-test/`. Their scope differs from the later Windows VM:

| Check | Result | Evidence relative to `.polder-test/` |
| --- | --- | --- |
| Syntax | 68 Python and 17 shell files passed. | `integration-arm64/final-source-checks.log` |
| Core compositor | 31 checks passed: clients, focus, desktops, window state and screenshot pixels. | `integration-arm64/final-checks.log` |
| Display/keyboard | 16 checks passed: maps, scaling, placement, rollback and saved profiles. | `integration-arm64/keyboard-regression.log` |
| Settings GUI | Four checks passed using actual GTK controls. | `integration-arm64/settings-w9adywpt/ui-report.json` |
| Lock integration | 15 checks passed: unequal monitors, PAM, fallback and deferred rollback. | `wayland-lock-preview-final/report.json` |
| Capture/portal | Eight checks passed: PNG/clipboard, finalized video, consent and changing PipeWire frames. | `capture-portal/final-r4/report.json` |
| Renderer fallback | Five no-DRM checks passed, including a visible terminal and typed input. | `scenefx/fallback-final/report.json` |
| Unit regressions | Session/settings, VM probe, lock, capture, wrapper and display-watchdog tests passed. | `integration-arm64/final-checks.log`, `final-source-checks.log` |
| Full native session | Desktop/shelf and launcher open/hide/reopen visually checked. | `session-integration/` |

The r6 rootfs built both compositors and the patched portal against Debian trixie
with kernel `6.12.111+deb13-arm64`. The image verifier checked hashes, UEFI metadata,
squashfs, manifests, runtime/config payload and kernel/modules.

| Historical image | SHA-256 |
| --- | --- |
| `iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6.hybrid.iso` | `8737cb0713ef44055fab83e8bf1b9f403e57b500eeb1be535780326081831e91` |
| Serial test copy, `iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6-qemu-serial-test.iso` | `672dd28c4bf4a90c7974baf014a9588fe1a81dc957b508c3b51c9292b352e47d` |

The 1,800-second ARM64 QEMU TCG run completed firmware/GRUB boot, live login,
Wayland readiness, visible desktop and terminal open/maximize/restore. Its final
QMP snapshot showed the VM running. Launcher activation and the exact lock/unlock
transition were inconclusive in those screenshots. Evidence is in
`.polder-test/vm-arm64-r6-interaction/`; image verification is in
`.polder-test/iso-arm64/r6-verification.txt`. TCG timing is not native performance.
The serial copy is instrumentation and remains distinct from other images.

## Dependency and build records

- SceneFX 0.2.1: commit `87c0e8b6d5c86557a800445e8e4c322f387fe19c`,
  archive SHA-256
  `8bca18dd0a082a064042ecd9b77de17cf729d398d2ba0c703bd672fb9b39c109`,
  against Debian wlroots 0.18.2. Subsequent package builds rebuilt plain and
  effects binaries. Their scene implementations remain separate; fallback is
  restricted to unsupported-initialization exit status 78.
- The xdg-desktop-portal-wlr 0.7.1 patch supports SHM-only software capture and
  fixes zero-refresh/max-FPS behavior. Archive SHA-256:
  `4bddc236aa9d1a2b33e7f0bef09a8712ded51e8bc335a2b6c8cd1d088863e676`.
  Reproduction: `tools/testing/build-capture-portal.sh`, adjacent patch, and
  `iso/src/hooks/0610-polderos-portal.hook.chroot`. Reassess on portal upgrades.
- Local volumes include `polder-build-arm64`, `polder-integration-arm64` and
  `polder-scenefx-arm64`. Historical r5 staging was incomplete and superseded by
  r6; it is not a clean-build starting point.
- WSL `Ubuntu-24.04` is ARM64 and lacked `/dev/kvm`, so earlier tests used TCG;
  the later Windows VM uses WHPX. WSL previously refused connections under load
  with `0x8007274c`; caches/evidence were preserved.
- Use `tools/testing/` as the Docker SDK build context. `.polder-test/` contains
  large artifacts; a clone does not include local images, evidence or caches.

Commands and focused test entry points remain in [README.md](README.md),
[the package guide](docs/package-updates.md) and `tools/testing/`. No image builds
or application tests were repeated solely to update this documentation.

## Remaining limitations

- Hardware GPU effects, physical monitor hotplug/mixed scaling, and actual ARM
  suspend/resume are unverified. Container PAM tests do not establish physical suspend.
- ARM images target generic UEFI/QEMU `virt`. Device-specific firmware/drivers,
  USB boot and installer disk behavior remain unvalidated on laptops or boards;
  a working VM does not establish native Surface boot support.
- Browser-specific sharing, GPU capture and audio recording remain unvalidated.
  Portal testing used a local PipeWire consumer rather than a conference call.
- IME/text-input integration and native Wayland night light are not implemented.
  Unsupported night-light controls are hidden; brightness needs a hardware backlight.
- Older TCG launcher/lock checkpoints remain inconclusive despite separate native
  integration results. The later Windows VM is not acceptance coverage for every interaction.
- The Store fix passed clean ARM64 runtime tests and a signed persistent-VM upgrade.
  An ISO containing revision 2 still needs a separate build/boot check before
  being described as a new tested ISO release.
