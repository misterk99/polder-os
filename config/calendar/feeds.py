#!/usr/bin/env python3
"""ICS feed sync + event expansion for the Polder OS calendar.
Feeds come from settings.json ('feeds'); cache: ~/.cache/osb/feeds/<id>.ics, status: status.json.
CLI: feeds.py sync [id]   -> fetch all (or one) feed, prints status JSON."""
import os, sys, json, time, datetime, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb'))
import osbsettings as S
DIR = os.path.join(S.CACHE, 'feeds'); STATUS = os.path.join(DIR, 'status.json')
LOCAL = os.path.expanduser('~/.local/share/osb/calendar.ics')   # user's own local calendar (optional, no samples)
TZ = 'Europe/Amsterdam'

def status():
    try: return json.load(open(STATUS))
    except Exception: return {}

def _save_status(st):
    os.makedirs(DIR, exist_ok=True); tmp = STATUS + '.tmp'; json.dump(st, open(tmp, 'w'), indent=1); os.replace(tmp, STATUS)

def norm_url(u):
    u = u.strip()
    if u.startswith('webcal://'): u = 'https://' + u[len('webcal://'):]
    return u

def valid_url(u):
    """Shared check (Instellingen > Agenda and Welkom): returns an error text or None."""
    if not u.strip().lower().startswith(('http://', 'https://', 'webcal://')):
        return 'Voer een geldige link in die begint met http://, https:// of webcal://'
    return None

def add(name, url, color='#0b57d0'):
    """Append a feed to settings.json and return it (caller syncs)."""
    import uuid
    s = S.load(); f = {'id': uuid.uuid4().hex[:8], 'name': name or 'Agenda', 'url': url.strip(), 'color': color}
    s['feeds'].append(f); S.save(s); return f

def sync(feed, timeout=20):
    """Fetch one feed. Returns status dict; keeps the previous cache on failure (and says so)."""
    st = {'last_try': time.time()}
    try:
        req = urllib.request.Request(norm_url(feed['url']), headers={'User-Agent': 'PolderOS-Agenda/0.13'})
        with urllib.request.urlopen(req, timeout=timeout) as r: data = r.read(20 * 1024 * 1024)
        txt = data.decode('utf-8', 'replace')
        if 'BEGIN:VCALENDAR' not in txt[:2000]: raise ValueError('geen iCalendar-gegevens (BEGIN:VCALENDAR ontbreekt)')
        import icalendar
        cal = icalendar.Calendar.from_ical(txt)
        n = sum(1 for c in cal.walk('VEVENT'))
        os.makedirs(DIR, exist_ok=True); open(os.path.join(DIR, feed['id'] + '.ics'), 'w').write(txt)
        st.update(ok=True, last_sync=time.time(), events=n, error=None, calname=str(cal.get('X-WR-CALNAME', '')))
    except urllib.error.HTTPError as e: st.update(ok=False, error=f'HTTP {e.code} {e.reason}')
    except urllib.error.URLError as e: st.update(ok=False, error=f'Netwerkfout: {e.reason}')
    except Exception as e: st.update(ok=False, error=f'{type(e).__name__}: {e}')
    all_st = status(); prev = all_st.get(feed['id'], {})
    if not st['ok']: st['last_sync'] = prev.get('last_sync'); st['events'] = prev.get('events')
    all_st[feed['id']] = st; _save_status(all_st); return st

def sync_all(only=None):
    s = S.load(); out = {}
    for f in s['feeds']:
        if only and f['id'] != only: continue
        out[f['id']] = sync(f)
    # drop cache of removed feeds
    ids = {f['id'] for f in s['feeds']}
    if os.path.isdir(DIR):
        for fn in os.listdir(DIR):
            if fn.endswith('.ics') and fn[:-4] not in ids: os.remove(os.path.join(DIR, fn))
    return out

_parsed = {}
def _calendar(path):
    import icalendar
    m = os.path.getmtime(path)
    if path not in _parsed or _parsed[path][0] != m:
        _parsed[path] = (m, icalendar.Calendar.from_ical(open(path, encoding='utf-8', errors='replace').read()))
    return _parsed[path][1]

def events_between(start, end):
    """All events overlapping [start, end) (dates) from all cached feeds + local calendar, expanded
    (RRULE/RDATE/EXDATE via recurring_ical_events), converted to Europe/Amsterdam.
    Returns {date: [event]} with multi-day events listed on every day they cover."""
    import recurring_ical_events
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TZ); s = S.load()
    sources = [(os.path.join(DIR, f['id'] + '.ics'), f.get('name', 'Agenda'), f.get('color', '#0b57d0')) for f in s['feeds']]
    if os.path.exists(LOCAL): sources.append((LOCAL, 'Lokaal', None))
    out = {}
    for path, name, color in sources:
        if not os.path.exists(path): continue
        try: cal = _calendar(path); occ = recurring_ical_events.of(cal).between(start, end)
        except Exception as e: print('agenda', path, e, file=sys.stderr); continue
        for ev in occ:
            ds, de = ev.get('DTSTART').dt, ev.get('DTEND').dt if ev.get('DTEND') else None
            allday = not isinstance(ds, datetime.datetime)
            if allday:
                d0 = ds; d1 = (de - datetime.timedelta(days=1)) if de else ds
                t0 = t1 = None
            else:
                if ds.tzinfo is None: ds = ds.replace(tzinfo=tz)           # floating time = local
                ds = ds.astimezone(tz)
                if de is None: de = ds + (ev.get('DURATION').dt if ev.get('DURATION') else datetime.timedelta(0))
                if de.tzinfo is None: de = de.replace(tzinfo=tz)
                de = de.astimezone(tz)
                d0 = ds.date(); d1 = (de - datetime.timedelta(seconds=1)).date() if de > ds else d0
                t0, t1 = ds, de
            item = {'title': str(ev.get('SUMMARY', '(geen titel)')), 'loc': str(ev.get('LOCATION', '') or ''),
                    'allday': allday, 'start': t0, 'end': t1, 'first': d0, 'last': d1, 'cal': name, 'color': color}
            d = max(d0, start)
            while d <= d1 and d < end:
                out.setdefault(d, []).append(item); d += datetime.timedelta(days=1)
    for k in out: out[k].sort(key=lambda e: (not e['allday'], e['start'] or datetime.datetime.min.replace(tzinfo=tz)))
    return out

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'sync':
        print(json.dumps(sync_all(sys.argv[2] if len(sys.argv) > 2 else None), indent=1))
