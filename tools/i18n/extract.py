#!/usr/bin/env python3
"""Extract translatable strings (English msgids) into po/polder.pot.
Python: _('…'), ngettext('…','…',n) · Rust: tr("…"), tf!("…"), n_("…"), trn("…","…",n)
Data files: .desktop Name/GenericName/Comment/Keywords, polkit <message>/<description>, tools/i18n/extra.txt."""
import ast, glob, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import pofile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
COMPONENTS = {  # path prefix -> component (also used by check.py for coverage)
    'config/settings': 'settings', 'config/store': 'store', 'config/assistant': 'assistant', 'config/welcome': 'welcome',
    'config/launcher': 'launcher', 'config/shelf': 'shelf', 'config/quicksettings': 'qs', 'config/notify': 'notify',
    'config/clip': 'clip', 'config/lock': 'lock', 'config/capture': 'capture', 'config/calendar': 'calendar',
    'config/weather': 'weather', 'config/sync': 'sync', 'config/webapps': 'webapps', 'config/shortcuts': 'shortcuts',
    'config/wm': 'wm', 'config/osb': 'osb', 'config/shell': 'shell',
    'shell/polder-shelf/src/bin/polder-quicksettings.rs': 'rs-quicksettings', 'shell/polder-shelf/src/bin/polder-phonehub.rs': 'rs-phonehub',
    'shell/polder-shelf/src/bin/polder-launcher.rs': 'rs-launcher', 'shell/polder-shelf/src/bin/polder-notifyd.rs': 'rs-notifyd',
    'shell/polder-shelf/src/bin/polder-clipd.rs': 'rs-clipd', 'shell/polder-shelf/src/bin/polder-safeharbor.rs': 'rs-safeharbor',
    'shell/polder-shelf/src/bin/polder-sluis': 'rs-sluis', 'shell/polder-shelf/src/sluis.rs': 'rs-sluis',
    'shell/polder-shelf/src/bin/polder-dynamic-color.rs': 'rs-dynamic-color', 'shell/polder-shelf/src/dyncolor.rs': 'rs-dynamic-color',
    'shell/polder-shelf/src': 'rs-shelf', 'safeharbor/': 'safeharbor-helper',
}
PY_EXCLUDE = ('config/store/test_', 'config/brand/', 'config/osb/polder_i18n.py')
RS_EXCLUDE = ('sluis_tests.rs', 'i18n.rs')

def component(path):
    for k in sorted(COMPONENTS, key=len, reverse=True):
        if path.startswith(k): return COMPONENTS[k]
    return 'other'

def py_files(): return [f for f in sorted(glob.glob('config/*/*.py')) if not f.startswith(PY_EXCLUDE)] + ['safeharbor/helper/polder-safeharbor-helper']
def rs_files(): return [f for f in sorted(glob.glob('shell/polder-shelf/src/*.rs') + glob.glob('shell/polder-shelf/src/bin/*.rs')) if not f.endswith(RS_EXCLUDE)]
def data_files():
    return sorted(set(glob.glob('config/**/*.desktop', recursive=True) + glob.glob('iso/**/*.desktop', recursive=True)
                      + glob.glob('safeharbor/**/*.desktop', recursive=True) + glob.glob('debian/**/*.desktop', recursive=True)
                      + glob.glob('**/*.policy', recursive=True)))

RS_LIT = r'"((?:[^"\\]|\\.)*)"'
RS_CALL = re.compile(r'(?<![\w:])(?:crate::i18n::|i18n::)?(tr|n_|tf!|trn)\(\s*' + RS_LIT + r'(?:\s*,\s*' + RS_LIT + r')?')

def rs_unescape(s): return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t', '"': '"', '\\': '\\', "'": "'"}.get(m.group(1), '\\' + m.group(1)), s)

def scan():
    found = {}  # (ctxt,msgid) -> Entry
    def add(msgid, ref, plural=None, flag=None):
        if not msgid: return
        e = found.setdefault((None, msgid), pofile.Entry(msgid, refs=[], plural=plural))
        if plural and not e.plural: e.plural = plural
        if ref not in e.refs: e.refs.append(ref)
        if flag: e.flags.add(flag)
    for f in py_files():
        t = ast.parse(open(f, encoding='utf-8').read())
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('_', 'N_', 'ngettext') and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                pl = n.args[1].value if n.func.id == 'ngettext' and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else None
                add(n.args[0].value, f'{f}:{n.lineno}', pl, 'python-brace-format' if '{' in n.args[0].value else None)
    for f in rs_files():
        src = open(f, encoding='utf-8').read()
        for m in RS_CALL.finditer(src):
            line = src.count('\n', 0, m.start()) + 1
            pl = rs_unescape(m.group(3)) if m.group(1) == 'trn' and m.group(3) is not None else None
            add(rs_unescape(m.group(2)), f'{f}:{line}', pl, 'rust-format' if m.group(1) == 'tf!' else None)
    for f in data_files():
        for i, line in enumerate(open(f, encoding='utf-8'), 1):
            m = re.match(r'^(Name|GenericName|Comment|Keywords)=(.+)$', line.rstrip('\n'))
            if m: add(m.group(2), f'{f}:{i}')
            for m in re.finditer(r'<(message|description)>([^<]+)</\1>', line): add(m.group(2).strip(), f'{f}:{i}')
    extra = os.path.join('tools', 'i18n', 'extra.txt')   # strings in shell scripts, grub, systemd units (msgid per line, '#' comments)
    if os.path.exists(extra):
        for i, line in enumerate(open(extra, encoding='utf-8'), 1):
            line = line.rstrip('\n')
            if line and not line.startswith('#'): add(line.replace('\\n', '\n'), f'{extra}:{i}')
    return found

def main():
    os.chdir(ROOT)
    found = scan()
    hdr = pofile.Entry('', 'Project-Id-Version: Polder OS\nReport-Msgid-Bugs-To: \nPOT-Creation-Date: %s\nMIME-Version: 1.0\n'
                       'Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n' % time.strftime('%Y-%m-%d %H:%M%z'))
    ents = [hdr] + sorted(found.values(), key=lambda e: (e.refs[0], e.msgid))
    pofile.write('po/polder.pot', ents)
    print(f'po/polder.pot: {len(ents) - 1} strings')

if __name__ == '__main__': main()
