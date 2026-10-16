#!/usr/bin/env python3
"""i18n check: untranslated/fuzzy msgids, stale .pot/.mo/.desktop, and hard-coded Dutch UI strings left in code.
Prints coverage per component (= marked strings / (marked + leftover Dutch-looking literals)). Exit 1 on problems.
  --report   only print, never fail"""
import ast, glob, os, re, sys, tempfile, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pofile, extract, desktop
DUTCH = re.compile(r"\b(de|het|een|en|van|niet|je|jouw|jij|op|met|voor|naar|wordt|worden|geen|nog|alle[s]?|nieuwe?|kies|maak|zoek|staat|aan|uit|bij|ook|wijzig\w*|bestand\w*|map|mappen|instelling\w*|melding\w*|venster\w*|scherm\w*|opnieuw|bezig|mislukt|gelukt|klaar|terug|openen|sluiten|verwijder\w*|toevoegen|annuleren|opslaan|vandaag|gekopieerd|wachtwoord|vergrendel\w*|herstel\w*|proefpolder\w*|vasteland)\b|[ëï]", re.I)
IGNORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ignore.txt')

def looks_ui(s):
    if len(s) < 2 or not re.search(r'[A-Za-zÀ-ÿ]{2}', s): return False
    if re.match(r'^(https?:|/|\.|org\.|nl\.|application/|text/|image/|\^|\\b|\(\?)', s): return False
    if re.search(r'[{};]\s*$|^\s*[.#@]?[a-z\-]+\s*\{|\\[bdsw]|\(\?P?<', s): return False   # css / regex
    return bool(DUTCH.search(s))

def leftovers():
    ign = [re.compile(l.rstrip('\n')) for l in open(IGNORE, encoding='utf-8') if l.strip() and not l.startswith('#')] if os.path.exists(IGNORE) else []
    out = collections.defaultdict(list)
    for f in extract.py_files():
        src = open(f, encoding='utf-8').read(); t = ast.parse(src); skip = set()
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('_', 'N_', 'ngettext'):
                for a in n.args: skip |= {id(x) for x in ast.walk(a)}
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0], ast.Expr): skip.add(id(n.body[0].value))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('debug', 'info', 'warning', 'error', 'exception', 'write'): skip |= {id(x) for x in ast.walk(n)}
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and looks_ui(n.value) and not any(r.search(f'{f}:{n.value}') for r in ign):
                out[extract.component(f)].append(f'{f}:{n.lineno}: {n.value[:70]!r}')
    for f in extract.rs_files():
        for i, line in enumerate(open(f, encoding='utf-8'), 1):
            code = line.split('//')[0] if not re.search(r'"[^"]*//', line) else line
            if code.strip().startswith(('//', '#[')): continue
            masked = extract.RS_CALL.sub('', code)
            for m in re.finditer(extract.RS_LIT, masked):
                s = m.group(1)
                if looks_ui(s) and not any(r.search(f'{f}:{s}') for r in ign): out[extract.component(f)].append(f'{f}:{i}: {s[:70]!r}')
    return out

def main():
    os.chdir(extract.ROOT); report = '--report' in sys.argv; problems = []
    found = extract.scan()
    pot_ids = {e.msgid for e in pofile.read('po/polder.pot') if e.msgid}
    if pot_ids != {k[1] for k in found}: problems.append('po/polder.pot is stale: run tools/i18n/extract.py && tools/i18n/update.py')
    marked = collections.Counter()
    for (ctx, mid), e in found.items():
        for c in {extract.component(r.rsplit(':', 1)[0]) for r in e.refs}: marked[c] += 1
    for l in [l.strip() for l in open('po/LINGUAS') if l.strip() and not l.startswith('#')]:
        ents = [e for e in pofile.read(f'po/{l}.po') if e.msgid]
        missing = [e for e in ents if not e.translated()]
        po_ids = {e.msgid for e in ents}
        if po_ids != {k[1] for k in found}: problems.append(f'po/{l}.po is not merged with the sources: run tools/i18n/update.py')
        for e in missing: problems.append(f'{l}: untranslated: {e.msgid[:60]!r} ({e.refs[0] if e.refs else "?"})')
        print(f'{l}: {len(ents) - len(missing)}/{len(ents)} translated ({100 * (len(ents) - len(missing)) // max(1, len(ents))}%)')
        mo = f'config/locale/{l}/LC_MESSAGES/polder.mo'
        with tempfile.NamedTemporaryFile() as tmp:
            pofile.compile_mo(pofile.read(f'po/{l}.po'), tmp.name)
            if not os.path.exists(mo) or open(mo, 'rb').read() != open(tmp.name, 'rb').read(): problems.append(f'{mo} is stale: run tools/i18n/compile.py')
    for f in desktop.main(check=True): problems.append(f'{f}: translations not applied: run tools/i18n/desktop.py')
    left = leftovers()
    print('\ncoverage per component (marked strings / marked + hard-coded Dutch literals):')
    for c in sorted(set(marked) | set(left)):
        m, lo = marked[c], len(left[c]); print(f'  {c:18} {100 * m // max(1, m + lo):3d}%  ({m} marked, {lo} left)')
    if '-v' in sys.argv:
        for c in sorted(left):
            for x in left[c]: print('   left:', x)
    for p in problems: print('PROBLEM:', p)
    return 0 if report or not problems else 1

if __name__ == '__main__': sys.exit(main())
