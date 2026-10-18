# Polder Sluis (Polder Lock)

Polder Sluis lets you "pump dry" a **proefpolder** (a trial polder): a copy-on-write branch of one folder.
In it you can let programs (or yourself) experiment. Nothing lands in the original folder, the **vasteland**,
until you review the changes and choose to take them over ("Overnemen").

Components: `polder-sluisd` (CLI + small notification daemon) and `polder-sluis` (GTK4 app), both in
`shell/polder-shelf`. Data lives in `$XDG_DATA_HOME/polder-sluis` (or `$POLDER_SLUIS_DIR`).

## How it works
- **Branch**: the user-namespace OverlayFS through bubblewrap (`--overlay-src <vasteland> --overlay upper work`).
  Fully unprivileged. No setuid, no root, no fuse daemon.
- **Runner** (`polder-sluisd run <id> [--net] [--terminal] [-- cmd]`): `bwrap --unshare-all --ro-bind / /`,
  with the vasteland path replaced by the overlay. The rest of `$HOME` is its own overlay that is thrown away
  (never merged). The Sluis data dir is hidden. Only the Wayland socket is passed through; DBus and X11 are not.
  Also `--new-session` and `--die-with-parent`.
- **Network** is off by default (its own empty net namespace). The switch shows a warning first and applies to
  newly started programs only.
- **Baseline**: when the polder is created, every file is recorded (type, mode, size, sha256, symlink target).
- **Change list**: added, modified, deleted, renamed (same hash), symlinks, and permission changes
  (including whiteouts and opaque dirs from the overlay).
- **Three-way**: baseline vs. vasteland now vs. polder. If the vasteland changed since the baseline and differs
  from the polder version, it is a **conflict**. Conflicts are never taken over automatically, only after
  "Toch de polderversie kiezen".
- **Merge**: dry run first (ops plus warnings), then per op: re-check the precondition (vasteland unchanged
  since the dry run), backup to the journal, write to a temp file, fsync, atomic rename. The journal
  (`journal/<id>/plan.json`, `log`, `backup/`) makes an interrupted merge resumable ("Afmaken") or
  reversible ("Terugdraaien"). A completed merge can also be rolled back via the CLI (`rollback`).
- Discard, archive and disk usage; the daemon warns about an unfinished merge, a polder > 2 GB, and < 5% free disk.
- Integration: Thunar right-click "Openen in Sluis", a launcher entry, and a shelf badge ("polder") on terminals
  started in a polder (app_id `nl.polderos.sluis.<id>`, title `[Proefpolder: name] …`).
- The change list refreshes when Sluis regains focus and has a Refresh button. Running terminals are counted;
  closing Sluis while they are active asks for confirmation because closing also stops those programs.

## Honest limits
- **This is not a VM and not a hardened sandbox.** The same kernel; no seccomp filter yet; the Wayland socket is
  reachable (a program can open windows and read the clipboard through the compositor's normal protocols).
- **External effects cannot be undone**: with network on, data leaving the machine (uploads, mails, API calls)
  is outside the polder. Sluis only reverts files in the project folder.
- Host folders are read-only from the polder; other parts of `$HOME` are a throwaway copy, so settings that a
  program writes there disappear when it exits.
- Files you did not change in the polder follow the vasteland live (that is OverlayFS); only changed files
  are frozen.
- Renaming a directory inside the polder becomes copy + delete (overlay without redirect_dir); in the change
  list that shows up as many adds and deletes, renames are recognised only per file.
- A type change from directory to file (or the reverse) under the same name is supported, but tested less than
  the normal cases.
- Hard links, xattrs/ACLs and file ownership are not carried over; only content, mode and symlinks.
- Only terminals started from Sluis (foot) get the window/shelf indicator; other apps inside a polder do not.
- The GTK app is not single-instance (`--new` opens a second window). Accessibility is basic
  (standard GTK widgets, no tests with a screen reader).
- The network toggle is per polder, not per program.

## CLI
`polder-sluisd list | create <name> <dir> [description] | info|changes|plan <id> [paths] | merge <id> [--review-token TOKEN] <paths…> [--force P] |
pending|resume <id> | rollback <id> [merge-id] | discard|archive|unarchive <id> | network <id> on|off | du | run <id> [--net] [--terminal] [-- cmd] | daemon`
(JSON output). `merge` without paths refuses.

`plan` returns a `review_token` alongside its operations. The desktop app passes that token and the same selected
paths to `merge`; Sluis recomputes the plan under the workspace lock and refuses it if either version has changed
since the preview. CLI callers can use the same option. Runner options (`--net`, `--terminal`) are only interpreted
before `--`; everything after it is passed to the child command unchanged.

## Safety and recovery guarantees (review fixes)

* **Ids**: a polder id is a strict slug (`[a-z0-9][a-z0-9-]{0,63}`) and must be a real (non-symlink) directory listed
  in the inventory directly under the canonical `polders` dir; the canonical path is re-checked before every read,
  write and delete. `rm_rf` is fd-relative and never follows symlinks (inode checked on every directory it enters).
* **Merge state machine** (`journal/<merge-id>/state`): `applying` → `applied` → `reconciled` → `committed`.
  `baseline.before.json` is saved before the first mainland change; reconciliation rebuilds `baseline.json` from it
  and the successfully applied states in the journal, preserving later mainland edits as conflicts,
  so every step can be re-run after a crash (`resume`). Rollback: `rolling-back` → `rolled-back` only when every op and
  the baseline were restored; otherwise `rollback-partial` (still pending, details in `rollback.json`, shown in the app,
  retry with *Roll back*).
* **Preconditions/races**: every op re-checks the exact pre-state (type, content and mode; a chmod is refused when the
  mainland mode changed) on an `O_NOFOLLOW` directory fd walked component by component from the project root;
  writes go to a temp file in that directory and are re-validated right before `renameat`; chmod uses an
  `O_PATH|O_NOFOLLOW` fd, so a directory swapped for a symlink is refused. Journal paths are validated on resume.
* **Type changes** (file↔folder, symlink↔folder, file↔symlink): the replacement is staged as `.name.sluis-tmp` next to
  the target and put in place with `renameat2(RENAME_EXCHANGE)` (or an atomic `renameat`/`RENAME_NOREPLACE` when no
  folder is involved); the old object is removed only after the swap. At every instant the target is either the old
  or the new object, never absent; stale staging is cleaned on resume/rollback. Rollback restages the saved original
  the same way (an independent verified copy from the journal, also across filesystems).
  Writes that replace a folder run after the deletions that empty it.
* **History**: only the newest merge that is not rolled back can be undone ("Roll back the newer merge(s) first"), so a
  historical rollback can never restore a baseline snapshot that predates later merges.
* **Locking**: merge (pending check + ops + reconciliation), resume, rollback and discard hold an exclusive `flock` on
  `locks/<id>.lock` outside the workspace; a second operation gets "This test polder is busy…" (`polder-sluisd` exits 75 with `"busy": true`,
  the app shows it as a message). The kernel releases the lock when the process exits or crashes.
* **Renames**: a selected rename only removes its source after the destination was accepted and successfully
  installed. A conflicted, failed or subsequently changed destination leaves the source in place.

## Staging ownership and locks

- Staging entries are named `.<name>.sluis-<merge-id>-<op>-<random>`, are created exclusively, and are recorded in `journal/<merge-id>/staging/<op>.json` (name + dev/inode/type/mtime). Recovery only removes an entry whose identity matches that record. Anything else stays in place and gets reported, and a name collision stops the merge with a clear error.
- Locks live at `$XDG_DATA_HOME/polder-sluis/locks/<id>.lock`, outside the workspace, and are never deleted. Create (ID reuse), merge, resume, rollback, discard and every metadata change (archive, network, run log) take the same lock. A busy lock gives exit code 75.

## Independent backups and verified swaps

- **Backups are independent copies.** Before an op changes a file, Sluis copies it into `journal/<merge-id>/backup/<n>`. Where the filesystem supports it, the copy is a reflink (`FICLONE`); otherwise it is a byte copy. It is never a hard link. Sluis records the size, sha256 and mode in `backup/<n>.json`, and fsyncs the file and the journal folder before touching the mainland. If the original changes while it is being copied, the copy won't match the plan, and that op is refused. On rollback, the backup is copied again (never linked) to an owned staging name. That copy has to match the recorded size and sha256, and the plan's original state, before it is installed. If it doesn't match, the rollback for that file is refused with "the backup of … does not match what was recorded" and the mainland is left as it is. Other hard links to the original file, and fds that are already open on it, therefore cannot change the backup or what gets restored.
- **Swaps are verified.** Every replacement of an existing object uses `renameat2(RENAME_EXCHANGE)`. A deletion (and rolling back a created file) first moves the object aside with `RENAME_NOREPLACE`. The object that was swapped out is then checked against the state checked just before the swap: dev, inode, mode, mtime and size must match, plus the content (sha256 or link target). ctime is not compared, because the rename itself updates it. If anything differs, for example another program replaced the path or wrote through an open fd in that window, Sluis swaps back, so the other program's version stays at its place, removes only its own staged object, and reports a conflict for that path.
- **Known limit.** A program that keeps a file open can still write through that fd after the verification. Such writes land in the old object, which has already been replaced, so they are not in the new file. This cannot be ruled out completely without the cooperation of that program (no mandatory locks on Linux). The merge dialog says so and asks the user to close programs that are editing the files first.
