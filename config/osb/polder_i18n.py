"""Polder OS i18n (gettext domain 'polder', English msgids, catalogs in config/locale or /usr/share/locale).
Language: $POLDER_LANG > ~/.config/polder/language > LANGUAGE/LC_ALL/LC_MESSAGES/LANG; 'en*' -> English, else Dutch."""
import gettext, os, builtins
DOMAIN = 'polder'
HERE = os.path.dirname(os.path.abspath(__file__))
LANG_FILE = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'polder', 'language')
LANGUAGES = (('nl', 'Nederlands', 'nl_NL.UTF-8'), ('en', 'English', 'en_US.UTF-8'))

def system_language():
    for k in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        v = os.environ.get(k, '')
        if v and v not in ('C', 'POSIX') and not v.startswith('C.'):
            return 'en' if v.split(':')[0].lower().startswith('en') else 'nl'
    return 'nl'

def chosen_language():
    try: return open(LANG_FILE).read().strip() or None
    except OSError: return None

def language():
    v = os.environ.get('POLDER_LANG') or chosen_language()
    if v: return 'en' if v.lower().startswith('en') else 'nl'
    return system_language()

def localedirs():
    return [d for d in (os.environ.get('POLDER_LOCALEDIR'), os.path.join(HERE, '..', 'locale'),
                        '/usr/share/polderos/config/locale', '/usr/share/locale') if d]

LANG = language()
T = gettext.NullTranslations()
if LANG != 'en':
    for d in localedirs():
        try: T = gettext.translation(DOMAIN, d, languages=[LANG]); break
        except OSError: pass
_ = T.gettext
ngettext = T.ngettext
builtins.__dict__.setdefault('_', _)   # for modules that only use _ via builtins

if os.environ.get('POLDER_LANG') or chosen_language():   # let GTK's own strings (dialogs, file chooser) follow the choice too
    os.environ['LANGUAGE'] = LANG

ENVD = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'environment.d', '50-polder-language.conf')
LIVE_COMPONENTS = ('shelf', 'launcher', 'notifications', 'clipboard', 'sluis')   # supervised by polderos-wayland-components

def locale_of(code): return dict((c, l) for c, _n, l in LANGUAGES).get(code, 'nl_NL.UTF-8')

def set_language(code):
    """code: 'nl', 'en' or None (= follow the system locale). Writes ~/.config/polder/language (read by every Polder OS
    component at start) and ~/.config/environment.d (LANG/LANGUAGE for the next login: GTK, systemd user services)."""
    os.makedirs(os.path.dirname(LANG_FILE), exist_ok=True); os.makedirs(os.path.dirname(ENVD), exist_ok=True)
    if code is None:
        for p in (LANG_FILE, ENVD):
            try: os.remove(p)
            except FileNotFoundError: pass
        return
    open(LANG_FILE, 'w').write(code + '\n')
    open(ENVD, 'w').write(f'# written by Polder OS Instellingen › Taal en regio\nLANG={locale_of(code)}\nLANGUAGE={code}\n')

def restart_components():
    """Live apply: restart the supervised shell components (they come back within ~2 s in the new language).
    Returns the restarted names; empty when not running under polderos-wayland-components (then: sign in again)."""
    import signal
    rundir = os.environ.get('OSB_RUNDIR', '/tmp'); done = []
    for n in LIVE_COMPONENTS:
        try:
            os.kill(int(open(os.path.join(rundir, f'{n}.service.pid')).read()), signal.SIGTERM); done.append(n)
        except (OSError, ValueError): pass
    return done

def set_system_locale(code):
    """System-wide (login screen, boot menu labels, new users): localectl via polkit. Returns (ok, message)."""
    import subprocess
    try:
        r = subprocess.run(['localectl', 'set-locale', f'LANG={locale_of(code)}'], capture_output=True, text=True, timeout=120)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except (OSError, subprocess.TimeoutExpired) as e: return False, str(e)
