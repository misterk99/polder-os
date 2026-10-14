#!/usr/bin/env python3
"""Regression check: theme changes must cooperate with the session supervisor."""
import importlib.util
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'config/osb'))
spec = importlib.util.spec_from_file_location('polder_apply', ROOT / 'config/osb/apply.py')
apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply)


class SupervisedTheme(unittest.TestCase):
    def test_theme_reloads_only_owned_services_without_spawning_competitors(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.config/osb').mkdir(parents=True)
            (home / '.config/osb/gtkslot').write_text('1')
            (home / 'xsettings.service.pid').write_text('12345')
            (home / 'notifications.service.pid').write_text('12346')
            env = {'HOME': temporary, 'OSB_RUNDIR': temporary, 'DISPLAY': ':99',
                   'POLDER_SESSION_SUPERVISED': '1'}
            with mock.patch.dict(os.environ, env), mock.patch.object(apply, 'sh'), \
                    mock.patch.object(apply, 'spawn') as spawn, mock.patch('os.kill') as kill:
                apply.wayland_theme({'theme': 'dark'})
            self.assertEqual(kill.call_args_list, [mock.call(12345, signal.SIGHUP),
                                                   mock.call(12346, signal.SIGTERM)])
            spawn.assert_not_called()
            self.assertIn('PolderOS-GTK-1', (home / '.config/xsettingsd/xsettingsd.conf').read_text())

    def test_missing_child_is_left_to_its_supervisor(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {'OSB_RUNDIR': temporary}), mock.patch('os.kill') as kill:
            apply.signal_service('notifications', signal.SIGTERM)
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
