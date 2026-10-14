#!/usr/bin/env python3
"""Boot an amd64 or arm64 Polder ISO and collect evidence for visual review.

This records QEMU liveness and screenshots, not a claim that the desktop passed.
No host disks, shared directories, or installer destination are exposed to the guest.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import socket
import shlex
import subprocess
import tempfile
import time
import zlib

from PIL import Image


class Monitor:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(15)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile("rwb")
        json.loads(self.stream.readline())  # QMP greeting
        self.execute("qmp_capabilities")

    def execute(self, command, arguments=None):
        self.stream.write((json.dumps({"execute": command, "arguments": arguments or {}}) + "\n").encode())
        self.stream.flush()
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError("QEMU closed its monitor")
            reply = json.loads(line)
            if "error" in reply:
                raise RuntimeError(str(reply["error"]))
            if "return" in reply:
                return reply["return"]

    def close(self):
        self.stream.close()
        self.socket.close()


class SessionProbe:
    """Pump a serial console and collect scoped diagnostics from the live account."""

    BEGIN = "__POLDER_PROBE_BEGIN__"
    END = "__POLDER_PROBE_END__"
    ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")

    def __init__(self, connection, output, observation_end):
        self.socket = connection
        self.socket.setblocking(False)
        self.output = output
        self.observation_end = observation_end
        self.log = (output / "serial.log").open("wb")
        self.phase = "waiting-login"
        self.logged_in = False
        self.ready = None
        self.error = None
        self.processes = {}
        self.pending = bytearray()
        self.tail = ""
        self.line = ""
        self.collecting = False
        self.diagnostics = []

    def queue(self, text):
        self.pending.extend(text.encode("utf-8"))

    def flush(self):
        while self.pending:
            try:
                sent = self.socket.send(self.pending)
            except BlockingIOError:
                break
            if sent == 0:
                raise RuntimeError("serial console closed while sending the session probe")
            del self.pending[:sent]

    def collect_line(self, line):
        line = self.ANSI.sub("", line).strip("\r")
        if line == self.BEGIN:
            self.collecting = True
        if self.collecting:
            self.diagnostics.append(line)
            if line.startswith("__POLDER_SESSION_READY__ "):
                self.ready = line.split()[-1] == "1"
            elif line.startswith("__POLDER_PROCESS__ "):
                _, role, *pids = line.split()
                self.processes[role] = [int(pid) for pid in pids if pid.isdigit()]
            elif line == self.END:
                self.collecting = False
                self.phase = "collected"

    def refresh(self):
        if self.phase != "collected":
            raise RuntimeError("wait for the current serial snapshot before refreshing")
        self.phase = "collecting"
        self.tail = ""
        self.queue(self.guest_command(wait_for_ready=False))

    def guest_command(self, wait_for_ready=True):
        # Reserve time for bounded system-service queries and serial transmission.
        wait_seconds = min(120, max(0, int(self.observation_end - time.monotonic()) - 40)) if wait_for_ready else 0
        script = r'''printf '\n__POLDER_PROBE_BEGIN__\n'
uid=$(id -u)
ready_file="/run/user/$uid/polderos-wayland/ready"
remaining=WAIT_SECONDS
while [ ! -f "$ready_file" ] && [ "$remaining" -gt 0 ]; do
  sleep 1
  remaining=$((remaining - 1))
done
ready=0
[ ! -f "$ready_file" ] || ready=1
printf '__POLDER_SESSION_READY__ %s\n' "$ready"
# The marker means jobs were launched, so let immediate service crashes appear
# in the process/log snapshot. This does not establish long-term stability.
if [ "$ready" = 1 ]; then sleep 5; fi
report_process() {
  role=$1; shift
  pids=$(pgrep -u "$uid" "$@" 2>/dev/null | tr '\n' ' ')
  printf '__POLDER_PROCESS__ %s %s\n' "$role" "$pids"
}
report_process compositor -x 'polder-comp(-fx)?'
report_process shelf -f '[/]shelf/shelf.py'
report_process launcher -f '[/]launcher/launcher.py'
report_process notifications -f '[/]notify/osb-notifyd.py'
report_process clipboard -f '[/]clip/clipd.py'
report_process settings -f '[/]osb/osb-settingsd.py'
report_process combined_shell -f '[/]shell/polder-shell.py'
printf '\n--- Live-account process state ---\n'
ps -u "$uid" -o pid,stat,pcpu,wchan:24,comm
log_dir="$HOME/.cache/polderos/wayland"
for name in session notifications shelf launcher clipboard settings idle xsettings; do
  printf '\n--- session log: %s ---\n' "$name"
  if [ -f "$log_dir/$name.log" ]; then
    if [ "$name" = session ]; then head -n 60 -- "$log_dir/$name.log"; printf '\n--- latest session messages ---\n'; fi
    tail -n 40 -- "$log_dir/$name.log"
  else printf '(not present)\n'; fi
done
printf '\n--- User-service presence and state (not a functional portal test) ---\n'
timeout 5s systemctl --user --no-pager show --property=Id,LoadState,ActiveState,SubState,ExecStart \
  xdg-desktop-portal.service xdg-desktop-portal-gtk.service xdg-desktop-portal-wlr.service \
  pipewire.service pipewire-pulse.service wireplumber.service 2>&1 || true
printf '\n--- Sleep inhibitors (not a suspend/resume test) ---\n'
timeout 5s systemd-inhibit --list --no-pager 2>&1 || true
if [ "$ready" = 1 ]; then
  printf '\n--- Native output configuration ---\n'
  XDG_RUNTIME_DIR="/run/user/$uid" WAYLAND_DISPLAY="$(cat "$ready_file")" timeout 5s wlr-randr --json 2>&1 || true
fi
printf '\n--- LightDM status ---\n'
timeout 5s systemctl --no-pager --full status lightdm.service 2>&1 || true
if timeout 5s sudo -n true 2>/dev/null; then
  printf '\n--- LightDM journal ---\n'
  timeout 5s sudo -n journalctl -b -u lightdm.service --no-pager -n 40 2>&1 || true
  for name in lightdm seat0-greeter; do
    printf '\n--- LightDM log: %s ---\n' "$name"
    timeout 5s sudo -n tail -n 40 -- "/var/log/lightdm/$name.log" 2>&1 || true
  done
else
  printf '\nPasswordless sudo unavailable; privileged LightDM logs skipped.\n'
fi
printf '\n__POLDER_PROBE_END__\n'
'''.replace("WAIT_SECONDS", str(wait_seconds))
        # Compress the known script to keep a single terminal input line below
        # the canonical TTY line limit. No credentials or environment are dumped.
        payload = base64.b64encode(zlib.compress(script.encode())).decode("ascii")
        code = ('import base64,zlib,subprocess; subprocess.run(["bash"],'
                f'input=zlib.decompress(base64.b64decode("{payload}")),check=True)')
        command = "python3 -c " + shlex.quote(code) + "\n"
        if len(command.encode()) >= 4096:
            raise RuntimeError("session probe command exceeds the terminal input limit")
        return command

    def pump(self):
        self.flush()
        # Bound each pump so serial output cannot starve QMP screenshots.
        for _ in range(64):
            try:
                data = self.socket.recv(65536)
            except BlockingIOError:
                break
            if not data:
                self.error = "serial console closed before observation ended"
                break
            self.log.write(data)
            text = data.decode("utf-8", errors="replace")
            self.tail = (self.tail + text)[-8192:]
            self.line += text
            while "\n" in self.line:
                line, self.line = self.line.split("\n", 1)
                self.collect_line(line)
            self.line = self.line[-16384:]
        self.log.flush()
        tail = self.ANSI.sub("", self.tail).replace("\r", "")
        if self.phase in ("waiting-password", "waiting-shell") and "Login incorrect" in tail:
            self.error = "the public live-session login was rejected"
            self.phase = "failed"
        if self.phase in ("waiting-login", "waiting-password", "waiting-shell") and re.search(
                r"(?:^|\n)polder@[^\n]*\$\s*$", tail):
            self.logged_in = True
            self.phase = "collecting"
            self.tail = ""
            self.queue(self.guest_command())
        elif self.phase == "waiting-login" and re.search(r"(?:^|\n)[^\n]*login:\s*$", tail):
            self.queue("polder\n")
            self.phase = "waiting-password"
            self.tail = ""
        elif self.phase == "waiting-password" and re.search(r"(?:Password|Wachtwoord):\s*$", tail, re.IGNORECASE):
            self.queue("live\n")  # Public credentials of the disposable live ISO.
            self.phase = "waiting-shell"
            self.tail = ""
        self.flush()

    def report(self):
        error = self.error
        if error is None:
            if not self.logged_in:
                error = f"no live-account shell within the observation window ({self.phase})"
            elif self.phase != "collected":
                error = "guest diagnostics did not finish within the observation window"
            elif not self.ready:
                error = "the Wayland session did not create its ready file before the bounded diagnostic snapshot"
        result = {"status": "failed" if error else "collected", "error": error,
                  "logged_in": self.logged_in, "session_ready": self.ready,
                  "process_ids": self.processes, "phase": self.phase,
                  "desktop_result": "diagnostics only; inspect processes, logs and screenshots"}
        (self.output / "session-probe.json").write_text(json.dumps(result, indent=2) + "\n")
        (self.output / "session-probe.log").write_text("\n".join(self.diagnostics) + "\n")
        return result

    def close(self):
        self.log.close()
        self.socket.close()


def capture(monitor, output, name):
    ppm = output / (name + ".ppm")
    monitor.execute("screendump", {"filename": str(ppm)})
    with Image.open(ppm) as frame:
        frame.save(output / (name + ".png"))
    ppm.unlink()
    print(f"Captured {name}.png", flush=True)
    return name + ".png"


def has_visible_content(path):
    """Readiness hint only: reject black frames and a cursor on a black screen."""
    with Image.open(path) as frame:
        colors = frame.convert("RGB").resize((64, 40), Image.Resampling.BOX).getcolors(2560)
    return len(colors) >= 32 and sum(count for count, rgb in colors if max(rgb) > 16) >= 640


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--arch", choices=("amd64", "arm64"), default="amd64")
    parser.add_argument("--direct-kernel", action="store_true", help="diagnose the live system with serial logs, bypassing GRUB")
    parser.add_argument("--probe-session", action="store_true", help="log into the disposable live account over serial and collect scoped session diagnostics (amd64 requires --direct-kernel)")
    parser.add_argument("--exercise-shell", action="store_true", help="after a ready probe, exercise launcher, terminal, maximize and close; screenshots require visual review")
    args = parser.parse_args()
    if not args.iso.is_file() or args.seconds < 30:
        parser.error("supply an existing ISO and at least 30 observation seconds")
    if args.probe_session and not args.direct_kernel and args.arch != "arm64":
        parser.error("--probe-session requires --direct-kernel on amd64 so a serial login console is available")
    if args.exercise_shell and not args.probe_session:
        parser.error("--exercise-shell requires --probe-session")
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix="polder-qemu-") as temporary:
        monitor_path = Path(temporary) / "qmp.sock"
        serial_path = Path(temporary) / "serial.sock"
        if args.arch == "arm64":
            command = ["qemu-system-aarch64", "-machine", "virt", "-cpu", "max",
                       "-device", "virtio-gpu-pci", "-device", "qemu-xhci",
                       "-device", "usb-kbd", "-device", "usb-tablet",
                       "-device", "virtio-scsi-pci",
                       "-drive", f"file={args.iso.resolve()},if=none,id=cdrom,format=raw,media=cdrom,readonly=on",
                       "-device", "scsi-cd,drive=cdrom,bootindex=1"]
            if not args.direct_kernel:
                firmware = Path("/usr/share/qemu-efi-aarch64/QEMU_EFI.fd")
                if not firmware.is_file():
                    raise RuntimeError("Install qemu-efi-aarch64 for ARM64 UEFI boot")
                command += ["-bios", str(firmware)]
            serial_console = "ttyAMA0"
        else:
            command = ["qemu-system-x86_64", "-cpu", "max", "-vga", "virtio",
                       "-cdrom", str(args.iso.resolve()), "-boot", "d",
                       "-usb", "-device", "usb-tablet"]
            serial_console = "ttyS0"
        command += ["-accel", "tcg,thread=multi", "-m", "3072", "-smp", "2",
                   "-display", "none", "-no-reboot", "-qmp", f"unix:{monitor_path},server=on,wait=off",
                   "-nic", "none", "-device", "virtio-rng-pci",
                   ]
        if args.probe_session:
            command += ["-chardev", f"socket,id=probe,path={serial_path},server=on,wait=off",
                        "-serial", "chardev:probe"]
        else:
            command += ["-serial", f"file:{output / 'serial.log'}"]
        if args.direct_kernel:
            with (output / 'extract.log').open('w') as extraction_log:
                listing = subprocess.run(['xorriso', '-indev', str(args.iso.resolve()), '-ls', '/live'],
                                         stdout=subprocess.PIPE, stderr=extraction_log, text=True, check=True)
                names = shlex.split(listing.stdout)
                kernels = [name for name in names if name.startswith('vmlinuz-')]
                if len(kernels) != 1:
                    raise RuntimeError('Direct boot requires exactly one versioned kernel in /live')
                kernel = kernels[0]
                initrd = 'initrd.img-' + kernel.removeprefix('vmlinuz-')
                if initrd not in names:
                    raise RuntimeError('No matching live initramfs found')
                subprocess.run(['xorriso', '-osirrox', 'on', '-indev', str(args.iso.resolve()),
                                '-extract', '/live/' + kernel, temporary + '/vmlinuz',
                                '-extract', '/live/' + initrd, temporary + '/initrd'],
                               stdout=extraction_log, stderr=extraction_log, check=True)
            command += ['-kernel', temporary + '/vmlinuz', '-initrd', temporary + '/initrd',
                        '-append', 'boot=live components locales=nl_NL.UTF-8 keyboard-layouts=us '
                                   'timezone=Europe/Amsterdam username=polder user-fullname=Polder '
                                   f'hostname=polderos console=tty0 console={serial_console},115200 loglevel=6']
        (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        monitor = None
        probe = None
        with (output / "qemu.log").open("wb") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while not monitor_path.exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("QEMU did not open its monitor; see qemu.log")
                    time.sleep(0.1)
                monitor = Monitor(monitor_path)
                started = time.monotonic()
                if args.probe_session:
                    connection = socket.socket(socket.AF_UNIX)
                    try:
                        connection.settimeout(1)
                        while True:
                            try:
                                connection.connect(str(serial_path))
                                break
                            except (FileNotFoundError, ConnectionRefusedError):
                                if process.poll() is not None or time.monotonic() >= deadline:
                                    raise RuntimeError("QEMU did not open its serial socket; see qemu.log")
                                time.sleep(0.1)
                        probe = SessionProbe(connection, output, started + args.seconds)
                    except BaseException:
                        connection.close()
                        raise
                next_capture = 0
                captures = []
                exercise_due = None
                visible_since = None
                final_probe_sent = False
                exercise_step = 0
                exercise = [(0, "capture", "desktop-ready"), (2, "key", "meta_l"),
                            (14, "capture", "launcher"), (15, "key", "esc"),
                            (18, "key", "meta_l-ret"), (43, "capture", "terminal"),
                            (45, "key", "meta_l-up"), (55, "capture", "terminal-maximized"),
                            (57, "key", "meta_l-q"), (67, "capture", "desktop-restored"),
                            (69, "key", "meta_l-l"), (94, "capture", "screen-locked"),
                            (96, "key", "l"), (97, "key", "i"), (98, "key", "v"),
                            (99, "key", "e"), (100, "key", "ret"),
                            (120, "capture", "screen-unlocked")]
                while time.monotonic() - started < args.seconds:
                    if probe is not None:
                        probe.pump()
                    if process.poll() is not None:
                        raise RuntimeError(f"QEMU exited early: {process.returncode}")
                    elapsed = int(time.monotonic() - started)
                    if (probe is not None and not final_probe_sent and elapsed >= args.seconds - 60
                            and probe.phase == "collected"):
                        probe.refresh()
                        final_probe_sent = True
                    if elapsed >= next_capture:
                        name = f"boot-{elapsed:04d}"
                        captures.append(capture(monitor, output, name))
                        if (args.exercise_shell and visible_since is None and probe.ready and
                                has_visible_content(output / captures[-1])):
                            visible_since = time.monotonic()
                            print("Visible screen content detected; settling before keyboard exercise.", flush=True)
                        next_capture += 30
                    if (args.exercise_shell and visible_since is not None and
                            time.monotonic() - visible_since >= 5 and
                            probe.phase == "collected" and probe.ready and all(
                            probe.processes.get(role) for role in ("compositor", "shelf", "launcher"))):
                        if exercise_due is None:
                            exercise_due = time.monotonic()
                        if exercise_step < len(exercise):
                            delay, action, value = exercise[exercise_step]
                            if time.monotonic() >= exercise_due:
                                if action == "capture":
                                    captures.append(capture(monitor, output, value))
                                else:
                                    monitor.execute("human-monitor-command", {"command-line": "sendkey " + value})
                                exercise_step += 1
                                if exercise_step < len(exercise):
                                    # Preserve the wait after each action even if a screenshot was slow.
                                    exercise_due = time.monotonic() + exercise[exercise_step][0] - delay
                    time.sleep(0.25)
                report = {"qemu_status": monitor.execute("query-status"), "architecture": args.arch,
                          "seconds": args.seconds, "screenshots": captures,
                          "desktop_result": "requires visual review; VM liveness is not desktop acceptance",
                          "acceleration": "TCG software emulation"}
                report['boot_path'] = 'direct kernel (GRUB not tested)' if args.direct_kernel else 'ISO firmware/GRUB'
                if args.exercise_shell:
                    report['shell_exercise'] = {"steps_completed": exercise_step, "steps_planned": len(exercise),
                                                "visible_content_seconds": None if visible_since is None else round(visible_since - started, 1),
                                                "result": "review named screenshots; key delivery alone is not a pass"}
                if probe is not None:
                    probe.pump()
                    report["session_probe"] = probe.report()
                (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
                if probe is not None and report["session_probe"]["status"] == "failed":
                    raise RuntimeError(report["session_probe"]["error"] + "; see session-probe.json and serial.log")
                print("VM evidence collected. Review screenshots and logs before judging the desktop.", flush=True)
            finally:
                if probe is not None:
                    try:
                        probe.report()
                    except OSError as error:
                        print(f"Could not save session probe report: {error}", flush=True)
                    finally:
                        probe.close()
                if monitor is not None:
                    try:
                        if process.poll() is None:
                            monitor.execute("quit")
                    except (OSError, RuntimeError):
                        pass
                    monitor.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
