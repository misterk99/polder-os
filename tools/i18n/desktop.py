#!/usr/bin/env python3
"""Write translations from po/<lang>.po into .desktop files (Key[lang]=…) and polkit policies (<message xml:lang=…>).
Base values stay English (the msgids). Run after editing translations; check.py verifies the files are in sync."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pofile, extract
ROOT = extract.ROOT

def catalogs():
    langs = [l.strip() for l in open('po/LINGUAS') if l.strip() and not l.startswith('#')]
    return {l: {e.msgid: e.msgstr for e in pofile.read(f'po/{l}.po') if e.translated() and e.msgid} for l in langs}

def render(path, cats):
    src = open(path, encoding='utf-8').read()
    if path.endswith('.desktop'):
        out = []
        for line in src.split('\n'):
            if re.match(r'^(Name|GenericName|Comment|Keywords)\[[\w@]+\]=', line): continue   # regenerated below
            out.append(line)
            m = re.match(r'^(Name|GenericName|Comment|Keywords)=(.+)$', line)
            if m:
                for l, c in sorted(cats.items()):
                    if m.group(2) in c and c[m.group(2)] != m.group(2): out.append(f'{m.group(1)}[{l}]={c[m.group(2)]}')
        return '\n'.join(out)
    out = []
    for line in src.split('\n'):
        if re.search(r'<(message|description) xml:lang=', line): continue
        out.append(line)
        m = re.match(r'^(\s*)<(message|description)>([^<]+)</\2>', line)
        if m:
            for l, c in sorted(cats.items()):
                if m.group(3) in c: out.append(f'{m.group(1)}<{m.group(2)} xml:lang="{l}">{c[m.group(3)]}</{m.group(2)}>')
    return '\n'.join(out)

def main(check=False):
    os.chdir(ROOT); cats = catalogs(); stale = []
    for f in extract.data_files():
        new = render(f, cats)
        if new != open(f, encoding='utf-8').read():
            stale.append(f)
            if not check: open(f, 'w', encoding='utf-8').write(new)
    for f in stale: print(('stale: ' if check else 'updated: ') + f)
    return stale

if __name__ == '__main__': sys.exit(1 if main('--check' in sys.argv) and '--check' in sys.argv else 0)
