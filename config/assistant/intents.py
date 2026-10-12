"""Polder Assistent local intent engine (no key, no network): Dutch + English phrases -> (tool, args).
parse(text) returns (tool, args) or None. Deliberately rule-based so it is predictable and offline."""
import re

def _num(t):
    m = re.search(r'(\d{1,3})\s*(%|procent|percent)?', t); return int(m.group(1)) if m else None

def _onoff(t):
    if re.search(r'\b(uit|off|uitzetten|uitschakelen|disable|stop)\b', t): return False
    if re.search(r'\b(aan|on|aanzetten|inschakelen|enable|start)\b', t): return True
    return None

RULES = []
def rule(pat):
    def deco(f): RULES.append((re.compile(pat), f)); return f
    return deco

@rule(r'\b(donker|dark|nacht)\w*\b.*\b(thema|modus|mode|theme)\b|\b(thema|theme|modus|mode)\b.*\b(donker|dark)\b|^(donker|dark)( mode| modus)?$')
def _dark(t, m): return ('set_theme', {'mode': 'dark'})
@rule(r'\b(licht|light)\w*\b.*\b(thema|modus|mode|theme)\b|\b(thema|theme|modus|mode)\b.*\b(licht|light)\b|^(licht|light)( mode| modus)?$')
def _light(t, m): return ('set_theme', {'mode': 'light'})
@rule(r'\b(wissel|switch|toggle)\b.*\b(thema|theme)\b')
def _toggle(t, m): return ('set_theme', {'mode': 'toggle'})
@rule(r'\b(volume|geluid|sound)\b')
def _vol(t, m):
    n = _num(t)
    if n is None and re.search(r'\b(uit|mute|dempen|stil)\b', t): n = 0
    if n is None and re.search(r'\b(max|vol|maximaal)\b', t): n = 100
    return ('set_volume', {'level': n}) if n is not None else None
@rule(r'\b(helderheid|brightness|scherm feller|scherm donkerder)\b')
def _bri(t, m):
    n = _num(t); return ('set_brightness', {'level': n}) if n is not None else None
@rule(r'\b(wifi|wi-fi|wlan)\b')
def _wifi(t, m):
    o = _onoff(t); return ('set_wifi', {'on': o}) if o is not None else None
@rule(r'\b(bluetooth)\b')
def _bt(t, m):
    o = _onoff(t); return ('set_bluetooth', {'on': o}) if o is not None else None
@rule(r'\b(niet storen|do not disturb|dnd|stil modus)\b')
def _dnd(t, m):
    o = _onoff(t); return ('set_dnd', {'on': True if o is None else o})
@rule(r'\b(vergrendel|lock)\w*\b')
def _lock(t, m): return ('lock_screen', {})
@rule(r'\b(schermafbeelding|screenshot|schermopname)\b')
def _shot(t, m): return ('screenshot', {})
@rule(r'\b(weer|weather|regen|rain|temperatuur|temperature)\b')
def _wx(t, m): return ('get_weather', {})
@rule(r'\b(agenda|kalender|calendar)\b')
def _cal(t, m): return ('open_calendar', {})
@rule(r'^(zoek|vind|find|search)( naar| for)?( (het )?(bestand(en)?|files?))? (?P<q>.+)$')
def _files(t, m): return ('search_files', {'query': m.group('q').strip(' "\'')})
@rule(r'^(open|start|launch|openen|starten)(\s+de|\s+het)?\s+(?P<a>.+?)( app)?$')
def _open(t, m): return ('open_app', {'name': m.group('a').strip()})

def parse(text):
    t = text.strip().lower().rstrip('.!?')
    t = re.sub(r'^(hey |hoi |polder,? |kun je |can you |wil je |please |alsjeblieft |zet |set |turn |doe )+', '', t)
    for pat, f in RULES:
        m = pat.search(t)
        if m:
            r = f(t, m)
            if r: return r
    return None
