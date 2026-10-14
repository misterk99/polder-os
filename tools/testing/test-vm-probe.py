#!/usr/bin/env python3
"""Exercise the optional VM serial probe without QEMU or a guest."""
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest


spec = importlib.util.spec_from_file_location("vm_smoke", Path(__file__).with_name("vm-smoke.py"))
vm_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm_smoke)


class SerialSessionProbe(unittest.TestCase):
    def test_dutch_live_login_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            client, guest = socket.socketpair()
            guest.settimeout(1)
            probe = vm_smoke.SessionProbe(client, Path(temporary), time.monotonic() + 60)
            try:
                guest.sendall(b"polderos login: ")
                probe.pump()
                self.assertEqual(guest.recv(128), b"polder\n")
                guest.sendall(b"polder\r\nWacht")
                probe.pump()
                self.assertEqual(probe.phase, "waiting-password")
                guest.sendall(b"woord: ")
                probe.pump()
                self.assertEqual(guest.recv(128), b"live\n")
                self.assertEqual(probe.phase, "waiting-shell")
            finally:
                probe.close()
                guest.close()

    def test_fragmented_login_and_diagnostics_preserve_serial_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            client, guest = socket.socketpair()
            guest.settimeout(1)
            probe = vm_smoke.SessionProbe(client, output, time.monotonic() + 60)
            try:
                guest.sendall(b"boot log\r\npolderos log")
                probe.pump()
                self.assertEqual(probe.phase, "waiting-login")
                self.assertIn("no live-account shell", probe.report()["error"])
                guest.sendall(b"in: ")
                probe.pump()
                self.assertEqual(guest.recv(128), b"polder\n")
                guest.sendall(b"polder\r\nPassword: ")
                probe.pump()
                self.assertEqual(guest.recv(128), b"live\n")
                guest.sendall(b"\r\nLast login: today\r\n\x1b[32mpolder@polderos\x1b[0m:~$ ")
                probe.pump()
                command = guest.recv(8192)
                self.assertTrue(command.startswith(b"python3 -c "))
                self.assertLess(len(command), 4096)
                self.assertNotIn(probe.BEGIN.encode(), command)
                guest.sendall(b"\r\n__POLDER_PROBE_BEGIN__\r\n__POLDER_SESSION_RE")
                probe.pump()
                guest.sendall(b"ADY__ 1\r\n")
                probe.pump()
                readiness = json.loads((output / "session-probe-readiness.json").read_text())
                self.assertEqual(readiness["status"], "ready")
                self.assertTrue(readiness["session_ready"])
                guest.sendall(b"__POLDER_PROCESS__ compositor 123\r\n"
                              b"__POLDER_PROCESS__ shelf 124 125\r\n"
                              b"__POLDER_PROCESS__ combined_shell \r\nknown log line\r\n"
                              b"__POLDER_PROBE_END__\r\n")
                probe.pump()
                result = probe.report()
                self.assertEqual(result["status"], "collected")
                self.assertTrue(result["session_ready"])
                self.assertEqual(result["process_ids"], {"compositor": [123], "shelf": [124, 125], "combined_shell": []})
                self.assertIn("known log line", (output / "session-probe.log").read_text())
                self.assertIn(b"boot log", (output / "serial.log").read_bytes())
                self.assertEqual(json.loads((output / "session-probe.json").read_text())["status"], "collected")
                probe.refresh()
                probe.pump()
                self.assertTrue(guest.recv(8192).startswith(b"python3 -c "))
                guest.sendall(b"\r\n__POLDER_PROBE_BEGIN__\r\n__POLDER_SESSION_READY__ 0\r\n"
                              b"__POLDER_PROCESS__ compositor \r\n__POLDER_PROBE_END__\r\n")
                probe.pump()
                self.assertEqual(probe.report()["status"], "failed")
                self.assertEqual(json.loads((output / "session-probe-readiness.json").read_text())["status"], "not_ready")
                self.assertFalse(probe.ready)
                self.assertEqual(probe.processes["compositor"], [])
                self.assertIn("known log line", (output / "session-probe.log").read_text())
            finally:
                probe.close()
                guest.close()


if __name__ == "__main__":
    unittest.main()
