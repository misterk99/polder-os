#!/usr/bin/env python3
"""Check renderer selection, failure boundaries and owned-child cleanup."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CompositorLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='polder-renderer-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = self.root / 'events.jsonl'
        self.wrapper = self.root / 'polder-compositor'
        self.wrapper.write_text((ROOT / 'iso/src/polder-compositor').read_text())
        self.wrapper.chmod(0o755)
        # Never discover a real installed compositor in the missing-binary tests.
        self.env = dict(os.environ, PATH=str(self.root),
                        POLDER_RENDERER_TEST_EVENTS=str(self.events))
        for key in ('POLDER_EFFECTS', 'WLR_RENDERER'):
            self.env.pop(key, None)
        program = '''#!/usr/bin/python3
import json, os, signal, sys
from pathlib import Path
kind = Path(sys.argv[0]).name
def record(event):
    with open(os.environ['POLDER_RENDERER_TEST_EVENTS'], 'a') as log:
        log.write(json.dumps([kind, event, sys.argv[1:]]) + '\\n')
record('start')
if kind == 'polder-comp-fx' and os.environ.get('FX_WAIT'):
    def stop(signum, _frame):
        record('stopped')
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    record('ready')
    while True:
        signal.pause()
sys.exit(int(os.environ.get('FX_EXIT' if kind == 'polder-comp-fx' else 'PLAIN_EXIT', '0')))
'''
        for name in ('polder-comp', 'polder-comp-fx'):
            path = self.root / name
            path.write_text(program)
            path.chmod(0o755)

    def records(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def run_wrapper(self, **env):
        return subprocess.run([str(self.wrapper), '-s', 'a command with spaces'],
                              env=dict(self.env, **env), capture_output=True, timeout=3)

    def starts(self):
        return [kind for kind, event, _args in self.records() if event == 'start']

    def test_effects_normal_exit_never_restarts_session(self):
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertEqual(self.starts(), ['polder-comp-fx'])
        self.assertEqual(self.records()[0][2], ['-s', 'a command with spaces'])

    def test_unsupported_renderer_falls_back_and_preserves_plain_status(self):
        self.assertEqual(self.run_wrapper(FX_EXIT='78', PLAIN_EXIT='7').returncode, 7)
        self.assertEqual(self.starts(), ['polder-comp-fx', 'polder-comp'])

    def test_runtime_failures_never_fall_back(self):
        for status in ('1', '137', '139'):
            with self.subTest(status=status):
                self.events.unlink(missing_ok=True)
                self.assertEqual(self.run_wrapper(FX_EXIT=status).returncode, int(status))
                self.assertEqual(self.starts(), ['polder-comp-fx'])

    def test_explicit_effects_disable_selects_plain(self):
        self.assertEqual(self.run_wrapper(POLDER_EFFECTS='0').returncode, 0)
        self.assertEqual(self.starts(), ['polder-comp'])

    def test_explicit_pixman_selects_plain(self):
        self.assertEqual(self.run_wrapper(WLR_RENDERER='pixman').returncode, 0)
        self.assertEqual(self.starts(), ['polder-comp'])

    def test_missing_optional_effects_selects_plain(self):
        (self.root / 'polder-comp-fx').unlink()
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertEqual(self.starts(), ['polder-comp'])

    def test_missing_required_effects_is_an_error(self):
        (self.root / 'polder-comp-fx').unlink()
        self.assertEqual(self.run_wrapper(POLDER_EFFECTS='1').returncode, 127)
        self.assertEqual(self.starts(), [])

    def test_termination_reaps_effects_without_fallback(self):
        process = subprocess.Popen([str(self.wrapper)], env=dict(self.env, FX_WAIT='1'),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 3
            while not any(event == 'ready' for _kind, event, _args in self.records()):
                if process.poll() is not None or time.monotonic() >= deadline:
                    self.fail('effects child failed to become ready')
                time.sleep(0.01)
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=3), 143)
            self.assertEqual(self.starts(), ['polder-comp-fx'])
            self.assertTrue(any(event == 'stopped' for _kind, event, _args in self.records()))
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


if __name__ == '__main__':
    unittest.main()
