#!/usr/bin/env python3
"""Read-only checks for a completed Polder ARM64 UEFI ISO.

All extracted files are temporary and are created beneath --work-dir. The ISO
is only opened for reading. Expected hashes are a JSON object mapping paths
inside the ISO or squashfs (for example ``/live/filesystem.squashfs`` or
``/usr/lib/polder/runtime.json``) to lowercase SHA256 hex strings. Kernel
metadata JSON may contain ``kernel_release``, ``kernel`` and ``initrd`` (each
an object with ``path`` and ``sha256``; their paths are relative to the ISO),
and ``modules`` (an object mapping paths relative to the squashfs root to
SHA256 strings).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


class VerifyError(Exception):
    pass


def run(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, check=False, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except OSError as exc:
        raise VerifyError(f"cannot run {argv[0]}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VerifyError(f"command failed ({result.returncode}): {argv[0]}: {detail}")
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid JSON file {path}: {exc}") from exc


def expected_hashes(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = load_json(path)
    if isinstance(data, dict) and "files" in data:
        data = data["files"]
    if not isinstance(data, dict):
        raise VerifyError("expected-hashes JSON must be an object of path -> SHA256")
    out = {}
    for name, value in data.items():
        if not isinstance(name, str) or not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise VerifyError(f"malformed expected hash entry: {name!r}")
        out[name.lstrip("/")] = value.lower()
    return out


def safe_member(root: Path, name: str) -> Path:
    rel = PurePosixPath(name.lstrip("/"))
    if not name or rel.is_absolute() or ".." in rel.parts:
        raise VerifyError(f"unsafe or empty manifest path: {name!r}")
    candidate = root.joinpath(*rel.parts)
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise VerifyError(f"manifest path escapes its root: {name!r}") from exc
    return candidate


def check_manifests(root: Path) -> int:
    checked = 0
    for manifest in root.rglob("*"):
        if not manifest.is_file() or manifest.name.upper() not in {"SHA256SUMS", "SHA256SUMS.TXT", "SHA256SUM.TXT", "SHA256.MANIFEST"}:
            continue
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise VerifyError(f"cannot read checksum manifest {manifest}: {exc}") from exc
        entries = 0
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[* ]?(.+?)\s*", line)
            if not match:
                raise VerifyError(f"malformed checksum line in {manifest}: {line!r}")
            target = safe_member(manifest.parent, match.group(2))
            if not target.is_file():
                raise VerifyError(f"manifest payload is missing: {target}")
            actual = sha256(target)
            if actual != match.group(1).lower():
                raise VerifyError(f"checksum mismatch for {target}")
            entries += 1
        if not entries:
            raise VerifyError(f"empty checksum manifest: {manifest}")
        checked += entries
    return checked


def compare_hashes(root: Path, expected: dict[str, str], label: str) -> None:
    for name, wanted in expected.items():
        target = safe_member(root, name)
        if not target.is_file():
            raise VerifyError(f"expected {label} file is missing: {name}")
        actual = sha256(target)
        if actual != wanted:
            raise VerifyError(f"{label} SHA256 mismatch for {name}: expected {wanted}, got {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path, help="completed ARM64 UEFI ISO to inspect")
    parser.add_argument("--work-dir", required=True, type=Path,
                        help="existing directory for temporary extracted data")
    parser.add_argument("--expected-sha256", help="expected ISO SHA256")
    parser.add_argument("--expected-hashes", type=Path,
                        help="JSON path -> SHA256 for packaged runtime/config files")
    parser.add_argument("--config-stamp", help="path inside squashfs containing the config version")
    parser.add_argument("--config-version", help="expected exact config stamp text")
    parser.add_argument("--kernel-metadata", type=Path,
                        help="JSON with expected kernel_release, initrd, and/or modules")
    args = parser.parse_args()

    try:
        if not args.iso.is_file():
            raise VerifyError(f"ISO does not exist or is not a file: {args.iso}")
        if not args.work_dir.is_dir():
            raise VerifyError(f"--work-dir must already exist: {args.work_dir}")
        if args.config_stamp and args.config_version is None:
            raise VerifyError("--config-stamp requires --config-version")
        for tool in ("xorriso", "unsquashfs"):
            if shutil.which(tool) is None:
                raise VerifyError(f"required tool is missing: {tool}")

        iso_hash = sha256(args.iso)
        if args.expected_sha256 and iso_hash.lower() != args.expected_sha256.lower():
            raise VerifyError(f"ISO SHA256 mismatch: expected {args.expected_sha256}, got {iso_hash}")

        boot = run(["xorriso", "-indev", str(args.iso), "-report_el_torito", "plain"])
        boot_lower = boot.lower()
        if "el torito" not in boot_lower and "boot catalog" not in boot_lower:
            raise VerifyError("xorriso reported no El Torito boot catalog")
        if "uefi" not in boot_lower and "efi" not in boot_lower:
            raise VerifyError("ISO has no reported UEFI/EFI El Torito entry")
        boot_entries = len(re.findall(r"el torito boot img", boot_lower))
        if boot_entries < 1:
            raise VerifyError("ISO has no UEFI El Torito boot entry")

        with tempfile.TemporaryDirectory(prefix="verify-arm64-", dir=args.work_dir) as tmp:
            tmpdir = Path(tmp)
            iso_tree = tmpdir / "iso"
            iso_tree.mkdir()
            run(["xorriso", "-osirrox", "on", "-indev", str(args.iso), "-extract", "/", str(iso_tree)])
            manifests = check_manifests(iso_tree)
            expected = expected_hashes(args.expected_hashes)
            iso_expected = {k: v for k, v in expected.items() if not k.startswith("squashfs:")}
            compare_hashes(iso_tree, iso_expected, "ISO")

            squashfs_files = sorted(p for p in iso_tree.rglob("*") if p.is_file() and p.suffix.lower() in {".squashfs", ".sfs"})
            if not squashfs_files:
                raise VerifyError("ISO contains no squashfs image")
            roots = []
            for index, image in enumerate(squashfs_files):
                run(["unsquashfs", "-s", str(image)])
                dest = tmpdir / f"squashfs-{index}"
                run(["unsquashfs", "-no-progress", "-d", str(dest), str(image)])
                roots.append(dest)
                manifests += check_manifests(dest)
            squash_expected = {k.removeprefix("squashfs:"): v for k, v in expected.items() if k.startswith("squashfs:")}
            if squash_expected:
                if len(roots) != 1:
                    raise VerifyError("squashfs: expected hashes require exactly one squashfs image")
                compare_hashes(roots[0], squash_expected, "squashfs")

            if args.config_stamp:
                if len(roots) != 1:
                    raise VerifyError("config stamp check requires exactly one squashfs image")
                stamp = safe_member(roots[0], args.config_stamp)
                try:
                    actual_version = stamp.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeError) as exc:
                    raise VerifyError(f"cannot read config stamp {args.config_stamp}: {exc}") from exc
                if actual_version != args.config_version:
                    raise VerifyError(f"config version mismatch: expected {args.config_version!r}, got {actual_version!r}")

            if args.kernel_metadata:
                metadata = load_json(args.kernel_metadata)
                if not isinstance(metadata, dict):
                    raise VerifyError("kernel metadata JSON must be an object")
                if len(roots) != 1:
                    raise VerifyError("kernel metadata checks require exactly one squashfs image")
                root = roots[0]
                release = metadata.get("kernel_release")
                if release is not None:
                    if not isinstance(release, str) or not release or not (root / "lib/modules" / release).is_dir():
                        raise VerifyError(f"expected kernel modules release is missing: {release!r}")
                kernel = metadata.get("kernel")
                if kernel is not None:
                    if not isinstance(kernel, dict) or not isinstance(kernel.get("path"), str) or not isinstance(kernel.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", kernel["sha256"]):
                        raise VerifyError("kernel metadata kernel must have path and SHA256")
                    compare_hashes(iso_tree, {kernel["path"]: kernel["sha256"].lower()}, "kernel")
                initrd = metadata.get("initrd")
                if initrd is not None:
                    if not isinstance(initrd, dict) or not isinstance(initrd.get("path"), str) or not isinstance(initrd.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", initrd["sha256"]):
                        raise VerifyError("kernel metadata initrd must have path and SHA256")
                    compare_hashes(iso_tree, {initrd["path"]: initrd["sha256"].lower()}, "initrd")
                modules = metadata.get("modules", {})
                if not isinstance(modules, dict):
                    raise VerifyError("kernel metadata modules must be an object of path -> SHA256")
                compare_hashes(root, modules, "kernel module")

        print(f"PASS ISO SHA256 {iso_hash}; ARM64 UEFI El Torito entry; {len(squashfs_files)} squashfs image(s); {manifests} manifest payload(s)")
        return 0
    except VerifyError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
