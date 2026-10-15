# Polder SafeHarbor: the OS that saves itself

SafeHarbor makes a **herstelpunt** (snapshot) of the system before every software change and lets you go back with one
click, or pick an earlier version from the boot menu if Polder OS no longer starts.

It is built from standard Debian parts: btrfs, snapper, GRUB, plus grub-btrfs 4.13. grub-btrfs is vendored in
`safeharbor/vendor/grub-btrfs`, unmodified, GPL-3.0, because it is not in trixie. Polder adds its own pieces on top:

| Part | File(s) | What it does |
|---|---|---|
| apt hook | `safeharbor/apt/80polder-safeharbor`, `apt-pre`, `apt-post` | `DPkg::Pre-Install-Pkgs` (VERSION 3) counts what dpkg is about to change and creates a snapper *pre* snapshot ("Voor update: 12 pakketten", "Voor verwijderen: 2 pakketten", "Voor automatische Polder-update: 1 pakket"); `DPkg::Post-Invoke` creates the paired *post* snapshot and applies the retention policy. Runs for apt, Polder Store/PackageKit and unattended-upgrades. Packages named `polder*` mark the snapshot `important=yes`. Replaces snapper's own `80snapper` hook (`DISABLE_APT_SNAPSHOT=yes`). A failing snapshot never blocks an update. |
| helper | `safeharbor/helper/polder-safeharbor-helper` | root helper behind polkit (`org.polderos.safeharbor`): status, create, rollback, delete, set-retention, set-auto, ack-failed-boot, reboot. JSON out. |
| GUI | `shell/polder-shelf/src/bin/polder-safeharbor.rs` | Rust/GTK4 app: list, "Herstel naar deze versie", reboot prompt, banners, Instellingen tab, `--check` notifications. |
| Settings | `config/settings/instellingen.py`, section *SafeHarbor* | status, auto on/off, retention, "Openen". |
| boot menu | `safeharbor/grub/grub-btrfs-config` + vendored `41_snapshots-btrfs`, `grub-btrfsd` | submenu **"Polder OS - eerdere versies (SafeHarbor)"** with date + description; grub-btrfsd regenerates it when snapshots appear or disappear. |
| read-only boot | `safeharbor/initramfs/hook`, `local-bottom` | booting a snapshot puts a tmpfs overlay over the read-only snapshot, so the system starts normally (changes are lost at reboot). klibc-safe (minbase has no busybox). `systemd/remount-fs-snapshot.conf` keeps systemd-remount-fs from failing on the overlay. |
| boot check | `safeharbor/systemd/boot-check` + 2 units | "did the previous boot finish?" notice (see below). |
| install | `safeharbor/install.sh [DESTDIR]` | installs all of the above into a root filesystem. |

## Required disk layout (for the installer: not done yet, out of scope)

One btrfs partition with **flat** subvolumes at the top level (subvolid 5):

| Subvolume | Mount point | In snapshots? |
|---|---|---|
| `@` | `/` | this *is* the system that gets snapshotted |
| `@home` | `/home` | no: personal files are never rolled back |
| `@snapshots` | `/.snapshots` | no (snapper's store) |
| `@var_log` | `/var/log` | no: logs (and the SafeHarbor boot history) survive a rollback |
| `@cache` | `/var/cache` | no: apt cache etc. |

```
UUID=<fs> /            btrfs subvol=@,compress=zstd:1          0 0
UUID=<fs> /home        btrfs subvol=@home,compress=zstd:1      0 0
UUID=<fs> /.snapshots  btrfs subvol=@snapshots,compress=zstd:1 0 0
UUID=<fs> /var/log     btrfs subvol=@var_log,compress=zstd:1   0 0
UUID=<fs> /var/cache   btrfs subvol=@cache,compress=zstd:1     0 0
```

`/boot` stays inside `@`, so every snapshot carries its own kernel and initramfs and can boot on its own. The snapper
config is `safeharbor/snapper/root` (installed as `/etc/snapper/configs/root`, `SNAPPER_CONFIGS="root"`). Do **not**
run `snapper create-config /`: it would try to create its own `/.snapshots` subvolume inside `@`. The installer has to:
create the subvolumes, write the fstab, run `install.sh`, `update-initramfs -u`, `grub-install`, `update-grub`.
The ESP (UEFI) is a separate FAT partition as usual. With `/boot` on btrfs, GRUB cannot write `grubenv`
(see boot counting).

## Rollback: how it works and why not `snapper rollback`

Debian's GRUB boots `rootflags=subvol=@`. It does not use the btrfs *default subvolume*, which is what
`snapper rollback` switches. So the helper swaps the `@` subvolume itself:

1. mount the top level (`subvolid=5`) at `/run/polder-safeharbor/top`
2. `btrfs subvolume snapshot @snapshots/N/snapshot @new-<time>` (a writable copy)
3. write `/var/lib/polder-safeharbor/rolled-back.json` and an `update-grub` flag into the copy
4. `mv @ @rollback-<time>`; `mv @new-<time> @`. The running system keeps working until the reboot.
5. keep the 2 newest `@rollback-*` backups and delete older ones. They are hidden from the boot menu.

After the reboot, `boot-check ok` sees the flag and runs `update-grub` once. This works on stock Debian GRUB and on
both amd64 and arm64.

"Maak dit de vaste versie" (shown when booted into a snapshot) is the same rollback with N = the booted snapshot.

## Boot counting / failed boot notice

GRUB's own boot counting needs a writable `grubenv`, which GRUB cannot write on btrfs. Polder does it in systemd
instead:

- `polder-safeharbor-boot.service` runs early in sysinit. If `/var/log/polder-safeharbor/boot-pending` still exists,
  the previous boot never got to multi-user, so it writes `failed-boot.json`. It then writes a new `boot-pending`,
  fsynced so it survives a power cut.
- `polder-safeharbor-boot-ok.service` runs after multi-user.target and removes the marker.
- The GUI and `polder-safeharbor --check` (session autostart) show "Het vorige opstarten is niet gelukt", together
  with the hint to use "eerdere versies" in the boot menu.

Limitation: a boot that hangs *before* systemd starts (kernel or initramfs) is not counted until the next boot that
does reach sysinit. There is no automatic fallback to the previous snapshot. That would need GRUB-side counting with
`/boot` on a separate non-btrfs partition, or systemd-boot with boot counting.

## Retention

snapper `number` cleanup: `NUMBER_LIMIT=10` (2–50, set in the GUI or Instellingen) and
`NUMBER_LIMIT_IMPORTANT = limit/2` (snapshots before Polder updates). `NUMBER_MIN_AGE=1800`, so snapshots younger than
30 minutes are never cleaned. Changes go through `snapper set-config`, because snapperd caches the config and does
not see edits to the file. Timeline snapshots are off, and `snapper-boot.timer` is disabled.

## Not available

On systems that are not on btrfs (the live ISO, ext4 installs), without snapper or the config, or when `/` is not `@`,
the helper reports `available: false` with a Dutch reason. The GUI shows "SafeHarbor is hier niet beschikbaar". The
apt hook does nothing. The settings page explains what SafeHarbor needs.

## ARM64 (target: Debian trixie arm64)

Nothing in SafeHarbor is architecture-specific: shell, Python and Rust, with no BIOS assumptions. On arm64, use
`grub-efi-arm64` with the ESP mounted at `/boot/efi`. `grub-btrfs` writes `grub-btrfs.cfg` next to `grub.cfg`, so the
same flow applies. **Not tested on arm64** (see below).

## Testing (2026-10-15, amd64 qemu/KVM, BIOS GRUB)

`safeharbor/tests/`:

- `build-image.sh`: debootstrap trixie minbase, apply the layout, `install.sh`, and build the btrfs image in
  userspace with `mkfs.btrfs --rootdir --subvol`, so the build host needs no btrfs module.
- `vm.sh`: qemu with 1 GB RAM, serial log, QMP and ssh on port 2222.
- `qmp.py`: GRUB screenshots, key presses, hard reset.
- `vmhelper`: runs the real helper inside the VM, so the GUI and Instellingen on the host drive the VM. This stands in
  for pkexec.
- `session.sh`: a headless Polder session for the screenshots.

Screenshots are in `screenshots/safeharbor/`.
