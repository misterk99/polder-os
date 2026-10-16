"""Minimal .po/.pot reader/writer + .mo compiler (pure Python; no gettext tools needed)."""
import ast, struct

def esc(s): return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')

def _q(s):
    if '\n' in s[:-1]:
        parts = s.split('\n'); out = ['""']
        for i, p in enumerate(parts):
            if i < len(parts) - 1: out.append('"%s\\n"' % esc(p))
            elif p: out.append('"%s"' % esc(p))
        return '\n'.join(out)
    return '"%s"' % esc(s)

class Entry:
    def __init__(self, msgid='', msgstr='', refs=None, comments=None, flags=None, ctxt=None, plural=None, plurals=None):
        self.msgid, self.msgstr, self.refs, self.comments = msgid, msgstr, refs or [], comments or []
        self.flags, self.ctxt, self.plural, self.plurals = flags or set(), ctxt, plural, plurals or {}
    @property
    def key(self): return (self.ctxt, self.msgid)
    def translated(self):
        if self.plural: return all(self.plurals.get(i) for i in (0, 1)) and 'fuzzy' not in self.flags
        return bool(self.msgstr) and 'fuzzy' not in self.flags

def read(path):
    entries, header, cur, field = [], '', None, None
    def flush():
        nonlocal cur
        if cur is not None:
            if cur.msgid == '' and cur.ctxt is None: entries.insert(0, cur)
            else: entries.append(cur)
        cur = None
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line:
            flush(); continue
        if cur is None: cur = Entry()
        if line.startswith('#:'): cur.refs += line[2:].split()
        elif line.startswith('#,'): cur.flags |= {f.strip() for f in line[2:].split(',')}
        elif line.startswith('#~'): continue
        elif line.startswith('#'): cur.comments.append(line)
        elif line.startswith('msgctxt '): field = 'ctxt'; cur.ctxt = ast.literal_eval(line[8:])
        elif line.startswith('msgid_plural '): field = 'plural'; cur.plural = ast.literal_eval(line[13:])
        elif line.startswith('msgid '): field = 'msgid'; cur.msgid = ast.literal_eval(line[6:])
        elif line.startswith('msgstr['):
            i = int(line[7:line.index(']')]); field = ('p', i); cur.plurals[i] = ast.literal_eval(line[line.index(']') + 1:].strip())
        elif line.startswith('msgstr '): field = 'msgstr'; cur.msgstr = ast.literal_eval(line[7:])
        elif line.startswith('"'):
            v = ast.literal_eval(line)
            if field == 'ctxt': cur.ctxt += v
            elif field == 'plural': cur.plural += v
            elif field == 'msgid': cur.msgid += v
            elif field == 'msgstr': cur.msgstr += v
            elif isinstance(field, tuple): cur.plurals[field[1]] += v
    flush()
    return entries

def write(path, entries):
    out = []
    for e in entries:
        out += e.comments
        if e.refs:
            line = '#:'
            for r in e.refs:
                if len(line) + len(r) > 78: out.append(line); line = '#:'
                line += ' ' + r
            out.append(line)
        if e.flags: out.append('#, ' + ', '.join(sorted(e.flags)))
        if e.ctxt is not None: out.append('msgctxt ' + _q(e.ctxt))
        out.append('msgid ' + _q(e.msgid))
        if e.plural is not None:
            out.append('msgid_plural ' + _q(e.plural))
            for i in (0, 1): out.append('msgstr[%d] ' % i + _q(e.plurals.get(i, '')))
        else: out.append('msgstr ' + _q(e.msgstr))
        out.append('')
    open(path, 'w', encoding='utf-8').write('\n'.join(out))

def compile_mo(entries, path):
    cat = {}
    for e in entries:
        if e.msgid == '' and e.ctxt is None: cat[b''] = e.msgstr.encode(); continue
        if not e.translated(): continue
        k = e.msgid if e.ctxt is None else e.ctxt + '\x04' + e.msgid
        if e.plural is not None:
            cat[(k + '\0' + e.plural).encode()] = (e.plurals[0] + '\0' + e.plurals[1]).encode()
        else: cat[k.encode()] = e.msgstr.encode()
    keys = sorted(cat); ids = b''; strs = b''; offs = []
    for k in keys:
        offs.append((len(ids), len(k), len(strs), len(cat[k]))); ids += k + b'\0'; strs += cat[k] + b'\0'
    n = len(keys); ko = 7 * 4; vo = ko + n * 8; idstart = vo + n * 8; strstart = idstart + len(ids)
    kt = b''.join(struct.pack('<II', l, idstart + o) for o, l, _, _ in offs)
    vt = b''.join(struct.pack('<II', l, strstart + o) for _, _, o, l in offs)
    data = struct.pack('<7I', 0x950412de, 0, n, ko, vo, 0, 0) + kt + vt + ids + strs
    open(path, 'wb').write(data)
    return n
