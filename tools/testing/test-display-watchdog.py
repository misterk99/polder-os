#!/usr/bin/env python3
"""Regression: locking during a preview cannot abandon its rollback."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('displays', ROOT / 'config/osb/wayland_display.py')
D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)


class Watchdog(unittest.TestCase):
    def test_locked_refusal_is_retried_without_allowing_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, XDG_RUNTIME_DIR=temporary):
            output = dict(name='TEST', make='Polder', model='VM', serial='1', enabled=True,
                          modes=[dict(width=1366, height=768, refresh=60, current=True)],
                          scale=1, transform='normal', position=dict(x=0, y=0))
            D.write_state(dict(token='test', status='preview', previous=[D.profile(output)], deadline=0))
            attempts = []
            def apply(profiles):
                attempts.append(profiles)
                if len(attempts) == 1: raise RuntimeError('configuration refused while locked')
                self.assertEqual(D.read_state()['status'], 'restoring')
            def wait(_seconds):
                self.assertEqual(D.read_state()['status'], 'restoring')
                with self.assertRaises(RuntimeError): D.decide('test', True)
            with patch.object(D, 'outputs', return_value=[output]), patch.object(D, 'apply', side_effect=apply), patch.object(D.time, 'sleep', side_effect=wait):
                D.guard('test')
            self.assertEqual(len(attempts), 2)
            self.assertEqual(D.read_state()['status'], 'reverted')


if __name__ == '__main__': unittest.main()
