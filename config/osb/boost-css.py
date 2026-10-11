#!/usr/bin/env python3
"""Append ':not(#osb-x)' to every selector so our overrides beat the base theme's more specific selectors
when both live in the same theme file (GTK only live-reloads the *theme*, not ~/.config/gtk-3.0/gtk.css)."""
import sys, re
css = open(sys.argv[1]).read(); out = []
for block in re.split(r'(?<=\})', css):
    if '{' not in block: out.append(block); continue
    sel, body = block.split('{', 1)
    if sel.strip().startswith('@') or sel.strip().startswith('/*') and '*/' not in sel: out.append(block); continue
    pre = ''
    if '*/' in sel: pre, sel = sel.rsplit('*/', 1); pre += '*/'
    # handle @define-color lines that precede the selector inside the same chunk
    lines = sel.split('\n'); head = [l for l in lines if l.strip().startswith('@')]; sel = '\n'.join(l for l in lines if not l.strip().startswith('@'))
    sels = [s.strip() for s in sel.split(',') if s.strip()]
    boosted = []
    for s in sels:
        m = re.match(r'^(.*?)((?::[a-z-]+(?:\([^)]*\))?)*)$', s)   # put :not() before trailing pseudo-classes
        base, pseudo = m.group(1), m.group(2)
        if base.endswith(' '): base = base + '*'
        boosted.append(f'{base}:not(#osb-x){pseudo}')
    out.append(pre + ('\n'.join(head) + '\n' if head else '') + ', '.join(boosted) + ' {' + body)
print(''.join(out))
