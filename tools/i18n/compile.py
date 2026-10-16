#!/usr/bin/env python3
"""Compile po/<lang>.po -> config/locale/<lang>/LC_MESSAGES/polder.mo (read by Python gettext and the Rust loader)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pofile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def main(out_root='config/locale'):
    os.chdir(ROOT)
    for l in [l.strip() for l in open('po/LINGUAS') if l.strip() and not l.startswith('#')]:
        d = os.path.join(out_root, l, 'LC_MESSAGES'); os.makedirs(d, exist_ok=True)
        n = pofile.compile_mo(pofile.read(f'po/{l}.po'), os.path.join(d, 'polder.mo'))
        print(f'{d}/polder.mo: {n - 1} messages')

if __name__ == '__main__': main(*sys.argv[1:])
