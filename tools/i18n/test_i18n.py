"""python3 -m unittest discover -s tools/i18n -p 'test_*.py'"""
import os, subprocess, sys, unittest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def run(code, **env):
    e = {k: v for k, v in os.environ.items() if k not in ('POLDER_LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG')}
    e.update(HOME='/nonexistent', XDG_CONFIG_HOME='/nonexistent', **env)
    return subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, "config/osb"); import polder_i18n as I; ' + code],
                          cwd=ROOT, env=e, capture_output=True, text=True, check=True).stdout.strip()

class T(unittest.TestCase):
    def test_dutch(self): self.assertEqual(run('print(I._("Settings"))', POLDER_LANG='nl'), 'Instellingen')
    def test_english(self): self.assertEqual(run('print(I._("Settings"))', POLDER_LANG='en'), 'Settings')
    def test_follows_system_locale(self):
        self.assertEqual(run('print(I.LANG)', LANG='en_GB.UTF-8'), 'en')
        self.assertEqual(run('print(I.LANG)', LANG='nl_BE.UTF-8'), 'nl')
        self.assertEqual(run('print(I.LANG)', LANG='C.UTF-8'), 'nl')     # product default
    def test_plural_and_format(self):
        self.assertEqual(run('print(I._("{n} restore points").format(n=3))', POLDER_LANG='nl'), '3 herstelpunten')
    def test_catalogs_complete(self):
        r = subprocess.run([sys.executable, 'tools/i18n/check.py'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

if __name__ == '__main__': unittest.main()
