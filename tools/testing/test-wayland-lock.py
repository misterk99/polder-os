#!/usr/bin/env python3
"""Linux-only lock/suspend regression tests. No display or real suspend is used."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / 'config/lock'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), LOCK / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.02)
    raise AssertionError('Timed out waiting for expected test state')


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='polder-lock-test-')
        self.path = Path(self.temp.name)
        self.children = []
        self.logs = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
        for log in self.logs: log.close()
        self.temp.cleanup()

    def start(self, commands, timeout=.7):
        module_path = str(LOCK / 'lock-session.py')
        code = ('import importlib.util,json,pathlib,signal,sys; '
                'signal.signal(signal.SIGTERM, lambda *_: sys.exit(143)); '
                's=importlib.util.spec_from_file_location("lock_session",sys.argv[1]); '
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m); '
                'sys.exit(m.serve(pathlib.Path(sys.argv[2]),json.loads(sys.argv[3]),float(sys.argv[4])))')
        log = (self.path / 'controller.log').open('ab'); self.logs.append(log)
        child = subprocess.Popen([sys.executable, '-c', code, module_path, str(self.path),
                                  json.dumps(commands), str(timeout)], stdout=log, stderr=log)
        self.children.append(child)
        wait_for(lambda: (self.path / 'controller.sock').exists() or child.poll() is not None)
        self.assertIsNone(child.poll(), (self.path / 'controller.log').read_text())
        return child

    @staticmethod
    def fake(delay=.01, ack=True, lifetime=10, status=0):
        code = ('import os,time,sys; '
                f'time.sleep({delay}); '
                + ("os.write(int(os.environ['POLDER_LOCK_READY_FD']),b'\\n'); " if ack else '')
                + f'time.sleep({lifetime}); sys.exit({status})')
        return [sys.executable, '-c', code]

    def connect(self):
        client = socket.socket(socket.AF_UNIX)
        client.settimeout(2)
        client.connect(str(self.path / 'controller.sock'))
        self.addCleanup(client.close)
        return client

    def test_ack_is_not_process_start_and_concurrent_callers_wait(self):
        self.start([self.fake(delay=.35)])
        a, b = self.connect(), self.connect()
        a.settimeout(.1)
        with self.assertRaises(socket.timeout): a.recv(64)
        a.settimeout(2)
        self.assertEqual(a.recv(64), b'LOCKED\n')
        self.assertEqual(b.recv(64), b'LOCKED\n')
        self.assertEqual(self.connect().recv(64), b'LOCKED\n')

    def test_primary_exit_before_ack_requires_fallback_ack(self):
        self.start([self.fake(ack=False, lifetime=0, status=3), self.fake(delay=.2)])
        self.assertEqual(self.connect().recv(64), b'LOCKED\n')

    def test_missing_primary_executable_uses_fallback(self):
        self.start([['/does-not-exist/polder-locker'], self.fake(delay=.1)])
        self.assertEqual(self.connect().recv(64), b'LOCKED\n')

    def test_unresponsive_primary_is_replaced(self):
        self.start([self.fake(ack=False), self.fake()], timeout=.2)
        self.assertEqual(self.connect().recv(64), b'LOCKED\n')

    def test_both_lockers_fail_without_success(self):
        child = self.start([self.fake(ack=False), self.fake(ack=False)], timeout=.2)
        self.assertEqual(self.connect().recv(64), b'ERROR\n')
        self.assertEqual(child.wait(timeout=3), 1)

    def test_crash_after_ack_falls_back_without_confirming_unlock(self):
        child = self.start([self.fake(lifetime=.25, status=7), self.fake(lifetime=.2)])
        stream = self.connect().makefile('rb'); self.addCleanup(stream.close)
        self.assertEqual(stream.readline(), b'LOCKED\n')
        self.assertEqual(stream.readline(), b'LOCKED\n')
        self.assertEqual(stream.readline(), b'UNLOCKED\n')
        self.assertEqual(child.wait(timeout=3), 0)

    def test_idle_zero_preserves_sleep_and_explicit_lock_hooks(self):
        idle = load('idle-wayland')
        command = idle.idle_command(0)
        self.assertIn('before-sleep', command)
        self.assertIn('lock', command)
        self.assertNotIn('timeout', command)
        self.assertIn('-w', command)

    def test_invalid_idle_setting_retains_last_valid_value(self):
        idle = load('idle-wayland')
        settings = self.path / 'settings.json'
        for value in ('{', '{"lock_idle_min": -1}', '{"lock_idle_min": "bad"}', '[]'):
            settings.write_text(value)
            self.assertEqual(idle.read_timeout(settings, 300), 300)

    def test_live_idle_setting_restarts_only_owned_swayidle(self):
        fake = self.path / 'swayidle'
        fake.write_text('#!' + sys.executable + '\nimport json,os,sys,time\n'
                        'with open(os.environ["IDLE_CALLS"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                        'time.sleep(30)\n')
        fake.chmod(0o755)
        settings = self.path / 'settings.json'; settings.write_text('{"lock_idle_min": 0}')
        calls = self.path / 'calls'
        env = dict(os.environ, PATH=str(self.path) + os.pathsep + os.environ['PATH'],
                   OSB_SETTINGS=str(settings), IDLE_CALLS=str(calls))
        env.pop('POLDER_IDLE_SECS', None)
        child = subprocess.Popen([sys.executable, str(LOCK / 'idle-wayland.py')], env=env,
                                  stdout=subprocess.DEVNULL)
        self.children.append(child)
        wait_for(calls.exists)
        first = json.loads(calls.read_text().splitlines()[0])
        self.assertNotIn('timeout', first)
        settings.write_text('{"lock_idle_min": 5}')
        wait_for(lambda: len(calls.read_text().splitlines()) == 2)
        second = json.loads(calls.read_text().splitlines()[1])
        self.assertEqual(second[second.index('timeout') + 1], '300')
        self.assertIn('before-sleep', second)

    def test_suspend_only_after_successful_lock(self):
        script = self.path / 'suspend-now.sh'
        script.write_bytes((LOCK / 'suspend-now.sh').read_bytes().replace(b'\r\n', b'\n'))
        locker = self.path / 'lock-now.sh'
        systemctl = self.path / 'systemctl'
        events = self.path / 'events'
        systemctl.write_text('#!/bin/sh\necho suspend >>"$EVENTS"\n'); systemctl.chmod(0o755)
        env = dict(os.environ, PATH=str(self.path) + os.pathsep + os.environ['PATH'],
                   WAYLAND_DISPLAY='test-wayland', EVENTS=str(events))
        for status in (1, 0):
            events.unlink(missing_ok=True)
            locker.write_text(f'#!/bin/sh\necho lock >>"$EVENTS"\nexit {status}\n'); locker.chmod(0o755)
            result = subprocess.run(['sh', str(script)], env=env)
            self.assertEqual(result.returncode, status)
            self.assertEqual(events.read_text().splitlines(), ['lock'] if status else ['lock', 'suspend'])


if __name__ == '__main__':
    unittest.main()
