#!/usr/bin/env python3
"""Explicit monitor consent for xdg-desktop-portal-wlr's dmenu chooser."""
import sys


def choose(outputs):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk
    available = list(dict.fromkeys(line.strip() for line in outputs if line.strip()))
    if not available:
        return None
    dialog = Gtk.Dialog(title='Scherm delen', modal=True)
    dialog.set_default_size(460, -1)
    dialog.set_resizable(False)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.add_button('_Annuleren', Gtk.ResponseType.CANCEL)
    share = dialog.add_button('_Delen', Gtk.ResponseType.OK)
    share.get_style_context().add_class('suggested-action')
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    box = dialog.get_content_area()
    box.set_border_width(20)
    box.set_spacing(16)
    label = Gtk.Label(label='Kies het scherm dat je wilt delen.\nAlles op dit scherm is zichtbaar voor de app.')
    label.set_line_wrap(True)
    label.set_xalign(0)
    box.add(label)
    choice = Gtk.ComboBoxText()
    for output in available:
        choice.append_text(output)
    choice.set_active(0)
    box.add(choice)
    def key(_widget, event):
        if event.keyval == Gdk.KEY_Escape:
            dialog.response(Gtk.ResponseType.CANCEL)
            return True
        if event.state & Gdk.ModifierType.MOD1_MASK:
            if event.keyval in (Gdk.KEY_d, Gdk.KEY_D):
                dialog.response(Gtk.ResponseType.OK)
                return True
            if event.keyval in (Gdk.KEY_a, Gdk.KEY_A):
                dialog.response(Gtk.ResponseType.CANCEL)
                return True
        return False
    dialog.connect('key-press-event', key)
    dialog.show_all()
    response = dialog.run()
    selected = choice.get_active_text() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    return selected


if __name__ == '__main__':
    selected = choose(sys.stdin.read().splitlines())
    if selected:
        print(selected, flush=True)
    else:
        raise SystemExit(1)
