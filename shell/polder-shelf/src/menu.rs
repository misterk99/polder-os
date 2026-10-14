//! Rounded ChromeOS-style context menu as an overlay layer surface (Rust port of osb/popmenu.py, Wayland path).
use gtk::{glib, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::{cell::Cell, rc::Rc};

pub enum Item { Sep, Entry(&'static str, String, Option<Box<dyn Fn()>>) }

pub struct PopMenu { win: gtk::Window, closed: Rc<Cell<bool>> }
impl PopMenu {
    pub fn close(&self) { close(&self.win, &self.closed) }
    pub fn is_open(&self) -> bool { !self.closed.get() }
}
fn close(w: &gtk::Window, c: &Cell<bool>) { if !c.replace(true) { w.destroy(); } }

/// anchor_above: y is the bottom edge of the menu (it grows upwards), else its top edge.
pub fn show(items: Vec<Item>, x: i32, y: i32, anchor_above: bool, title: Option<&str>, screen: (i32, i32)) -> PopMenu {
    let win = gtk::Window::builder().title("Polder menu").decorated(false).resizable(false).build();
    win.set_widget_name("pmwin");
    let closed = Rc::new(Cell::new(false));
    let card = gtk::Box::new(gtk::Orientation::Vertical, 0);
    card.set_widget_name("pmcard"); card.set_size_request(210, -1);
    if let Some(t) = title {
        let l = gtk::Label::builder().label(t).xalign(0.0).build(); l.add_css_class("pmtitle"); card.append(&l);
    }
    for it in items {
        match it {
            Item::Sep => { let s = gtk::Box::new(gtk::Orientation::Horizontal, 0); s.add_css_class("pmsep"); card.append(&s); }
            Item::Entry(icon, label, cb) => {
                let b = gtk::Button::new(); b.add_css_class("pmitem");
                let bx = gtk::Box::new(gtk::Orientation::Horizontal, 12);
                if icon.is_empty() { let e = gtk::Box::new(gtk::Orientation::Horizontal, 0); e.set_size_request(16, 16); bx.append(&e); }
                else { let im = gtk::Image::from_icon_name(icon); im.set_pixel_size(16); bx.append(&im); }
                let l = gtk::Label::builder().label(&label).xalign(0.0).hexpand(true).build(); bx.append(&l);
                b.set_child(Some(&bx));
                match cb {
                    Some(cb) => { let (w, c) = (win.clone(), closed.clone()); b.connect_clicked(move |_| { close(&w, &c); cb(); }); }
                    None => b.set_sensitive(false),
                }
                card.append(&b);
            }
        }
    }
    win.set_child(Some(&card));
    let (_, h, _, _) = card.measure(gtk::Orientation::Vertical, 210);
    let w = 210;
    let mut y = if anchor_above { y - h } else { y };
    let x = x.max(6).min(screen.0 - w - 6);
    y = y.max(6).min(screen.1 - h - 6);
    if gtk4_layer_shell::is_supported() {
        win.init_layer_shell(); win.set_namespace("polder-menu"); win.set_layer(Layer::Overlay);
        win.set_anchor(Edge::Left, true); win.set_anchor(Edge::Top, true);
        win.set_margin(Edge::Left, x); win.set_margin(Edge::Top, y);
        win.set_exclusive_zone(0); win.set_keyboard_mode(KeyboardMode::OnDemand);
    }
    // no seat grab on Wayland: close once focus moves elsewhere, or on Escape (same rule as popmenu.py)
    let (w2, c2) = (win.clone(), closed.clone());
    win.connect_is_active_notify(move |w| {
        if !w.is_active() { let (w, c) = (w2.clone(), c2.clone()); glib::timeout_add_local_once(std::time::Duration::from_millis(80), move || close(&w, &c)); }
    });
    let k = gtk::EventControllerKey::new();
    let (w3, c3) = (win.clone(), closed.clone());
    k.connect_key_pressed(move |_, key, _, _| {
        if key == gtk::gdk::Key::Escape { close(&w3, &c3); glib::Propagation::Stop } else { glib::Propagation::Proceed }
    });
    win.add_controller(k);
    win.present();
    PopMenu { win, closed }
}
