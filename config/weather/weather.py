#!/usr/bin/env python3
"""Polder Weer (Revision 25): Open-Meteo (free, no key; KNMI HARMONIE + ECMWF via best_match) fetch + cache.
Cache ~/.cache/osb/weather.json: {'ok', 'fetched', 'place', 'data'} or {'ok': False, 'error'}. Never invents data.
Fetching runs inside osb-settingsd (no extra daemon). CLI: weather.py fetch | search <name> | pill"""
import os, sys, json, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'osb'))
import osbsettings as S
CACHE = os.path.join(S.CACHE, 'weather.json')
DEFAULT_LOC = {'name': 'Amsterdam', 'admin': 'Noord-Holland', 'lat': 52.374, 'lon': 4.8897}
MAX_AGE = 2 * 3600          # older than this -> treat as unavailable (pill hides)
UA = {'User-Agent': 'PolderOS-Weer/0.20'}

def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r: return json.loads(r.read())

def location(s=None):
    return (s or S.load()).get('weather_loc') or DEFAULT_LOC

def search(q, n=6):
    """Open-Meteo geocoding, Dutch names."""
    d = _get('https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode({'name': q, 'count': n, 'language': 'nl', 'format': 'json'}))
    return [{'name': r['name'], 'admin': ', '.join(x for x in (r.get('admin1'), r.get('country')) if x), 'lat': r['latitude'], 'lon': r['longitude']} for r in d.get('results', [])]

def fetch():
    loc = location()
    q = {'latitude': loc['lat'], 'longitude': loc['lon'], 'timezone': 'Europe/Amsterdam', 'wind_speed_unit': 'ms', 'forecast_days': 5,
         'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,is_day,precipitation',
         'hourly': 'temperature_2m,weather_code,precipitation_probability,is_day',
         'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
         'minutely_15': 'precipitation', 'forecast_minutely_15': 8}
    try:
        d = _get('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(q))
        out = {'ok': True, 'fetched': time.time(), 'place': loc, 'data': d}
    except Exception as e:
        out = {'ok': False, 'fetched': time.time(), 'error': f'{type(e).__name__}: {e}'}
    os.makedirs(S.CACHE, exist_ok=True); tmp = CACHE + '.tmp'; json.dump(out, open(tmp, 'w')); os.replace(tmp, CACHE)
    return out

def load():
    """Cached weather if fresh and ok, else None."""
    try: w = json.load(open(CACHE))
    except Exception: return None
    if not w.get('ok') or time.time() - w['fetched'] > MAX_AGE: return None
    return w

# WMO weather codes -> (Dutch text, Papirus icon base)
def describe(code, day=1):
    c = int(code); n = '' if day else '-night'
    if c == 0: return 'Helder', 'weather-clear' + n
    if c in (1, 2): return ('Licht bewolkt' if c == 1 else 'Half bewolkt'), 'weather-few-clouds' + n
    if c == 3: return 'Bewolkt', 'weather-overcast'
    if c in (45, 48): return 'Mist', 'weather-fog'
    if c in (51, 53, 55, 56, 57): return 'Motregen', 'weather-showers-scattered'
    if c in (61, 63, 65, 66, 67): return ('Lichte regen' if c == 61 else 'Regen'), 'weather-showers'
    if c in (80, 81, 82): return 'Buien', 'weather-showers-scattered'
    if c in (71, 73, 75, 77, 85, 86): return 'Sneeuw', 'weather-snow'
    if c in (95, 96, 99): return 'Onweer', 'weather-storm'
    return 'Onbekend', 'weather-severe-alert'

def bft(ms):
    for b, lim in enumerate((0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)):
        if ms < lim: return b
    return 12

def wind_dir(deg):
    return ['N', 'NO', 'O', 'ZO', 'Z', 'ZW', 'W', 'NW'][int((deg + 22.5) % 360 // 45)]

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'fetch'
    if cmd == 'fetch': r = fetch(); print(json.dumps({k: r[k] for k in r if k != 'data'}))
    elif cmd == 'search': print(json.dumps(search(' '.join(sys.argv[2:])), ensure_ascii=False))
    elif cmd == 'pill':   # for render-status.sh: "<icon> <temp>" or nothing
        w = load()
        if w: c = w['data']['current']; print(describe(c['weather_code'], c['is_day'])[1], f"{round(c['temperature_2m'])}°")
