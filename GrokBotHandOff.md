# Polder OS handoff to GrokBot

Prepared 14 October 2026. Repository: https://github.com/misterk99/polder-os.
Work branch: `codex/wayland-test-foundation`, based on `76013460f87ff350def04660e66374e3c8c009d1`.
This document accompanies the commit containing the implementation and test tools.

## Read this first

The Wayland integration changes are implemented and have passed native ARM tests.
**The updated ARM ISO is not finished and has not been boot-tested.** Do not
describe this as a completed release or use the old ISO as evidence for the new code.

The user initially requested both CPU architectures, then explicitly narrowed the
work to **ARM64 only**. Do not resume Intel/AMD builds. The user approved WSL2 and
a VM for testing, then asked us to stop if completion was not close. We stopped
the sole active build container and verified that no Docker containers remained
running. No VM or compression job was launched for the new image.

The latest request was to upload the source and create this handoff. It did not
restart the stopped build work. Wait for a request to continue before starting
long builds or VMs. Once asked to continue, the next task is packaging and
validating the ARM image, not another broad feature pass. Keep progress updates
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

## Exact stopping point and local caches

The Windows workspace is `C:\Users\kyle_\Documents\ChatGPT\Polder OS`.
WSL distro: `Ubuntu-24.04`, ARM64, approximately 7.6 GiB RAM, no `/dev/kvm`.
QEMU therefore uses TCG software emulation. A prior normal ARM boot took about
421 seconds to show the desktop; that is not a native performance measurement.

| Local resource | Contents |
| --- | --- |
| Docker volume `polder-build-arm64` | Original cached rootfs `/work/arm-r3-repair/rootfs`; incomplete new `/work/arm-r5-repair` |
| Docker volume `polder-integration-arm64` | Incremental staged source `/work/source`, plain compositor `/work/build/polder-comp` |
| Docker volume `polder-scenefx-arm64` | SceneFX installation `/work/install` and earlier `/work/compositor-fx`; rebuild final source |
| Images `polder-test:integration-arm64`, `polder-live-test:integration-arm64` | SDK and GUI test runtime with wlr-randr |
| `.polder-test/iso-arm64/R5-STOP-CHECKPOINT.md` | Detailed stopped-build record |
| `.polder-test/iso-arm64/grub-stage-r5.sh` | Local cache-repack preparation script; not a portable clean-build entry point |
| `.polder-test/capture-portal/portal-final-r3-install` | Exact tested portal binary, activation files and provenance |

The only active container, `polder-arm-r5-stage`, was stopped. It exited 137
during initial staging/base-rootfs copying; its log contains only `START`.
**Treat the r5 source/rootfs as incomplete.** No r5 squashfs, ISO or verification
result completed. The local staging script refuses an existing repair directory;
do not run it blindly or delete the original cache. Inspect and preserve the
partial state, then choose a fresh revision directory or resume verified steps.
The explicit `libsystemd-dev` dependency was added after that snapshot began.

The old image is
`.polder-test/iso-arm64/polderos-0.30.1-wayland-dev-arm64-r4.hybrid.iso`, SHA-256
`79140e0e52588ac35d011bd1d35c62209533416faf156ff71124dd47d1c498a6`.
Its kernel/initramfs matched the previously UEFI-booted r3 image and its config
was verified separately. **It does not contain this handoff's new features.**
The exact tested portal executable SHA-256 is
`38cf7b48d51a4cb17eb00d16389253633c11c5a20d7d39a8f8df3c4aab19ec18`.

## Where to pick up after a request to continue

1. Read this handoff, inspect Git status and available ARM caches. Use the final
   committed source, including the last lock, preview-watchdog and dependency fixes.
2. Finish an isolated ARM runtime image. Build/install both compositor variants,
   the patched portal and its activation overrides, wlr-randr, session/config
   files, chooser, and the 15-second logind inhibitor setting. Recompute
   `WAYLAND_CONFIG_VERSION` using `iso/build.sh`'s full-config hash algorithm.
3. Verify runtime libraries and exact packaged files, then compress/repack the
   image. With local caches, preserve the previous ISO and rootfs. Check every
   ISO checksum entry, boot metadata, kernel/initramfs and matching module tree.
   A clean build is the portable alternative when those local caches are absent.
4. Boot the new ISO through normal UEFI/GRUB in an ARM VM. Run the serial probe
   and desktop exercise, then inspect screenshots/logs. The exercise now covers
   launcher, terminal, maximize/close, and live-account lock/unlock. Key delivery
   or a running QEMU process alone is not a pass. Direct-kernel boot is diagnostic
   only and cannot replace normal firmware acceptance.
5. Report the exact image hash, actual results and remaining hardware limitations.
   Do not silently add AMD work, install onto a real disk, or publish a release.

Commands below are for Linux/WSL from the repository root, **after resumption is
requested**. They can take substantial time; do not run all of them just to
recreate already-valid evidence. Use two build CPUs on this host.

```sh
# Portable headless regression suite (rebuilds the SDK if needed).
POLDER_ARCH=arm64 bash tools/test-linux.sh headless

# Portable ISO build; live-build uses a disposable privileged container.
POLDER_ARCH=arm64 POLDER_BUILD_CPUS=2 \
  POLDER_TEST_OUTPUT="$PWD/.polder-test/iso-arm64-next" \
  bash tools/test-linux.sh iso

# Normal firmware boot of the NEW image; replace the path with the actual output.
POLDER_ARCH=arm64 POLDER_VM_SECONDS=750 \
  POLDER_VM_PROBE_SESSION=1 POLDER_VM_EXERCISE_SHELL=1 \
  POLDER_TEST_OUTPUT="$PWD/.polder-test/vm-arm64-next" \
  bash tools/test-linux.sh vm /absolute/path/to/new-arm64.iso
```

Use `--help` on `test-settings-ui.py`, `check-wayland-lock.py`,
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

- Final source still needs an FX rebuild and the complete ARM image/VM acceptance above.
- Actual GPU effects, physical monitor hotplug/mixed scaling, and real ARM
  hardware suspend/resume remain unverified.
- ARM images target generic UEFI/QEMU `virt`, not every ARM laptop or board.
  USB boot, device-specific firmware/drivers and installer disk tests are unverified.
- Browser-specific sharing, GPU capture and audio recording were not validated.
- IME/text-input integration and native night light are not implemented. The
  unsupported Wayland night-light tile is hidden. Brightness appears when a
  hardware backlight is available.
- Source/tests are published on the work branch; no merge or release is implied.
