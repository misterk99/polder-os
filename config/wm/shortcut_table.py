"""THE single source of Polder OS keyboard shortcuts.
- KEYD: global shortcuts; wm/keyd.py grabs exactly these (sym + mods) and dispatches 'action'. The overview
  (shortcuts/sneltoetsen.py) renders the same list, so documentation can't drift from the bindings.
- XFWM4: xfwm4 window-manager actions we document; the overview shows an entry only if xfconf currently binds it
  (read live), with the key xfconf reports.
- INAPP: keys handled inside our own popups; 'check' = (file, token) that must appear in that handler (verified by test).
Groups: Populair, Vensters en bureaus, Systeem, Navigatie, Tekst/klembord."""
KEYD = [
    # sym, mods (names), action, group, description, extra groups
    dict(sym='Super_L', mods=(), action='launcher', group='Populair', desc='Launcher openen of sluiten (Super tikken)', tap=True),
    dict(sym='F3', mods=(), action='overview', group='Vensters en bureaus', desc='Overzicht: alle vensters en bureaus', also=('Populair',)),
    dict(sym='Tab', mods=('Alt',), action='alttab', group='Vensters en bureaus', desc='Wisselen tussen vensters (Alt ingedrukt houden)', also=('Populair',)),
    dict(sym='Tab', mods=('Alt', 'Shift'), action='alttab', group='Vensters en bureaus', desc='Wisselen tussen vensters, achteruit'),
    dict(sym='bracketleft', mods=('Alt',), action='snap left', group='Vensters en bureaus', desc='Venster links vastzetten (gesplitst scherm)'),
    dict(sym='bracketright', mods=('Alt',), action='snap right', group='Vensters en bureaus', desc='Venster rechts vastzetten (gesplitst scherm)'),
    dict(sym='equal', mods=('Alt',), action='snap max', group='Vensters en bureaus', desc='Venster maximaliseren / herstellen'),
    dict(sym='minus', mods=('Alt',), action='snap min', group='Vensters en bureaus', desc='Venster minimaliseren'),
    dict(sym='l', mods=('Super',), action='lock', group='Systeem', desc='Scherm vergrendelen', also=('Populair',)),
    dict(sym='Print', mods=(), action='capture', group='Systeem', desc='Schermopname (of opname stoppen)', also=('Populair',)),
    dict(sym='F5', mods=('Ctrl', 'Shift'), action='capture', group='Systeem', desc='Schermopname (ChromeOS-toets)'),
    dict(sym='a', mods=('Super',), action='assistant', group='Systeem', desc='Polder Assistent openen', also=('Populair',)),
    dict(sym='v', mods=('Super',), action='clip', group='Tekst/klembord', desc='Klembordgeschiedenis openen', also=('Populair',)),
    dict(sym='slash', mods=('Ctrl', 'Alt'), action='shortcuts', group='Navigatie', desc='Dit overzicht met sneltoetsen', also=('Populair',)),
]
XFWM4 = {   # xfwm4 action -> (group, description)
    'close_window_key': ('Vensters en bureaus', 'Venster sluiten'),
    'maximize_window_key': ('Vensters en bureaus', 'Venster maximaliseren (xfwm4)'),
    'fullscreen_key': ('Vensters en bureaus', 'Volledig scherm aan/uit'),
    'hide_window_key': ('Vensters en bureaus', 'Venster verbergen'),
    'popup_menu_key': ('Vensters en bureaus', 'Venstermenu openen'),
    'left_workspace_key': ('Vensters en bureaus', 'Naar vorig bureau'),
    'right_workspace_key': ('Vensters en bureaus', 'Naar volgend bureau'),
    'move_window_prev_workspace_key': ('Vensters en bureaus', 'Venster naar vorig bureau'),
    'move_window_next_workspace_key': ('Vensters en bureaus', 'Venster naar volgend bureau'),
    'workspace_1_key': ('Vensters en bureaus', 'Naar Bureau 1'),
    'workspace_2_key': ('Vensters en bureaus', 'Naar Bureau 2'),
    'show_desktop_key': ('Vensters en bureaus', 'Bureaublad tonen'),
}
INAPP = [
    dict(keys=('Escape',), group='Navigatie', desc='Launcher, Snelle instellingen, agenda, klembord of schermopname sluiten', check=('launcher/launcher.py', 'KEY_Escape')),
    dict(keys=('Up',), alt=('Down',), group='Navigatie', desc='Door zoekresultaten in de launcher bladeren', check=('launcher/launcher.py', 'KEY_Down')),
    dict(keys=('Return',), group='Navigatie', desc='Geselecteerd zoekresultaat openen (rekenresultaat kopiëren)', check=('launcher/launcher.py', "'activate'")),
    dict(keys=('1',), alt=('9',), group='Tekst/klembord', desc='In klembordgeschiedenis: item 1–9 direct plakken', check=('clip/clipd.py', 'KEY_1')),
    dict(keys=('Delete',), group='Tekst/klembord', desc='In klembordgeschiedenis: geselecteerd item verwijderen', check=('clip/clipd.py', 'KEY_Delete')),
    dict(keys=('Return',), group='Systeem', desc='Schermopname: vastleggen / opname starten', check=('capture/capture.py', 'KEY_Return')),
]
GROUPS = ['Populair', 'Vensters en bureaus', 'Systeem', 'Navigatie', 'Tekst/klembord']

def xfwm4_live():
    """[(group, desc, keys tuple)] for documented xfwm4 actions that xfconf binds right now."""
    import subprocess, re
    try: out = subprocess.run(['xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-l', '-v'], capture_output=True, text=True, timeout=5).stdout
    except Exception: return []
    res = []
    for line in out.splitlines():
        m = re.match(r'/xfwm4/custom/(\S+)\s+(\S+)$', line)
        if not m or m.group(2) not in XFWM4: continue
        acc = m.group(1); mods = re.findall(r'<(\w+)>', acc); key = re.sub(r'<\w+>', '', acc)
        names = {'Primary': 'Ctrl', 'Control': 'Ctrl', 'Alt': 'Alt', 'Shift': 'Shift', 'Super': 'Super'}
        g, d = XFWM4[m.group(2)]
        if any(r[1] == d for r in res): continue   # one binding per action is enough
        res.append((g, d, tuple(names.get(x, x) for x in mods) + (key,)))
    return res
