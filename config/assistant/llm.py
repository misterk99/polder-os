"""Polder Assistent cloud LLM (optional). Providers: OpenAI (Chat Completions), Google Gemini (generateContent),
Anthropic Claude (Messages). Plain urllib + SSE streaming + tool/function calling with the actions in actions.py.
Keys: libsecret via `secret-tool` when available (gnome-keyring), else ~/.config/osb/assistant-keys (chmod 600). Never in settings.json."""
import os as _i18n_os, sys as _i18n_sys; _i18n_sys.path.insert(0, _i18n_os.path.join(_i18n_os.path.dirname(_i18n_os.path.abspath(__file__)), '..', 'osb')); from polder_i18n import _, ngettext  # i18n
import os, json, shutil, subprocess, urllib.request, urllib.error
import actions as A
PROVIDERS = {'openai': ('OpenAI', 'gpt-4o-mini'), 'gemini': ('Google Gemini', 'gemini-2.0-flash'), 'claude': ('Anthropic Claude', 'claude-3-5-haiku-latest')}
KEYFILE = os.path.expanduser('~/.config/osb/assistant-keys')
SYSTEM = ('Je bent Polder Assistent, de ingebouwde assistent van Polder OS (een Debian-desktop in ChromeOS-stijl). '
          'Antwoord kort, in de taal van de gebruiker (meestal Nederlands). Gebruik de tools om echt acties uit te voeren '
          'op de computer; verzin nooit dat iets gelukt is zonder tool-resultaat.')

# ---------- keys ----------
def _secret_ok(): return shutil.which('secret-tool') is not None and bool(os.environ.get('DBUS_SESSION_BUS_ADDRESS'))
def get_key(p):
    if _secret_ok():
        r = subprocess.run(['secret-tool', 'lookup', 'service', 'polder-assistent', 'provider', p], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip(): return r.stdout.strip()
    try: return json.load(open(KEYFILE)).get(p, '')
    except Exception: return ''
def set_key(p, key):
    """Returns where the key was stored ('sleutelbos' or 'bestand')."""
    if _secret_ok():
        if key:
            r = subprocess.run(['secret-tool', 'store', '--label', _('Polder Assistant ({p})').format(p=p), 'service', 'polder-assistent', 'provider', p], input=key, capture_output=True, text=True, timeout=5)
        else: r = subprocess.run(['secret-tool', 'clear', 'service', 'polder-assistent', 'provider', p], capture_output=True, timeout=5)
        if r.returncode == 0: _file_set(p, ''); return 'sleutelbos'
    _file_set(p, key); return 'bestand'
def _file_set(p, key):
    try: d = json.load(open(KEYFILE))
    except Exception: d = {}
    if key: d[p] = key
    else: d.pop(p, None)
    if not d and not os.path.exists(KEYFILE): return
    os.makedirs(os.path.dirname(KEYFILE), exist_ok=True)
    fd = os.open(KEYFILE + '.tmp', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(d, f)
    os.chmod(KEYFILE + '.tmp', 0o600); os.replace(KEYFILE + '.tmp', KEYFILE)

def config():
    import osbsettings as S
    s = S.load(); p = s.get('assistant_provider', 'none')
    if p not in PROVIDERS: return None
    return p, (s.get('assistant_model') or {}).get(p) or PROVIDERS[p][1], get_key(p)

# ---------- HTTP ----------
class LLMError(Exception): pass
def _post(url, body, headers, stream=True, timeout=60):
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', **headers}, method='POST')
    try: return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors='replace')
        try: j = json.loads(raw); j = j[0] if isinstance(j, list) else j; msg = (j.get('error') or {}).get('message') or raw
        except Exception: msg = raw
        raise LLMError(f'HTTP {e.code}: {msg[:300]}')
    except urllib.error.URLError as e: raise LLMError(_('No connection: {reason}').format(reason=e.reason))
def _sse(resp):
    for line in resp:
        line = line.decode('utf-8', 'replace').strip()
        if line.startswith('data:'):
            d = line[5:].strip()
            if d == '[DONE]': return
            try: yield json.loads(d)
            except ValueError: pass

def _schema(params, req):
    props = {}
    for k, (t, d, enum) in params.items():
        props[k] = {'type': t, 'description': d}
        if enum: props[k]['enum'] = enum
    return {'type': 'object', 'properties': props, 'required': req}
def _tools(kind):
    T = [(n, t[1], _schema(t[2], t[3])) for n, t in A.TOOLS.items()]
    if kind == 'openai': return [{'type': 'function', 'function': {'name': n, 'description': d, 'parameters': s}} for n, d, s in T]
    if kind == 'claude': return [{'name': n, 'description': d, 'input_schema': s} for n, d, s in T]
    return [{'functionDeclarations': [{'name': n, 'description': d, **({'parameters': s} if s['properties'] else {})} for n, d, s in T]}]

# ---------- conversation ----------
def chat(history, on_text, on_tool, cfg=None, max_rounds=5):
    """history: list of {'role': 'user'|'assistant', 'content': str}. Streams text via on_text(chunk).
    on_tool(name, args) -> result string (handles confirmation + execution). Returns final assistant text."""
    p, model, key = cfg or config()
    if not key: raise LLMError(_('No API key set.'))
    return {'openai': _openai, 'gemini': _gemini, 'claude': _claude}[p](history, model, key, on_text, on_tool, max_rounds)

def _openai(history, model, key, on_text, on_tool, rounds):
    msgs = [{'role': 'system', 'content': SYSTEM}] + [dict(m) for m in history]; full = ''
    for _x in range(rounds):
        r = _post('https://api.openai.com/v1/chat/completions', {'model': model, 'messages': msgs, 'tools': _tools('openai'), 'stream': True}, {'Authorization': f'Bearer {key}'})
        text = ''; calls = {}
        for ev in _sse(r):
            for ch in ev.get('choices', []):
                d = ch.get('delta', {})
                if d.get('content'): text += d['content']; on_text(d['content'])
                for tc in d.get('tool_calls') or []:
                    c = calls.setdefault(tc['index'], {'id': '', 'name': '', 'args': ''})
                    c['id'] = tc.get('id') or c['id']; f = tc.get('function', {})
                    c['name'] += f.get('name') or ''; c['args'] += f.get('arguments') or ''
        full += text
        if not calls: return full
        msgs.append({'role': 'assistant', 'content': text or None, 'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['args'] or '{}'}} for c in calls.values()]})
        for c in calls.values():
            try: a = json.loads(c['args'] or '{}')
            except ValueError: a = {}
            msgs.append({'role': 'tool', 'tool_call_id': c['id'], 'content': on_tool(c['name'], a)})
    return full

def _claude(history, model, key, on_text, on_tool, rounds):
    msgs = [dict(m) for m in history]; full = ''
    for _x in range(rounds):
        r = _post('https://api.anthropic.com/v1/messages', {'model': model, 'max_tokens': 1024, 'system': SYSTEM, 'messages': msgs, 'tools': _tools('claude'), 'stream': True},
                  {'x-api-key': key, 'anthropic-version': '2023-06-01'})
        blocks = {}; stop = None
        for ev in _sse(r):
            t = ev.get('type')
            if t == 'content_block_start': b = dict(ev['content_block']); b['_json'] = ''; blocks[ev['index']] = b
            elif t == 'content_block_delta':
                d = ev['delta']; b = blocks[ev['index']]
                if d.get('type') == 'text_delta': b['text'] = b.get('text', '') + d['text']; full += d['text']; on_text(d['text'])
                elif d.get('type') == 'input_json_delta': b['_json'] += d.get('partial_json', '')
            elif t == 'message_delta': stop = ev.get('delta', {}).get('stop_reason')
            elif t == 'error': raise LLMError(ev.get('error', {}).get('message', 'fout'))
        content = []
        for i in sorted(blocks):
            b = blocks[i]
            if b['type'] == 'text': content.append({'type': 'text', 'text': b.get('text', '')})
            elif b['type'] == 'tool_use':
                try: inp = json.loads(b['_json'] or '{}')
                except ValueError: inp = {}
                content.append({'type': 'tool_use', 'id': b['id'], 'name': b['name'], 'input': inp})
        uses = [c for c in content if c['type'] == 'tool_use']
        if stop != 'tool_use' or not uses: return full
        msgs.append({'role': 'assistant', 'content': content})
        msgs.append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': u['id'], 'content': on_tool(u['name'], u['input'])} for u in uses]})
    return full

def _gemini(history, model, key, on_text, on_tool, rounds):
    contents = [{'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]} for m in history]; full = ''
    for _x in range(rounds):
        r = _post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse',
                  {'systemInstruction': {'parts': [{'text': SYSTEM}]}, 'contents': contents, 'tools': _tools('gemini')}, {'x-goog-api-key': key})
        parts = []; calls = []
        for ev in _sse(r):
            for cand in ev.get('candidates', []):
                for part in cand.get('content', {}).get('parts', []):
                    parts.append(part)
                    if 'text' in part: full += part['text']; on_text(part['text'])
                    if 'functionCall' in part: calls.append(part['functionCall'])
        if not calls: return full
        contents.append({'role': 'model', 'parts': parts})
        contents.append({'role': 'user', 'parts': [{'functionResponse': {'name': c['name'], 'response': {'result': on_tool(c['name'], c.get('args') or {})}}} for c in calls]})
    return full

def test(p, model, key):
    """Real minimal API call (lists nothing, generates 1 short reply). Returns (ok, message)."""
    try:
        if p == 'openai': r = _post('https://api.openai.com/v1/chat/completions', {'model': model, 'messages': [{'role': 'user', 'content': 'Zeg alleen: ok'}], 'max_tokens': 5}, {'Authorization': f'Bearer {key}'}, False, 20)
        elif p == 'claude': r = _post('https://api.anthropic.com/v1/messages', {'model': model, 'max_tokens': 5, 'messages': [{'role': 'user', 'content': 'Zeg alleen: ok'}]}, {'x-api-key': key, 'anthropic-version': '2023-06-01'}, False, 20)
        else: r = _post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', {'contents': [{'parts': [{'text': 'Zeg alleen: ok'}]}], 'generationConfig': {'maxOutputTokens': 5}}, {'x-goog-api-key': key}, False, 20)
        json.load(r); return True, _('Connected to {p0} ({model}).').format(p0=PROVIDERS[p][0], model=model)
    except LLMError as e: return False, str(e)
    except Exception as e: return False, f'{type(e).__name__}: {e}'
