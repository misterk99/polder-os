# Polder OS handoff to GrokBot

Prepared 14 October 2026. Repository: https://github.com/misterk99/polder-os.
Work branch: `codex/wayland-test-foundation`, based on `76013460f87ff350def04660e66374e3c8c009d1`.
This document accompanies the implementation, ARM64 image verifier and current
build/VM results. The source is on this work branch; its latest commit contains
the verifier and this updated handoff.

## Read this first

The Wayland integration changes passed the native ARM tests listed below. The
r6 ARM64 production ISO is built and checksum-verified. The latest test-only ISO
run has completed UEFI/GRUB boot, live login, and Wayland session readiness; a
rendered desktop and terminal open/maximize/restore are visible in reviewed
screenshots. Launcher activation and the precise lock/unlock transition are
still unconfirmed. The 1800-second TCG run completed with the VM active at its
final QMP status query and the session probe collected without error. Check
`.polder-test/vm-arm64-r6-interaction/result.json` for the full report. This is
not a completed release. The production ISO and serial-instrumented test copy
have different hashes; do not treat the test copy as a release artifact.

The user initially requested both CPU architectures, then explicitly narrowed the
work to **ARM64 only**. Do not resume Intel/AMD builds. The user approved WSL2 and
a VM for testing and explicitly asked us to finish the ARM work. The final VM
result and screenshots are recorded below. Next, investigate the launcher
shortcut and lock capture timing with focused tests; do not repeat the full ISO
build or 1800-second run without a code change that requires it. Keep updates
short and concrete; the user has already found the task too lengthy.

## What changed

| Area | Implementation and important files |
| --- | --- |
| Session | `iso/src/polderos-wayland-session` bootstraps the user's configuration; `polderos-wayland-components` supervises the desktop services. The optional Wayland ISO selects this session and retains the X11 greeter choice. Runtime PID/state files are scoped to the session. |
| Displays | `compositor/polder-comp/polder-comp.c` implements output management, validated test/apply/rollback, fractional scale support, and per-monitor work areas. Windows retain their monitor when its position/scale changes. `config/osb/wayland_display.py` provides saved profiles and an independent 15-second preview watchdog. `config/settings/instellingen.py` exposes resolution, scale, rotation and placement. |
| Keyboard/settings | The compositor applies validated physical keyboard layouts/variants live and preserves virtual keyboards' own maps. `wayland_control.py`, `apply.py` and `osb-settingsd.py` connect settings to the compositor. Reopening Settings focuses the existing instance and selects the requested page. |
| Lock/sleep | `config/lock/lock-session.py` brokers acknowledged locking and GTK-to-swaylock fallback. The compositor acknowledges only after an opaque cover is presented on every output and keeps the cover if all lockers die. `idle-wayland.py` reloads idle timeout settings while retaining sleep hooks. `suspend-now.sh` waits for acknowledged locking before requesting suspend. |
| Capture/sharing | `config/capture/capture_backend.py` handles native screenshots, clipboard and recording lifecycle. `portal-chooser.py` requires explicit monitor selection/consent. Shelf and session cleanup use the capture backend. The patched portal supports software rendering. |
| Polish | A short window-opening fade and a live reduced-motion preference were added. Maximized windows have no compositor shadow/rounding. SceneFX is built separately for effects; the session wrapper selects a plain compositor when effects renderer initialization is unsupported. |
| Build/test | `tools/test-linux.sh` supplies ARM-aware Docker headless/ISO/VM workflows. `stage-source.py` normalizes Windows line endings in the Linux copy. ISO boot assembly preserves matching kernel/initramfs/modules. See `README.md`, `iso/build.sh` and the new Wayland hooks/package list. |

## Bugs already found and fixed — preserve these fixes

- A display preview expiring while locked was rejected by output management and
  abandoned. The watchdog now retains its preview lock, reports `restoring`, and
  retries after unlock. This was tested through actual PAM unlock and rollback.
- A newly connected virtual keyboard initially had no keymap. Publishing it to
  the seat sent format 0 and could crash a locker. Give it an initial server map
  only while its own map is absent; later client-supplied maps must remain intact.
- The shared GTK lock UI requested the entire virtual desktop as a minimum size.
  On unequal monitors it committed a buffer larger than one lock surface allowed.
  The Wayland lock window clears that inherited minimum/default size.
- Lock acknowledgement must wait for output presentation, not merely creation
  of lock surfaces. The locked Super+Shift+Escape shortcut must not terminate the
  compositor. Output reconfiguration is refused while locked.
- Launcher showing inside the signal callback could stall GTK. Toggle work is
  dispatched through the GLib idle loop.
- `wl-copy` inherited captured subprocess pipes, making screenshot completion
  hang. The capture backend avoids that pipe lifetime issue.
- A stationary desktop can legitimately produce no new damage-based capture
  frames. Portal tests deliberately change visible content and verify distinct
  received frame hashes; daemon liveness alone is not a sharing test.

## Dependency decisions

**SceneFX:** version 0.2.1, commit
`87c0e8b6d5c86557a800445e8e4c322f387fe19c`, archive SHA-256
`8bca18dd0a082a064042ecd9b77de17cf729d398d2ba0c703bd672fb9b39c109`.
`tools/testing/build-scenefx.sh` builds against Debian's wlroots 0.18.2.
Hook `0600-polderos-wayland.hook.chroot` builds both `polder-comp` and
`polder-comp-fx`. Their scene implementations must not be mixed in one fallback
process. `iso/src/polder-compositor` falls back to the separate pixman executable
only on initialization exit status 78, not after an ordinary runtime crash.
`POLDER_EFFECTS=0` selects the plain build. The final compositor source still
needs a fresh FX build: the last keyboard/display fixes followed the earlier FX test.

**Portal:** Debian's xdg-desktop-portal-wlr 0.7.1 rejects valid SHM-only screencopy
with software rendering. Testing 0.8.0 also rejected that configuration. We kept
0.7.1 with a small compatibility patch, including the zero-refresh/max-FPS fix.
The source archive SHA-256 is
`4bddc236aa9d1a2b33e7f0bef09a8712ded51e8bc335a2b6c8cd1d088863e676`.
`tools/testing/build-capture-portal.sh`, its adjacent patch and
`iso/src/hooks/0610-polderos-portal.hook.chroot` reproduce the build.
It installs `/usr/local/libexec/xdg-desktop-portal-wlr` plus D-Bus and systemd-user
activation overrides, retaining Debian's packaged backend. Explicit build
dependencies include `libpipewire-0.3-dev`, `libinih-dev`, and `libsystemd-dev`.
Reassess the compatibility patch when upgrading the portal.

## Completed validation

These results came from native ARM Linux tests on 13 October 2026. They are
historical results, not a claim that the unfinished ISO passed. Raw logs,
screenshots and cached binaries are local-only under ignored `.polder-test/`;
the test scripts and this summary are in Git.

| Check | Result | Local evidence |
| --- | --- | --- |
| Source syntax | 68 Python files and 17 shell files passed | `integration-arm64/final-source-checks.log` |
| Core compositor | 31 checks passed: real clients, input focus, desktops, minimize/maximize, screenshot/thumbnail pixels | `integration-arm64/final-checks.log` |
| Display/keyboard | 16 checks passed: live maps, invalid-map preservation, scaling, negative placement, crash rollback, saved profiles, monitor retention | `integration-arm64/keyboard-regression.log` |
| Settings GUI | 4 checks passed using actual GTK controls, including raising Settings over another application | `integration-arm64/settings-w9adywpt/ui-report.json` |
| Lock integration | 15 checks passed on two unequal monitors at negative origin, including invalid/successful PAM, relock, crash fallback and deferred display rollback | `wayland-lock-preview-final/report.json` |
| Capture/portal | 8 checks passed with the exact release binary and D-Bus activation: PNG/clipboard, cancellation, finalized video, consent, and five changing PipeWire frames | `capture-portal/final-r4/report.json` |
| Renderer fallback | 5 actual no-DRM fallback checks passed, including a visible foot client and typed input | `scenefx/fallback-final/report.json` |
| Unit regressions | 2 session-settings, 2 VM-probe, 10 lock, 8 capture, 8 wrapper, 1 display-watchdog tests passed | `integration-arm64/final-checks.log`, `final-source-checks.log` |
| Full native session | Desktop/shelf and launcher open/hide/reopen visually checked | `session-integration/` |

All evidence paths in that table are relative to `.polder-test/`. Positive PAM
tests used a disposable container; no host user's password was changed. The
container lacked system logind, so those tests do not establish physical suspend.
The portal test is a real local PipeWire consumer, not a browser conference call.

## r6 ARM64 image and VM results

These are the current packaging results. Build evidence and ISO files are local
only beneath ignored `.polder-test/`; the verifier and this handoff are in Git.
The production image remains separate from the serial-instrumented VM copy.

| Check | Result | Local evidence |
| --- | --- | --- |
| Runtime build | Plain and FX compositor plus the pinned portal payload built for Debian Trixie ARM64; runtime linking and package audit passed. Kernel release: `6.12.111+deb13-arm64`. | `iso-arm64/r6-build-rootfs.log` |
| Production ISO | Repacked from the verified r4 UEFI image with updated root filesystem and manifest; 229 checksum entries; image SHA-256 `8737cb0713ef44055fab83e8bf1b9f403e57b500eeb1be535780326081831e91`. | `iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6.hybrid.iso`, `grub-r6-repack.json` |
| Read-only image verifier | Passed ISO hash, UEFI El Torito entry, squashfs, manifest, runtime/config hashes, kernel/initrd and module metadata checks on both images. | `tools/testing/verify-arm64-iso.py`, `iso-arm64/r6-verification.txt` |
| Serial test copy | Replayed UEFI metadata and appended `console=tty0 console=ttyAMA0,115200` to the primary live GRUB kernel line. Test copy SHA-256 `672dd28c4bf4a90c7974baf014a9588fe1a81dc957b508c3b51c9292b352e47d`; it also passed the image verifier. This is test instrumentation, not the production image. | `iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6-qemu-serial-test.iso`, `r6-serial-test.json` |
| UEFI/GRUB and live login | Passed on ARM64 QEMU TCG using the instrumented copy. Firmware selected the CD, GRUB handed off to the kernel, and the probe authenticated to the live `polder` account. The 1800-second run completed; QMP reported the VM still running at its final status query. | `vm-arm64-r6-interaction/serial.log`, `command.json`, `result.json` |
| Wayland readiness | Passed for session startup: the probe observed `session_ready=true` by about 270 seconds. Its final snapshot was collected without error and found the compositor, shelf, launcher, notifications, clipboard and settings processes. | `vm-arm64-r6-interaction/session-probe-readiness.json`, `session-probe.json`, `serial.log` |
| Visible desktop and interaction | A rendered desktop, panel and first-run welcome wizard are visible by about 390 seconds and remain visible through the final 1770-second capture. The terminal opened, maximized, and returned to the welcome desktop in reviewed screenshots. The launcher checkpoint still shows the welcome wizard, so launcher activation is unconfirmed. Lock-flow screenshots show a `Verifying` state and a later return to the desktop by 600 seconds, but do not clearly capture the locked state; treat lock acceptance as inconclusive. All 18 scripted steps ran, but key delivery alone is not a pass. | `vm-arm64-r6-interaction/desktop-ready.png`, `launcher.png`, `terminal.png`, `terminal-maximized.png`, `desktop-restored.png`, `screen-locked.png`, `screen-unlocked.png`, `boot-0600.png`, `boot-1770.png`, `result.json` |

The VM harness now persists readiness as soon as the signal changes, repeats a
readiness probe every 30 seconds after a completed negative snapshot, records
full process command lines, and keeps `result.json` updated while the run is in
progress or if an exception interrupts it. Its focused socket tests passed
before this run.

The completed VM run confirms firmware/GRUB boot, live login, a ready Wayland
session, rendered desktop, and terminal open/maximize/restore. It does not
confirm launcher activation or a clear lock/unlock pass. QEMU uses TCG, so its
timing is not a native performance measurement. The standard production ISO
has no serial-console kernel arguments; the instrumented copy lets the session
probe observe normal firmware/GRUB boot without changing the production ISO.
Hardware GPU/effects and native ARM device behavior remain untested.

## Exact stopping point and local caches

The Windows workspace is `C:\Users\kyle_\Documents\ChatGPT\Polder OS`.
WSL distro: `Ubuntu-24.04`, ARM64, approximately 7.6 GiB RAM, no `/dev/kvm`.
QEMU therefore uses TCG software emulation. A prior normal ARM boot took about
421 seconds to show the desktop; that is not a native performance measurement.
The latest r6 interaction run completed its 1800-second window. `result.json`
records `status=complete`, QMP `running=true`, and `session_ready=true`; the
final session probe was collected without error. All 18 input/screenshot steps
ran; terminal behavior passed visual review, while launcher activation and the
lock/unlock checkpoint remain inconclusive. Current r6 artifacts are:

| Local resource | Contents |
| --- | --- |
| Docker volume `polder-build-arm64` | Original cached rootfs `/work/arm-r3-repair/rootfs`; incomplete historical `/work/arm-r5-repair`; completed `/work/arm-r6-repair` |
| Docker volume `polder-integration-arm64` | Incremental staged source `/work/source`, plain compositor `/work/build/polder-comp` |
| Docker volume `polder-scenefx-arm64` | SceneFX installation `/work/install` and earlier `/work/compositor-fx`; rebuild final source |
| Images `polder-test:integration-arm64`, `polder-live-test:integration-arm64` | SDK and GUI test runtime with wlr-randr |
| `.polder-test/iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6.hybrid.iso` | Production r6 ARM64 image, SHA-256 `8737cb0713ef44055fab83e8bf1b9f403e57b500eeb1be535780326081831e91` |
| `.polder-test/iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6-qemu-serial-test.iso` | Test-only UEFI/GRUB copy with serial kernel args, SHA-256 `672dd28c4bf4a90c7974baf014a9588fe1a81dc957b508c3b51c9292b352e47d` |
| `.polder-test/iso-arm64/r6-build-rootfs.log` | ARM64 rootfs/compositor/portal build log |
| `.polder-test/iso-arm64/r6-verification.txt` | Fresh read-only verifier results for both r6 ISO files |
| `.polder-test/vm-arm64-r6-serial/` | Normal UEFI/GRUB boot screenshots, serial log and incomplete session diagnostics for the test-only ISO |
| `.polder-test/vm-arm64-r6-interaction/` | Completed 1800-second ARM64 QEMU run: periodic readiness, named shell screenshots, serial log and final QMP/probe report |
| `.polder-test/iso-arm64/R5-STOP-CHECKPOINT.md` | Detailed historical r5 stopped-build record; r5 was superseded by the completed r6 packaging work |
| `.polder-test/iso-arm64/grub-stage-r5.sh` | Local cache-repack preparation script; not a portable clean-build entry point |
| `.polder-test/capture-portal/portal-final-r3-install` | Exact tested portal binary, activation files and provenance |

Historical r5 staging exited 137 during initial copying. **Treat r5 source/rootfs
as incomplete; r6 is built in a fresh repair directory and supersedes it.** Keep
the original cached r3/r4 assets and the partial r5 state. Do not reuse the r5
staging script as the r6 clean-build entry point.

The old image is
`.polder-test/iso-arm64/polderos-0.30.1-wayland-dev-arm64-r4.hybrid.iso`, SHA-256
`79140e0e52588ac35d011bd1d35c62209533416faf156ff71124dd47d1c498a6`.
Its kernel/initramfs matched the previously UEFI-booted r3 image and its config
was verified separately. **It does not contain this handoff's new features.**
The exact tested portal executable SHA-256 is
`38cf7b48d51a4cb17eb00d16389253633c11c5a20d7d39a8f8df3c4aab19ec18`.

## Where to pick up next

1. Preserve `.polder-test/vm-arm64-r6-interaction/` as the final VM evidence.
   `result.json`, `session-probe.json`, serial/session logs, and the named
   screenshots have been reviewed. The ISO and raw screenshots remain local.
2. Launcher activation remains unconfirmed: the `launcher.png` checkpoint shows
   the welcome wizard. Check the actual launcher shortcut/focus behavior and
   repeat only that interaction if needed.
3. Lock behavior is inconclusive: the run showed `Verifying` and then returned
   to the welcome desktop, but the capture named `screen-locked.png` does not
   show a lock screen. Confirm the exact transition with a focused repeat before
   claiming lock/unlock acceptance.
4. Do not rebuild the r6 image unless its source changes or the current hashes
   stop matching. Report the exact production and test-copy hashes and current
   limitations. Do not silently add AMD work, install onto a real disk, or
   publish a release.

Commands below are for Linux/WSL from the repository root. They can take
substantial time; do not run all of them just to recreate already-valid
evidence. Use two build CPUs on this host.

```sh
# Portable headless regression suite (rebuilds the SDK if needed).
POLDER_ARCH=arm64 bash tools/test-linux.sh headless

# Portable ISO build; live-build uses a disposable privileged container.
POLDER_ARCH=arm64 POLDER_BUILD_CPUS=2 \
  POLDER_TEST_OUTPUT="$PWD/.polder-test/iso-arm64-next" \
  bash tools/test-linux.sh iso

# Repeat the normal firmware boot only if a code change requires it. Use a new
# output directory so the completed evidence is preserved.
POLDER_ARCH=arm64 POLDER_VM_SECONDS=1800 \
  POLDER_VM_PROBE_SESSION=1 POLDER_VM_EXERCISE_SHELL=1 \
  POLDER_TEST_OUTPUT="$PWD/.polder-test/vm-arm64-r6-interaction-next" \
  bash tools/test-linux.sh vm "$PWD/.polder-test/iso-arm64/polderos-0.30.1-wayland-dev-arm64-r6-qemu-serial-test.iso"
```

`verify-arm64-iso.py` requires `xorriso` and `unsquashfs`; run it from WSL/Linux
with a native Linux `--work-dir` and sufficient privileges to extract squashfs
device nodes. Use `--help` on `test-settings-ui.py`, `check-wayland-lock.py`,
`check-renderer-fallback.py` and `capture-portal-smoke.py` for focused checks.
They need the corresponding GTK/PAM/portal runtime dependencies; the basic
headless SDK alone is insufficient. Portal frame consumption additionally needs
`gir1.2-gstreamer-1.0` and `gstreamer1.0-pipewire`.

Never use `.polder-test/` as a Docker build context: it contains large ISOs and
captures. The checked-in SDK uses `tools/testing/` as its small build context.
WSL occasionally refused new connections under load with `0x8007274c`; inspect
existing jobs before restarting WSL. Do not stop unrelated programs or delete
caches. A Git clone will not contain the local Docker volumes, raw evidence or ISOs.

## Known limitations

- The r6 FX image's Wayland session readiness, visible desktop, and terminal
  open/maximize/restore are confirmed in ARM64 QEMU TCG. Launcher activation is
  not confirmed and lock/unlock evidence remains inconclusive. The full 1800-
  second VM run completed; its process liveness does not represent native
  performance.
- Actual GPU effects, physical monitor hotplug/mixed scaling, and real ARM
  hardware suspend/resume remain unverified.
- ARM images target generic UEFI/QEMU `virt`, not every ARM laptop or board.
  USB boot, device-specific firmware/drivers and installer disk tests are unverified.
- Browser-specific sharing, GPU capture and audio recording were not validated.
- IME/text-input integration and native night light are not implemented. The
  unsupported Wayland night-light tile is hidden. Brightness appears when a
  hardware backlight is available.
- Source/tests are published on the work branch; no merge or release is implied.
