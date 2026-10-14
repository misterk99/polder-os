#!/usr/bin/env python3
"""Small Linux tests for capture geometry and safe recording process ownership."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[2] / 'config/capture/capture_backend.py'
spec = importlib.util.spec_from_file_location('capture_backend', source)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, OSB_RUNDIR=self.temp.name)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_clips_partially_offscreen_window_without_expanding_it(self):
        self.assertEqual(capture.clip_rect((-30, -10, 80, 40), 100, 100), (0, 0, 50, 30))
        self.assertIsNone(capture.clip_rect((110, 0, 30, 40), 100, 100))

    def test_wayland_recording_uses_logical_geometry_and_monitor_origin(self):
        cmd = capture.recording_command('/tmp/video with spaces.mp4', (5, 7, 101, 99), True, origin=(-1280, 0))
        self.assertEqual(cmd[cmd.index('-g') + 1], '-1275,7 100x98')
        self.assertEqual(cmd[-1], '/tmp/video with spaces.mp4')
        self.assertNotIn('x11grab', cmd)

    def test_tiny_recording_is_rejected(self):
        with self.assertRaises(ValueError):
            capture.recording_command('video.mp4', (0, 0, 1, 20), True)

    def test_missing_and_stale_state_never_signal(self):
        capture.state_path().write_text(json.dumps(dict(pid=os.getpid(), start_ticks='wrong', boot_id='wrong')))
        with patch.object(os, 'pidfd_open') as opened:
            self.assertIsNone(capture.recording_state())
            self.assertFalse(capture.stop_recording())
            opened.assert_not_called()

    def test_atomic_state_is_private_and_identifies_process_lifetime(self):
        state = dict(pid=os.getpid(), start=1, file='video.mp4', **capture.process_identity(os.getpid()))
        capture.publish_state(state)
        self.assertEqual(capture.recording_state(), state)
        self.assertEqual(capture.state_path().stat().st_mode & 0o777, 0o600)

    def test_locks_are_exclusive_without_stale_pid_files(self):
        first = capture.acquire_lock('ui.lock')
        self.assertIsNotNone(first)
        self.assertIsNone(capture.acquire_lock('ui.lock'))
        os.close(first)
        second = capture.acquire_lock('ui.lock')
        self.assertIsNotNone(second)
        os.close(second)

    def test_failed_recorder_does_not_publish_or_claim_success(self):
        self.assertFalse(capture.run_recording(['/bin/false', '/tmp/never-created.mp4']))
        self.assertFalse(capture.state_path().exists())

    def test_non_video_file_is_not_a_successful_recording(self):
        path = Path(self.temp.name) / 'fake.mp4'
        path.write_bytes(b'not a video')
        self.assertFalse(capture.valid_video(path))


if __name__ == '__main__':
    unittest.main()
