"""Polder Weer card (Revision 25) shown on top of the calendar popup (cal.py --weather). Real cached Open-Meteo data only."""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gi; gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import weather as WX
DAYS = ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo']

def css(P):
    return f'''
.wx {{ background: {P['SURFACE_VARIANT']}; border-radius: 18px; padding: 14px; }}
.wxtemp {{ font-size: 34px; font-weight: 400; }}
.wxdesc {{ font-size: 13px; font-weight: 500; }}
.wxsub {{ font-size: 11px; color: {P['ON_SURFACE_VARIANT']}; }}
.wxbar {{ background: {P['ACCENT']}; border-radius: 2px; }}
.wxbar0 {{ background: alpha({P['ON_SURFACE_VARIANT']}, 0.25); border-radius: 2px; }}
'''

def L(t, cls=None, x=0.0):
    l = Gtk.Label(label=t, xalign=x)
    if cls: l.get_style_context().add_class(cls)
    return l

def icon(name, px):
    i = Gtk.Image.new_from_icon_name(name + '-symbolic', Gtk.IconSize.DIALOG); i.set_pixel_size(px); return i

def card():
    w = WX.load()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); box.get_style_context().add_class('wx')
    if not w:
        box.pack_start(L('Weer niet beschikbaar (offline of geen recente gegevens).', 'wxsub'), False, False, 0); return box
    d = w['data']; c = d['current']; txt, ic = WX.describe(c['weather_code'], c['is_day'])
    top = Gtk.Box(spacing=12); top.pack_start(icon(ic, 44), False, False, 0)
    top.pack_start(L(f"{round(c['temperature_2m'])}°", 'wxtemp'), False, False, 0)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    v.pack_start(L(txt, 'wxdesc'), False, False, 0); v.pack_start(L(w['place']['name'] + ' · Open-Meteo', 'wxsub'), False, False, 0)
    top.pack_start(v, True, True, 0); box.pack_start(top, False, False, 0)
    now = c['time'][:13]; hrs = d['hourly']; i0 = next((i for i, t in enumerate(hrs['time']) if t[:13] >= now), 0)
    rain = hrs['precipitation_probability'][i0] if hrs.get('precipitation_probability') else None
    box.pack_start(L(f"Voelt als {round(c['apparent_temperature'])}° · Wind {WX.bft(c['wind_speed_10m'])} Bft {WX.wind_dir(c['wind_direction_10m'])}"
                     + (f' · Regenkans {rain}%' if rain is not None else ''), 'wxsub'), False, False, 0)
    # rain next 2 hours (minutely_15)
    mm = (d.get('minutely_15') or {}).get('precipitation') or []
    if mm:
        if max(mm) <= 0: box.pack_start(L('Droog de komende 2 uur', 'wxsub'), False, False, 0)
        else:
            rb = Gtk.Box(spacing=3); mx = max(max(mm), 1.0)
            for x in mm:
                b = Gtk.Box(); b.get_style_context().add_class('wxbar' if x > 0 else 'wxbar0'); b.set_size_request(30, max(3, int(24 * x / mx))); b.set_valign(Gtk.Align.END); rb.pack_start(b, False, False, 0)
            rb.set_size_request(-1, 24); box.pack_start(L(f'Neerslag komende 2 uur (max {max(mm):.1f} mm/15 min)', 'wxsub'), False, False, 0); box.pack_start(rb, False, False, 0)
    hs = Gtk.Box(homogeneous=True)
    for i in range(i0 + 1, min(i0 + 7, len(hrs['time']))):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        col.pack_start(L(hrs['time'][i][11:13] + ':00', 'wxsub', 0.5), False, False, 0)
        col.pack_start(icon(WX.describe(hrs['weather_code'][i], hrs['is_day'][i])[1], 18), False, False, 0)
        col.pack_start(L(f"{round(hrs['temperature_2m'][i])}°", None, 0.5), False, False, 0); hs.pack_start(col, True, True, 0)
    box.pack_start(hs, False, False, 0)
    dl = d['daily']; g = Gtk.Grid(column_spacing=10, row_spacing=2)
    for r, day in enumerate(dl['time'][:5]):
        dt = datetime.date.fromisoformat(day)
        g.attach(L('Vandaag' if r == 0 else DAYS[dt.weekday()]), 0, r, 1, 1)
        g.attach(icon(WX.describe(dl['weather_code'][r])[1], 16), 1, r, 1, 1)
        g.attach(L(f"{dl['precipitation_probability_max'][r]}%", 'wxsub', 1), 2, r, 1, 1)
        l = L(f"{round(dl['temperature_2m_min'][r])}° / {round(dl['temperature_2m_max'][r])}°", None, 1); l.set_hexpand(True); g.attach(l, 3, r, 1, 1)
    box.pack_start(g, False, False, 0)
    return box
