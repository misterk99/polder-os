#!/usr/bin/env python3
"""Merge po/polder.pot into every po/<lang>.po (keeps translations, adds new msgids untranslated, drops obsolete ones)."""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pofile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def merge(pot, po_path, lang):
    old = {e.key: e for e in pofile.read(po_path)} if os.path.exists(po_path) else {}
    out = []
    for e in pot:
        if e.msgid == '' and e.ctxt is None:
            h = old.get((None, ''))
            out.append(h if h else pofile.Entry('', e.msgstr + f'Language: {lang}\nPlural-Forms: nplurals=2; plural=(n != 1);\n')); continue
        o = old.get(e.key)
        n = pofile.Entry(e.msgid, refs=e.refs, flags=set(e.flags), ctxt=e.ctxt, plural=e.plural)
        if o:
            n.msgstr, n.plurals, n.comments = o.msgstr, o.plurals, [c for c in o.comments if c.startswith('# ')]
            if 'fuzzy' in o.flags: n.flags.add('fuzzy')
        out.append(n)
    pofile.write(po_path, out)
    done = sum(1 for e in out[1:] if e.translated())
    print(f'{po_path}: {done}/{len(out) - 1} translated')

def main():
    os.chdir(ROOT)
    pot = pofile.read('po/polder.pot')
    langs = [l.strip() for l in open('po/LINGUAS') if l.strip() and not l.startswith('#')]
    for l in langs: merge(pot, f'po/{l}.po', l)

if __name__ == '__main__': main()
