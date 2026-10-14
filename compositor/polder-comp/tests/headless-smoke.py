#!/usr/bin/env python3
"""Exercise a real headless polder-comp session with native Wayland clients.

Build with -Dscenefx=disabled, then run on Linux with foot, wtype, grim,
fonts-dejavu-core and python3-pil installed. No existing desktop is used.
Each run keeps its logs, assertions and screenshot beneath --output-dir.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback


class SmokeFailure(RuntimeError):
    pass


class Session:
    def __init__(self, binary, output, timeout):
        self.binary = binary
        self.output = output
        self.timeout = timeout
        self.temp = tempfile.TemporaryDirectory(prefix="polder-smoke-")
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.children = []
        self.logs = []
        self.compositor = None
        self.checks = []
        self.last_state = None
        self.env = {key: value for key, value in os.environ.items()
                    if key in ("PATH", "LD_LIBRARY_PATH")}
        for key, name in (("HOME", "home"), ("XDG_RUNTIME_DIR", "runtime"),
                          ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                          ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            path = self.root / name
            path.mkdir(mode=0o700)
            self.env[key] = str(path)
        keys = self.root / "keys"
        keys.write_text("Super m @minimize\n", encoding="utf-8")
        self.env.update(WLR_BACKENDS="headless", WLR_RENDERER="pixman",
                        WLR_HEADLESS_OUTPUTS="0", POLDER_NO_XWAYLAND="1",
                        POLDER_DESKS="1", POLDER_KEYS=str(keys),
                        POLDER_LAUNCHER="true", XKB_DEFAULT_LAYOUT="us",
                        LANG="C.UTF-8", LC_ALL="C.UTF-8")

    def alive(self):
        if self.compositor is not None and self.compositor.poll() is not None:
            raise SmokeFailure(f"compositor exited with {self.compositor.returncode}")

    def wait_for(self, label, predicate):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.alive()
            result = predicate()
            if result:
                return result
            time.sleep(0.025)
        raise SmokeFailure(f"timed out waiting for {label}")

    def spawn(self, name, argv):
        log = (self.output / f"{name}.log").open("wb")
        self.logs.append(log)
        process = subprocess.Popen(argv, env=self.env, cwd=self.root,
                                   stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append(process)
        return process

    def run(self, argv):
        self.alive()
        try:
            result = subprocess.run(argv, env=self.env, cwd=self.root,
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(f"command timed out: {argv[0]}") from exc
        with (self.output / "commands.log").open("ab") as log:
            log.write((json.dumps(argv) + "\n").encode())
            log.write(result.stdout + result.stderr)
        if result.returncode:
            raise SmokeFailure(f"{argv[0]} exited with {result.returncode}; see commands.log")
        self.alive()
        return result

    def command(self, command):
        self.alive()
        fifo = self.runtime / "polder-comp.cmd"
        try:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, (command + "\n").encode("ascii"))
            finally:
                os.close(fd)
        except OSError as exc:
            raise SmokeFailure(f"cannot send compositor command {command!r}: {exc}") from exc

    def state(self):
        path = self.runtime / "polder-state.json"
        path.unlink(missing_ok=True)
        self.command("dump")
        self.wait_for("fresh compositor state", path.is_file)
        # dump_state writes a temporary file then atomically renames it.
        self.last_state = json.loads(path.read_text(encoding="utf-8"))
        return self.last_state

    def expect_state(self, label, predicate):
        state = self.wait_for(label, lambda: (s if predicate(s := self.state()) else None))
        self.passed(label)
        return state

    def passed(self, label):
        self.checks.append(label)
        print(f"PASS {label}", flush=True)

    def window(self, state, app_id):
        return next((w for w in state["windows"] if w["app_id"] == app_id), None)

    def client(self, name):
        app_id = f"polder-smoke-{name}"
        received = self.root / f"input-{name}"
        command = ("printf 'Polder smoke %s\\n' \"$2\"; "
                   "while IFS= read -r line; do printf '%s\\n' \"$line\" >> \"$1\"; done")
        process = self.spawn(f"client-{name}", ["foot", "-c", "/dev/null", "-a", app_id,
                            "-T", f"Polder smoke {name}", "-w", "480x320", "sh", "-c",
                            command, "polder-smoke", str(received), name])

        def mapped(state):
            if process.poll() is not None:
                raise SmokeFailure(f"client {name} exited early with {process.returncode}")
            return self.window(state, app_id)

        state = self.expect_state(f"native client {name} mapped", mapped)
        window = self.window(state, app_id)
        if window["x11"] or window["w"] <= 0 or window["h"] <= 0:
            raise SmokeFailure(f"client {name} did not map as a sized native Wayland window")
        return window["id"], received

    def type_marker(self, label, receiver, other):
        marker = f"smoke-{label}"
        self.run(["wtype", "-d", "1", marker, "-k", "Return"])
        self.wait_for(f"typed marker {label}",
                      lambda: receiver.is_file() and marker in receiver.read_text().splitlines())
        if other.is_file() and marker in other.read_text().splitlines():
            raise SmokeFailure(f"typed marker {label} also reached the wrong client")
        self.passed(f"keyboard focus {label}")

    def maximize_restore(self, state, window_id):
        from PIL import Image

        window = next(w for w in state["windows"] if w["id"] == window_id)
        floating = tuple(window[key] for key in ("x", "y", "w", "h"))
        with Image.open(self.output / "screenshot.png") as baseline:
            baseline = baseline.convert("RGB")
            width, height = baseline.size
            x, y, w, h = floating
            if not (w < width and h < height and x + w < width - 32 and y + h < height - 32):
                raise SmokeFailure(f"maximize test requires a smaller floating client: {floating}")
            # Blank terminal pixels well inside the floating client provide an
            # independent reference for its buffer, distinct from the desktop.
            client_box = (x + w - 32, y + h - 32, x + w - 16, y + h - 16)
            client_colors = baseline.crop(client_box).getcolors(maxcolors=1)
            desktop_colors = baseline.crop((width - 32, height - 32, width - 16, height - 16)).getcolors(maxcolors=1)
            if not client_colors or not desktop_colors or client_colors == desktop_colors:
                raise SmokeFailure("cannot distinguish terminal buffer from desktop for resize validation")

        def geometry_matches(current, expected):
            match = next((w for w in current["windows"] if w["id"] == window_id), None)
            return match and tuple(match[key] for key in ("x", "y", "w", "h")) == expected

        def capture_matches(name, expected_colors, boxes):
            self.run(["grim", str(self.output / name)])
            with Image.open(self.output / name) as screenshot:
                screenshot = screenshot.convert("RGB")
                return screenshot.size == (width, height) and all(
                    screenshot.crop(box).getcolors(maxcolors=1) == expected_colors for box in boxes)

        self.run(["wtype", "-M", "logo", "-k", "Up", "-m", "logo"])
        maximized = self.expect_state("maximize resizes the committed client to the whole output",
                                     lambda s: geometry_matches(s, (0, 0, width, height)))
        (self.output / "maximized-state.json").write_text(json.dumps(maximized, indent=2) + "\n")
        # Stay below foot's client-side titlebar when sampling its upper edge.
        expanded_boxes = [(width - 32, 64, width - 16, 80),
                          (16, height - 32, 32, height - 16),
                          (width - 32, height - 32, width - 16, height - 16)]
        self.wait_for("maximized buffer reaching the output edges", lambda: capture_matches(
            "maximized.png", client_colors, expanded_boxes))
        self.passed("maximized screenshot contains client pixels beyond the original buffer bounds")

        self.run(["wtype", "-M", "logo", "-k", "Up", "-m", "logo"])
        restored = self.expect_state("unmaximize restores the committed client size and position",
                                    lambda s: geometry_matches(s, floating))
        (self.output / "restored-state.json").write_text(json.dumps(restored, indent=2) + "\n")
        self.wait_for("restored desktop outside the floating client", lambda: capture_matches(
            "restored.png", desktop_colors, expanded_boxes))
        self.passed("restored screenshot clears the maximized client pixels outside its floating bounds")

    def start(self):
        self.compositor = self.spawn("compositor", [str(self.binary)])

        def ready():
            sockets = [p for p in self.runtime.glob("wayland-*")
                       if stat.S_ISSOCK(p.stat().st_mode)]
            fifo = self.runtime / "polder-comp.cmd"
            return sockets[0].name if sockets and fifo.exists() and stat.S_ISFIFO(fifo.stat().st_mode) else None

        self.env["WAYLAND_DISPLAY"] = self.wait_for("Wayland socket and command FIFO", ready)

    def execute(self):
        from PIL import Image

        self.start()
        self.expect_state("empty initial desk", lambda s: s["desk"] == 0 and s["desks"] == 1 and not s["windows"])
        a, input_a = self.client("a")
        b, input_b = self.client("b")
        self.expect_state("two independent windows", lambda s: len(s["windows"]) == 2)

        def first(state, window_id):
            return bool(state["windows"]) and state["windows"][0]["id"] == window_id

        self.command(f"focus {a}")
        self.expect_state("focus A changes MRU order", lambda s: first(s, a))
        self.type_marker("a-initial", input_a, input_b)
        self.command(f"focus {b}")
        self.expect_state("focus B changes MRU order", lambda s: first(s, b))
        self.type_marker("b-initial", input_b, input_a)

        self.run(["wtype", "-M", "logo", "-k", "m", "-m", "logo"])
        self.expect_state("minimize B focuses A", lambda s: first(s, a) and
                          self.window(s, "polder-smoke-b")["min"])
        self.type_marker("a-after-minimize", input_a, input_b)
        self.command(f"focus {b}")
        self.expect_state("focus restores minimized B", lambda s: first(s, b) and
                          not self.window(s, "polder-smoke-b")["min"])
        self.type_marker("b-restored", input_b, input_a)

        self.command("newdesk")
        self.expect_state("new desk selected", lambda s: s["desk"] == 1 and s["desks"] == 2 and
                          all(w["desk"] == 0 for w in s["windows"]))
        self.run(["grim", str(self.output / "empty-desk.png")])
        with Image.open(self.output / "empty-desk.png") as empty_desk:
            empty_desk.load()
            if empty_desk.size != (1366, 768) or any(
                    low != high for low, high in empty_desk.convert("RGB").getextrema()):
                raise SmokeFailure("windows or shadows remain visible on the empty desk")
        self.passed("empty desk hides the previous desk's windows and shadows")
        self.command(f"movedesk {a} 1")
        self.expect_state("A moved to desk 1", lambda s: self.window(s, "polder-smoke-a")["desk"] == 1)
        self.command(f"focus {a}")
        self.expect_state("A focused on desk 1", lambda s: s["desk"] == 1 and first(s, a))
        self.type_marker("a-on-desk-one", input_a, input_b)
        self.command("desk 0")
        self.expect_state("switch to desk 0 focuses B", lambda s: s["desk"] == 0 and first(s, b))
        self.type_marker("b-on-desk-zero", input_b, input_a)
        self.command(f"focus {a}")
        self.expect_state("focus follows A across desks", lambda s: s["desk"] == 1 and first(s, a))
        self.type_marker("a-cross-desk", input_a, input_b)
        self.command("deldesk 1")
        self.expect_state("deleting desk preserves both windows", lambda s: s["desk"] == 0 and
                          s["desks"] == 1 and len(s["windows"]) == 2 and
                          all(w["desk"] == 0 for w in s["windows"]))

        self.command(f"close {b}")
        state = self.expect_state("close B preserves A", lambda s: len(s["windows"]) == 1 and first(s, a))
        self.run(["grim", str(self.output / "screenshot.png")])
        with Image.open(self.output / "screenshot.png") as screenshot:
            screenshot.load()
            if screenshot.size != (1366, 768):
                raise SmokeFailure(f"unexpected headless capture size {screenshot.size}")
            window = state["windows"][0]
            # A shadow alone makes the whole screenshot nonuniform. Check inside
            # the reported client rectangle so a missing client buffer fails.
            box = (window["x"] + 24, window["y"] + 24,
                   window["x"] + window["w"] - 24, window["y"] + window["h"] - 24)
            if not (0 <= box[0] < box[2] <= screenshot.width and
                    0 <= box[1] < box[3] <= screenshot.height):
                raise SmokeFailure(f"client geometry is outside the screenshot: {box}")
            if not any(low != high for low, high in screenshot.crop(box).convert("RGB").getextrema()):
                raise SmokeFailure("screenshot has no rendered content inside the client rectangle")
        self.passed("screencopy shows client content at its reported geometry in a 1366x768 PNG")
        thumb = self.runtime / f"polder-thumb-{a}.raw"
        with thumb.open("rb") as source:
            width, height, pixel_format = source.readline().decode("ascii").split()
            pixels = source.read()
        if (int(width) <= 0 or int(height) <= 0 or pixel_format not in ("RGBA", "BGRA") or
                len(pixels) != int(width) * int(height) * 4):
            raise SmokeFailure("invalid overview thumbnail buffer")
        thumbnail = Image.frombytes("RGBA", (int(width), int(height)), pixels, "raw", pixel_format)
        if not any(low != high for low, high in thumbnail.convert("RGB").getextrema()):
            raise SmokeFailure("overview thumbnail contains only a flat buffer")
        self.passed("overview exports a complete thumbnail containing rendered content")
        (self.output / "captured-state.json").write_text(json.dumps(state, indent=2) + "\n")
        self.maximize_restore(state, a)
        self.type_marker("a-after-unmaximize", input_a, input_b)
        self.command(f"close {a}")
        self.expect_state("closing last window leaves compositor running", lambda s: not s["windows"])

    def close(self):
        # Signal only process groups started by this harness, never a desktop-wide pkill.
        for process in reversed(self.children):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in reversed(self.children):
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
        for log in self.logs:
            log.close()
        self.temp.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10, help="seconds per bounded readiness check")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("the headless compositor test requires Linux")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    binary = args.compositor.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f"compositor is not executable: {binary}")
    missing = [name for name in ("foot", "wtype", "grim") if not shutil.which(name)]
    if missing:
        parser.error("missing commands: " + ", ".join(missing))
    try:
        import PIL  # noqa: F401
    except ImportError:
        parser.error("python3-pil is required to validate the screenshot")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="headless-", dir=args.output_dir.resolve()))
    print(f"Artifacts: {output}", flush=True)
    session = Session(binary, output, args.timeout)
    status, error = "failed", None
    try:
        session.execute()
        status = "passed"
    except Exception as exc:
        error = str(exc)
        traceback.print_exc(file=sys.stderr)
    finally:
        try:
            session.close()
        except Exception as exc:
            status, error = "failed", f"cleanup failed: {exc}; prior failure: {error}"
            traceback.print_exc(file=sys.stderr)
        report = {"status": status, "checks": session.checks, "error": error,
                  "compositor": str(binary), "last_state": session.last_state}
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{status.upper()}: {len(session.checks)} checks; artifacts: {output}", flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
