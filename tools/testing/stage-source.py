#!/usr/bin/env python3
"""Copy a checkout into Linux storage, fixing Windows checkout line endings there."""
import pathlib
import os
import subprocess
import sys

source, target = map(pathlib.Path, sys.argv[1:])
target.mkdir(parents=True, exist_ok=True)
subprocess.run([
    "rsync", "-a", "--delete", "--exclude=.git/", "--exclude=.polder-test/",
    "--exclude=screenshots/", "--exclude=iso/build/", "--exclude=iso/build-arm64/", "--exclude=__pycache__/",
    str(source) + "/", str(target) + "/",
], check=True)
suffixes = {".sh", ".py", ".c", ".h", ".desktop", ".env", ".conf", ".ini",
            ".xml", ".policy", ".service", ".timer", ".rules", ".chroot", ".pam"}
for directory, dirs, files in os.walk(target):
    dirs[:] = [name for name in dirs if name not in {"build", "build-arm64"}]
    for name in files:
        path = pathlib.Path(directory) / name
        if path.is_symlink():
            continue
        with path.open("rb") as stream:
            shebang = stream.read(2) == b"#!"
        if shebang or path.suffix in suffixes:
            data = path.read_bytes()
            if b"\r\n" in data:
                path.write_bytes(data.replace(b"\r\n", b"\n"))
            if shebang:
                path.chmod(path.stat().st_mode | 0o111)
