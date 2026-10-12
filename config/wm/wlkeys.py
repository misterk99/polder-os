#!/usr/bin/env python3
"""Rev 34c: polder-comp key bindings from THE shortcut table (shortcut_table.KEYD), so the Wayland session binds
exactly what the Sneltoetsen overview documents. Prints 'MODS KEYSYM COMMAND' lines (MODS = '+'-joined or '-').
COMMAND '@...' = compositor-internal action, anything else is run with sh -c.  usage: wlkeys.py > keys.conf"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE); import shortcut_table as ST
CMD = {
    'alttab': '@alttab',
    'snap left': '@snap-left', 'snap right': '@snap-right', 'snap max': '@snap-max', 'snap min': '@minimize',
    'lock': f'{C}/lock/lock-now.sh',
    'capture': f'python3 {C}/capture/capture.py',
    'assistant': f'{C}/assistant/assistant-toggle.sh',
    'clip': f'{C}/clip/clip-toggle.sh',
    'shortcuts': f'python3 {C}/shortcuts/sneltoetsen.py',
    'overview': '@overview',
}
for sc in ST.KEYD:
    if sc.get('tap'): continue                       # Super tap = launcher: built into the compositor
    cmd = CMD.get(sc['action'])
    if not cmd: print(f'# no Wayland action for {sc["action"]}', file=sys.stderr); continue
    if sc['action'] == 'alttab' and 'Shift' in sc['mods']: cmd = '@alttab-back'
    print(f"{'+'.join(sc['mods']) or '-'} {sc['sym']} {cmd}")
