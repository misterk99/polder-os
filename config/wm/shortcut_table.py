"""THE single source of Polder OS keyboard shortcuts.
- KEYD: global shortcuts; wm/keyd.py grabs exactly these (sym + mods) and dispatches 'action'. The overview
  (shortcuts/sneltoetsen.py) renders the same list, so documentation can't drift from the bindings.
- XFWM4: xfwm4 window-manager actions we document; the overview shows an entry only if xfconf currently binds it
  (read live), with the key xfconf reports.
- INAPP: keys handled inside our own popups; 'check' = (file, token) that must appear in that handler (verified by test).
Groups: Populair, Vensters en bureaus, Systeem, Navigatie, Tekst/klembord."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
KEYD = [
    # sym, mods (names), action, group, description, extra groups
    dict(sym='Super_L', mods=(), action='launcher', group=_('Popular'), desc=_('Open or close the launcher (tap Super)'), tap=True),
    dict(sym='F3', mods=(), action='overview', group=_('Windows and desks'), desc=_('Overview: all windows and desks'), also=(_('Popular'),)),
    dict(sym='Tab', mods=('Alt',), action='alttab', group=_('Windows and desks'), desc=_('Switch between windows (hold Alt)'), also=(_('Popular'),)),
    dict(sym='Tab', mods=('Alt', 'Shift'), action='alttab', group=_('Windows and desks'), desc=_('Switch between windows, backwards')),
    dict(sym='bracketleft', mods=('Alt',), action='snap left', group=_('Windows and desks'), desc=_('Snap window left (split screen)')),
    dict(sym='bracketright', mods=('Alt',), action='snap right', group=_('Windows and desks'), desc=_('Snap window right (split screen)')),
    dict(sym='equal', mods=('Alt',), action='snap max', group=_('Windows and desks'), desc=_('Maximize / restore window')),
    dict(sym='minus', mods=('Alt',), action='snap min', group=_('Windows and desks'), desc=_('Minimize window')),
    dict(sym='bracketleft', mods=('Super',), action='desk prev', group=_('Windows and desks'), desc=_('To previous desk')),
    dict(sym='bracketright', mods=('Super',), action='desk next', group=_('Windows and desks'), desc=_('To next desk')),
    dict(sym='bracketleft', mods=('Super', 'Shift'), action='move prev', group=_('Windows and desks'), desc=_('Move window to previous desk')),
    dict(sym='bracketright', mods=('Super', 'Shift'), action='move next', group=_('Windows and desks'), desc=_('Move window to next desk')),
    dict(sym='l', mods=('Super',), action='lock', group=_('System'), desc=_('Lock screen'), also=(_('Popular'),)),
    dict(sym='Print', mods=(), action='capture', group=_('System'), desc=_('Screen capture (or stop recording)'), also=(_('Popular'),)),
    dict(sym='F5', mods=('Ctrl', 'Shift'), action='capture', group=_('System'), desc=_('Screen capture (ChromeOS key)')),
    dict(sym='a', mods=('Super',), action='assistant', group=_('System'), desc=_('Open Polder Assistant'), also=(_('Popular'),)),
    dict(sym='v', mods=('Super',), action='clip', group=_('Text/clipboard'), desc=_('Open clipboard history'), also=(_('Popular'),)),
    dict(sym='slash', mods=('Ctrl', 'Alt'), action='shortcuts', group=_('Navigation'), desc=_('This keyboard shortcut overview'), also=(_('Popular'),)),
]
XFWM4 = {   # xfwm4 action -> (group, description)
    'close_window_key': (_('Windows and desks'), _('Close window')),
    'maximize_window_key': (_('Windows and desks'), _('Maximize window (xfwm4)')),
    'fullscreen_key': (_('Windows and desks'), _('Toggle full screen')),
    'hide_window_key': (_('Windows and desks'), _('Hide window')),
    'popup_menu_key': (_('Windows and desks'), _('Open window menu')),
    'left_workspace_key': (_('Windows and desks'), _('To previous desk')),
    'right_workspace_key': (_('Windows and desks'), _('To next desk')),
    'move_window_prev_workspace_key': (_('Windows and desks'), _('Move window to previous desk')),
    'move_window_next_workspace_key': (_('Windows and desks'), _('Move window to next desk')),
    'workspace_1_key': (_('Windows and desks'), _('To Desk 1')),
    'workspace_2_key': (_('Windows and desks'), _('To Desk 2')),
    'show_desktop_key': (_('Windows and desks'), _('Show desktop')),
}
INAPP = [
    dict(keys=('Escape',), group=_('Navigation'), desc=_('Close launcher, Quick Settings, calendar, clipboard or screen capture'), check=('launcher/launcher.py', 'KEY_Escape')),
    dict(keys=('Up',), alt=('Down',), group=_('Navigation'), desc=_('Browse search results in the launcher'), check=('launcher/launcher.py', 'KEY_Down')),
    dict(keys=('Return',), group=_('Navigation'), desc=_('Open selected search result (copy calculation result)'), check=('launcher/launcher.py', "'activate'")),
    dict(keys=('1',), alt=('9',), group=_('Text/clipboard'), desc=_('In clipboard history: paste item 1–9 directly'), check=('clip/clipd.py', 'KEY_1')),
    dict(keys=('Delete',), group=_('Text/clipboard'), desc=_('In clipboard history: delete selected item'), check=('clip/clipd.py', 'KEY_Delete')),
    dict(keys=('Return',), group=_('System'), desc=_('Screen capture: capture / start recording'), check=('capture/capture.py', 'KEY_Return')),
]
GROUPS = [_('Popular'), _('Windows and desks'), _('System'), _('Navigation'), _('Text/clipboard')]

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
