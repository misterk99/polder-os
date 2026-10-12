"""Rev 32d: run Polder OS surfaces as wlr-layer-shell surfaces (gtk-layer-shell) when the session is Wayland
(polder-comp). On X11 every call is a no-op and the old Xlib/EWMH code paths keep working.
Call setup() before the window is realized (shown)."""
import os
try:
    import gi; gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import GtkLayerShell as LS
except (ImportError, ValueError):
    LS = None
from gi.repository import Gdk

def wayland():
    d = Gdk.Display.get_default()
    return bool(d) and 'Wayland' in type(d).__name__

def available():
    return LS is not None and wayland() and LS.is_supported()

_LAYERS = {'background': 'BACKGROUND', 'bottom': 'BOTTOM', 'top': 'TOP', 'overlay': 'OVERLAY'}
_EDGES = {'left': 'LEFT', 'right': 'RIGHT', 'top': 'TOP', 'bottom': 'BOTTOM'}

def setup(win, namespace, layer='top', anchors=(), margins=None, exclusive=None, keyboard='none'):
    """anchors: iterable of 'left'/'right'/'top'/'bottom'; margins: {edge: px}; exclusive: px, -1 or None (auto);
    keyboard: 'none' | 'on_demand' | 'exclusive'. Returns True if the window became a layer surface."""
    if not available(): return False
    LS.init_for_window(win); LS.set_namespace(win, namespace)
    LS.set_layer(win, getattr(LS.Layer, _LAYERS[layer]))
    for e, n in _EDGES.items(): LS.set_anchor(win, getattr(LS.Edge, n), e in anchors)
    for e, px in (margins or {}).items(): LS.set_margin(win, getattr(LS.Edge, _EDGES[e]), int(px))
    if exclusive is None: LS.auto_exclusive_zone_enable(win)
    else: LS.set_exclusive_zone(win, int(exclusive))
    km = {'none': 'NONE', 'on_demand': 'ON_DEMAND', 'exclusive': 'EXCLUSIVE'}[keyboard]
    if hasattr(LS, 'set_keyboard_mode') and hasattr(LS, 'KeyboardMode'): LS.set_keyboard_mode(win, getattr(LS.KeyboardMode, km))
    else: LS.set_keyboard_interactivity(win, keyboard != 'none')
    win._osb_layer = True; return True

def active(win): return getattr(win, '_osb_layer', False)

def set_margins(win, margins):
    if active(win):
        for e, px in margins.items(): LS.set_margin(win, getattr(LS.Edge, _EDGES[e]), int(px))

def rundir():
    """PID/state files: OSB_RUNDIR lets a second session (e.g. polder-comp test) coexist with the X11 one."""
    return os.environ.get('OSB_RUNDIR', '/tmp')
