"""Rev 29.2: real rounded corners for self-drawn Polder OS surfaces.
enable(win) gives the window an ARGB visual and clears it to fully transparent on every draw, so the compositor (picom)
shows whatever is behind through the corners; the inner widget's CSS border-radius paints the rounded fill.
Returns True when active; False (no compositor / no RGBA visual) -> caller keeps its wallpaper-backdrop fallback.
Call before the window is realized (shown)."""
import cairo
from gi.repository import Gdk

def available(scr=None):
    scr = scr or Gdk.Screen.get_default()
    return bool(scr and scr.get_rgba_visual() is not None and scr.is_composited())

def _clear(w, cr):
    cr.save(); cr.set_operator(cairo.OPERATOR_SOURCE); cr.set_source_rgba(0, 0, 0, 0); cr.paint(); cr.restore(); return False

def enable(win):
    scr = win.get_screen()
    if not available(scr): win._osb_rgba = False; return False
    win.set_visual(scr.get_rgba_visual()); win.set_app_paintable(True)
    if not getattr(win, '_osb_rgba_hooked', False): win.connect('draw', _clear); win._osb_rgba_hooked = True
    win._osb_rgba = True; return True

def active(win): return getattr(win, '_osb_rgba', False)
