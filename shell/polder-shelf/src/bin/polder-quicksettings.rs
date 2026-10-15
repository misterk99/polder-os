#![allow(dead_code)]
//! Polder OS Quick Settings in Rust (GTK4 + wlr-layer-shell): feature port of config/quicksettings/qs.py (Wayland path).
//! Run again -> closes the open panel (same PID file as qs.py, so the two implementations toggle each other).
#[path = "../i18n.rs"] #[macro_use] mod i18n;
#[allow(unused_imports)] use i18n::tr;
#[path = "../theme.rs"] mod theme;
#[path = "../status.rs"] mod status;
#[path = "../kdc.rs"] mod kdc;
use gtk::{gdk, gio, glib, pango, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use serde_json::Value;
use std::{cell::{Cell, RefCell}, process::{Command, Stdio}, rc::Rc, time::SystemTime};

const W: i32 = 420; const MARGIN_R: i32 = 10; const SHELF: i32 = 62; const GAP: i32 = 8; const TOP_MARGIN: i32 = 10;
fn weekday(d: i32) -> &'static str { tr("Mon Tue Wed Thu Fri Sat Sun").split(' ').nth(d as usize - 1).unwrap_or("") }
fn month(m: u32) -> &'static str { tr("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec").split(' ').nth(m as usize - 1).unwrap_or("") }

fn have(c: &str) -> bool { status::which(c) }
fn run(argv: &[&str]) {
    let mut c = Command::new(argv[0]); c.args(&argv[1..]).stdout(Stdio::null()).stderr(Stdio::null());
    use std::os::unix::process::CommandExt; c.process_group(0);
    match c.spawn() { Ok(mut ch) => { std::thread::spawn(move || ch.wait()); } Err(e) => eprintln!("run {argv:?}: {e}") }   // reap: no zombies
}
fn out(argv: &[&str]) -> String {
    Command::new(argv[0]).args(&argv[1..]).output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}
fn cpath(rel: &str) -> String { theme::config_dir().join(rel).to_string_lossy().into() }
fn pidfile() -> std::path::PathBuf { theme::rundir().join("osb-qs.pid") }
fn wayland() -> bool { std::env::var("POLDER_COMP").is_ok() && std::env::var("WAYLAND_DISPLAY").is_ok() }
fn backlight() -> bool { have("brightnessctl") && std::fs::read_dir("/sys/class/backlight").map(|mut d| d.next().is_some()).unwrap_or(false) }
fn battery() -> Option<String> {
    let mut b: Vec<_> = std::fs::read_dir("/sys/class/power_supply").ok()?.flatten().map(|e| e.path())
        .filter(|p| p.file_name().map(|f| f.to_string_lossy().starts_with("BAT")).unwrap_or(false)).collect();
    b.sort(); Some(format!("{}%", std::fs::read_to_string(b.first()?.join("capacity")).ok()?.trim()))
}
fn wifi_state() -> (bool, String) {
    let o = out(&["nmcli", "radio", "wifi"]);
    (o == "enabled", if o == "enabled" { tr("Connected") } else { tr("Off") }.into())
}
fn volume() -> f64 {   // real sink volume (qs.py starts the slider at 70)
    let v = out(&["pactl", "get-sink-volume", "@DEFAULT_SINK@"]);
    v.split('%').next().and_then(|s| s.rsplit(|c: char| !c.is_ascii_digit()).next()).and_then(|s| s.parse().ok()).unwrap_or(70.0)
}
fn cur_bri() -> f64 {
    let c: f64 = out(&["brightnessctl", "-c", "backlight", "get"]).parse().unwrap_or(0.0);
    let m: f64 = out(&["brightnessctl", "-c", "backlight", "max"]).parse().unwrap_or(0.0);
    if m > 0.0 { (c * 100.0 / m).round() } else { 100.0 }
}
fn initial() -> String {
    let n = glib::real_name().to_string_lossy().to_string();
    let n = if n.is_empty() || n == "Unknown" { glib::user_name().to_string_lossy().to_string() } else { n };
    n.chars().find(|c| c.is_alphanumeric()).map(|c| c.to_uppercase().to_string()).unwrap_or_else(|| "?".into())
}

// ---- notification service (osbnotify.call) ----
fn notify_bus() -> Option<gio::DBusConnection> {
    let addr = std::fs::read_to_string(theme::notify_dir().join("bus")).ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
        .or_else(|| std::env::var("DBUS_SESSION_BUS_ADDRESS").ok())?;
    gio::DBusConnection::for_address_sync(&addr, gio::DBusConnectionFlags::AUTHENTICATION_CLIENT | gio::DBusConnectionFlags::MESSAGE_BUS_CONNECTION,
        None::<&gio::DBusAuthObserver>, gio::Cancellable::NONE).ok()
}
fn ncall(method: &str, args: Option<glib::Variant>) {
    match notify_bus() {
        Some(b) => if let Err(e) = b.call_sync(Some("org.osbuilder.Notify"), "/org/osbuilder/Notify", "org.osbuilder.Notify", method, args.as_ref(),
                                                 None, gio::DBusCallFlags::NONE, 2000, gio::Cancellable::NONE) { eprintln!("notify {method}: {e}"); },
        None => eprintln!("notify svc unavailable"),
    }
}
fn notify_state() -> Value {
    std::fs::read_to_string(theme::notify_dir().join("state.json")).ok().and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| serde_json::json!({"history": [], "unread": 0, "dnd": false}))
}

// ---- KDE Connect phone: tile whenever KDE Connect exists; it opens the Telefoon-hub (never invents a device) ----
fn phone() -> Option<(String, String, bool)> {
    if !kdc::running() { return if kdc::installed() { Some((tr("Phone").into(), tr("Off").into(), false)) } else { None }; }
    let devs = kdc::devices();
    let Some(d) = devs.iter().find(|d| d.paired) else { return Some((tr("Phone").into(), tr("Not paired").into(), false)) };
    let sub = if !d.reachable { tr("Unreachable").to_string() } else { match kdc::info(d).battery { Some((b, _)) => format!("{b}%"), None => tr("Connected").into() } };
    Some((d.name.clone(), sub, d.reachable))
}
fn hub_bin() -> Option<String> {
    let side = std::env::current_exe().ok().and_then(|e| e.parent().map(|d| d.join("polder-phonehub"))).filter(|p| p.exists());
    std::env::var("PATH").unwrap_or_default().split(':').map(|d| std::path::Path::new(d).join("polder-phonehub")).find(|p| p.exists())
        .or(side).map(|p| p.to_string_lossy().into())
}

struct Tile { key: &'static str, icon: &'static str, title: String, sub: Option<String>, active: bool }
fn tiles() -> Vec<Tile> {
    let s = theme::settings(); let mut t = vec![];
    if have("nmcli") { let (a, sub) = wifi_state(); t.push(Tile { key: "wifi", icon: "network-wireless-signal-excellent-symbolic", title: tr("Wi‑Fi").into(), sub: Some(sub), active: a }); }
    if have("bluetoothctl") { t.push(Tile { key: "bt", icon: "bluetooth-active-symbolic", title: tr("Bluetooth").into(), sub: None, active: false }); }
    let th = s.get("theme").and_then(|v| v.as_str()).unwrap_or("light");
    t.push(Tile { key: "dark", icon: "weather-clear-night-symbolic", title: tr("Dark theme").into(),
                  sub: Some(match th { "auto" => tr("Automatic"), "dark" => tr("On"), _ => tr("Off") }.into()), active: theme::effective_dark(&s) });
    let dyn_on = s.get("color_source").and_then(|v| v.as_str()) == Some("wallpaper");
    t.push(Tile { key: "dyn", icon: "preferences-desktop-wallpaper-symbolic", title: tr("Colors from wallpaper").into(),
                  sub: Some(if dyn_on { tr("On") } else { tr("Off") }.into()), active: dyn_on });
    let (l, v) = (s.get("kbd_layout").and_then(|x| x.as_str()).unwrap_or("us").to_string(), s.get("kbd_variant").and_then(|x| x.as_str()).unwrap_or("").to_string());
    let kn = theme::LAYOUTS.iter().find(|x| x.0 == l && x.1 == v).map(|x| tr(x.2).to_string()).unwrap_or_else(|| l.to_uppercase());
    t.push(Tile { key: "kbd", icon: "input-keyboard-symbolic", title: tr("Keyboard").into(), sub: Some(kn), active: false });
    t.push(Tile { key: "cap", icon: "camera-photo-symbolic", title: tr("Screen capture").into(), sub: Some(tr("Screenshot or video").into()), active: false });
    t.push(Tile { key: "dnd", icon: "notifications-disabled-symbolic", title: tr("Do not disturb").into(), sub: None, active: notify_state()["dnd"].as_bool().unwrap_or(false) });
    if let Some((name, sub, reach)) = phone() { t.push(Tile { key: "phone", icon: "phone-symbolic", title: name, sub: Some(sub), active: reach }); }
    t
}

struct Qs {
    win: gtk::Window, histbox: gtk::Box, panel: gtk::Box, mediabox: gtk::Box, hist: Vec<Value>,
    msig: Option<Option<(String, String, String, String, String)>>, dialog_open: Cell<bool>,
    prov: gtk::CssProvider, palm: Option<SystemTime>, sh: i32,
}
type Q = Rc<RefCell<Qs>>;

fn quit() -> ! {
    let _ = std::fs::remove_file(pidfile());
    let _ = std::fs::write(theme::rundir().join("osb-qs.closed"), "");   // see main(): a click on the shelf pill both unfocuses and re-toggles
    std::process::exit(0)
}

fn pill(text: &str, icon: Option<&str>) -> gtk::Button {
    let b = gtk::Button::new(); b.add_css_class("pill"); let bx = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    if let Some(i) = icon { bx.append(&gtk::Image::from_icon_name(i)); }
    bx.append(&gtk::Label::new(Some(text))); b.set_child(Some(&bx)); b
}
fn round_btn(icon: &str) -> gtk::Button { let b = gtk::Button::from_icon_name(icon); b.add_css_class("round"); b }
fn lbl(t: &str, cls: &str, maxw: i32) -> gtk::Label {
    let l = gtk::Label::builder().label(t).xalign(0.0).build(); l.add_css_class(cls);
    if maxw > 0 { l.set_ellipsize(pango::EllipsizeMode::End); l.set_max_width_chars(maxw); } l
}

fn on_toggle(key: &str, on: bool) {
    match key {
        "dnd" => ncall("SetDnd", Some((on,).to_variant())),
        "wifi" => run(&["nmcli", "radio", "wifi", if on { "on" } else { "off" }]),
        "bt" => run(&["bluetoothctl", "power", if on { "on" } else { "off" }]),
        "cap" if have(if wayland() { "grim" } else { "import" }) => { run(&["sh", "-c", "sleep 0.4; exec python3 \"$0\"", &cpath("capture/capture.py")]); quit() }
        "dark" => theme::update_setting("theme", Value::from(if on { "dark" } else { "light" })),   // osb-settingsd regenerates + reloads everything
        "dyn" => theme::update_setting("color_source", Value::from(if on { "wallpaper" } else { "accent" })),   // Material You
        "kbd" => { run(&["python3", &cpath("settings/instellingen.py"), "toetsenbord"]); quit() }
        "phone" => { match hub_bin() { Some(b) => run(&[&b]), None => run(&["python3", &cpath("settings/instellingen.py"), "telefoon"]) } quit() }
        _ => {}
    }
}

fn tile_widget(t: &Tile, compact: bool) -> gtk::ToggleButton {
    let b = gtk::ToggleButton::new(); b.set_active(t.active); b.add_css_class("tile");
    if compact { b.add_css_class("mini"); b.set_child(Some(&gtk::Image::from_icon_name(t.icon))); b.set_tooltip_text(Some(&t.title)); }
    else {
        let bx = gtk::Box::new(gtk::Orientation::Horizontal, 10);
        let ic = gtk::Image::from_icon_name(t.icon); ic.set_pixel_size(24); bx.append(&ic);
        let tb = gtk::Box::new(gtk::Orientation::Vertical, 0); tb.set_valign(gtk::Align::Center); tb.set_hexpand(true);
        tb.append(&lbl(&t.title, "title", 14));
        if let Some(s) = &t.sub { tb.append(&lbl(s, "sub", 14)); }
        bx.append(&tb); b.set_child(Some(&bx));
    }
    let key = t.key; b.connect_toggled(move |b| on_toggle(key, b.is_active()));
    b
}

fn slider(icon: &str, val: f64, cb: impl Fn(i32) + 'static) -> gtk::Overlay {
    let ov = gtk::Overlay::new(); ov.add_css_class("sliderwrap");
    let s = gtk::Scale::with_range(gtk::Orientation::Horizontal, 0.0, 100.0, 1.0); s.set_value(val); s.set_draw_value(false); s.set_hexpand(true);
    s.connect_value_changed(move |w| cb(w.value() as i32)); ov.set_child(Some(&s));
    let knob = gtk::Image::from_icon_name(icon); knob.set_halign(gtk::Align::Start); knob.set_margin_start(16); knob.add_css_class("knobicon");
    knob.set_can_target(false); ov.add_overlay(&knob);
    ov
}

fn reload_css(q: &Q) {
    let mut me = q.borrow_mut();
    let m = theme::mtime(&theme::config_dir().join("palette.env"));
    if m != me.palm || me.palm.is_none() { me.palm = m; #[allow(deprecated)] me.prov.load_from_data(&theme::qs_css(&theme::palette())); }
}

fn notif_card(q: &Q, n: &Value) -> gtk::Box {
    let id = n["id"].as_u64().unwrap_or(0) as u32;
    let card = gtk::Box::new(gtk::Orientation::Horizontal, 12); card.add_css_class("card"); card.add_css_class("inner");
    let app = n["app"].as_str().unwrap_or(tr("System"));
    let icon = n["icon"].as_str().filter(|s| !s.is_empty()).map(String::from).unwrap_or_else(|| match app.to_lowercase().as_str() {
        "downloads" => "folder-download-symbolic", "systeem" => "emblem-system-symbolic", "chromium" => "web-browser-symbolic",
        "bestanden" => "system-file-manager-symbolic", _ => "dialog-information-symbolic" }.into());
    let ic = gtk::Image::from_icon_name(&icon); ic.set_pixel_size(24); ic.add_css_class("appicon"); ic.set_valign(gtk::Align::Start); card.append(&ic);
    let col = gtk::Box::new(gtk::Orientation::Vertical, 2); col.set_hexpand(true);
    let t = glib::DateTime::from_unix_local(n["time"].as_f64().unwrap_or(0.0) as i64).map(|d| format!("{:02}:{:02}", d.hour(), d.minute())).unwrap_or_default();
    col.append(&lbl(&format!("{app} · {t}"), "app", 0));
    let ti = lbl(n["summary"].as_str().unwrap_or(""), "ntitle", 0); ti.set_ellipsize(pango::EllipsizeMode::End); col.append(&ti);
    if let Some(b) = n["body"].as_str().filter(|s| !s.is_empty()) {
        let l = lbl(b, "nbody", 0); l.set_wrap(true); l.set_max_width_chars(40); l.set_lines(2); l.set_ellipsize(pango::EllipsizeMode::End); col.append(&l);
    }
    if let Some(img) = n["image"].as_str().filter(|p| std::path::Path::new(p).is_file()) {
        let p = gtk::Picture::for_filename(img); p.set_size_request(240, 120); p.set_halign(gtk::Align::Start); p.set_margin_top(6); col.append(&p);
    }
    let acts: Vec<(String, String)> = n["actions"].as_array().map(|a| a.iter().filter_map(|x| Some((x[0].as_str()?.to_string(), x[1].as_str()?.to_string())))
        .filter(|(k, _)| k != "default").collect()).unwrap_or_default();
    if !acts.is_empty() {
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_margin_top(6);
        for (k, l) in acts { let b = gtk::Button::with_label(&l); b.add_css_class("act"); b.connect_clicked(move |_| { ncall("Invoke", Some((id, k.as_str()).to_variant())); quit() }); row.append(&b); }
        col.append(&row);
    }
    card.append(&col);
    let x = gtk::Button::from_icon_name("window-close-symbolic"); x.set_tooltip_text(Some(tr("Close"))); x.add_css_class("x"); x.set_valign(gtk::Align::Start);
    let w = Rc::downgrade(q);
    x.connect_clicked(move |_| if let Some(q) = w.upgrade() {
        ncall("Dismiss", Some((id,).to_variant()));
        q.borrow_mut().hist.retain(|h| h["id"].as_u64() != Some(id as u64)); layout(&q);
    });
    card.append(&x);
    let g = gtk::GestureClick::new(); g.set_button(1);
    g.connect_released(move |_, _, _, _| { ncall("Invoke", Some((id, "default").to_variant())); quit() });
    card.add_controller(g); card.set_cursor_from_name(Some("pointer"));
    card
}

/// One column: [notification card (scrollable)] GAP [QS panel]; same width/right edge, fits above the shelf.
fn layout(q: &Q) {
    let (histbox, panel, hist, sh) = { let me = q.borrow(); (me.histbox.clone(), me.panel.clone(), me.hist.clone(), me.sh) };
    while let Some(c) = histbox.first_child() { histbox.remove(&c); }
    histbox.set_visible(false);
    let (_, ph, _, _) = panel.measure(gtk::Orientation::Vertical, W);
    let avail = sh - SHELF - TOP_MARGIN - ph - GAP;
    if !hist.is_empty() {
        let card = gtk::Box::new(gtk::Orientation::Vertical, 8); card.set_widget_name("histcard");
        let hdr = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        let l = lbl(&tf!("Notifications ({})", hist.len()), "histtitle", 0); l.set_hexpand(true); hdr.append(&l);
        let cb = gtk::Button::with_label(tr("Clear all")); cb.add_css_class("pill");
        let w = Rc::downgrade(q);
        cb.connect_clicked(move |_| if let Some(q) = w.upgrade() { ncall("ClearAll", None); q.borrow_mut().hist.clear(); layout(&q); });
        hdr.append(&cb); card.append(&hdr);
        let lst = gtk::Box::new(gtk::Orientation::Vertical, 8);
        for n in &hist { lst.append(&notif_card(q, n)); }
        let sc = gtk::ScrolledWindow::new(); sc.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic); sc.set_child(Some(&lst));
        sc.set_propagate_natural_height(true); sc.set_max_content_height((avail - 32 - 52).max(90));
        card.append(&sc); histbox.append(&card); histbox.set_visible(true);
    }
    // shrink-wrap like qs.py's resize(W, 1): the layer surface must not keep its old, taller size
    // gtk4-layer-shell only grows a mapped surface, so remap it at its new natural size (guarded against focus-out quit)
    let win = q.borrow().win.clone();
    if win.is_visible() {
        q.borrow().dialog_open.set(true); win.set_visible(false); win.set_default_size(W, 1);
        let w2 = win.clone(); glib::timeout_add_local_once(std::time::Duration::from_millis(50), move || w2.present());
        let w = Rc::downgrade(q);
        glib::timeout_add_local_once(std::time::Duration::from_millis(400), move || if let Some(q) = w.upgrade() { q.borrow().dialog_open.set(false) });
    }
}

fn refresh_media(q: &Q) {
    let m = status::media_active();
    let sig = m.as_ref().map(|m| (m.name.clone(), m.status.clone(), m.title.clone(), m.artist.clone(), m.art.clone()));
    let mb = { let me = q.borrow(); if me.msig.as_ref() == Some(&sig) { return; } me.mediabox.clone() };
    let first = q.borrow().msig.is_none(); q.borrow_mut().msig = Some(sig);
    while let Some(c) = mb.first_child() { mb.remove(&c); }
    if let Some(m) = m {
        let card = gtk::Box::new(gtk::Orientation::Horizontal, 12); card.set_widget_name("media"); card.set_hexpand(true);
        let art = if !m.art.is_empty() && std::path::Path::new(&m.art).is_file() { let p = gtk::Image::from_file(&m.art); p.set_pixel_size(48); p }
                  else { let p = gtk::Image::from_icon_name("audio-x-generic-symbolic"); p.set_pixel_size(24); p.add_css_class("mart"); p };
        card.append(&art);
        let tb = gtk::Box::new(gtk::Orientation::Vertical, 0); tb.set_valign(gtk::Align::Center); tb.set_hexpand(true);
        tb.append(&lbl(if m.title.is_empty() { tr("Unknown title") } else { &m.title }, "mtitle", 20));
        tb.append(&lbl(&[m.artist.as_str(), m.app.as_str()].iter().filter(|x| !x.is_empty()).cloned().collect::<Vec<_>>().join(" · "), "msub", 20));
        card.append(&tb);
        let playing = m.status == "Playing";
        for (icon, meth, ok, tip) in [("media-skip-backward-symbolic", "Previous", m.can_prev, tr("Previous")),
                                      (if playing { "media-playback-pause-symbolic" } else { "media-playback-start-symbolic" }, "PlayPause", true, if playing { tr("Pause") } else { tr("Play") }),
                                      ("media-skip-forward-symbolic", "Next", m.can_next, tr("Next"))] {
            let b = gtk::Button::from_icon_name(icon); b.add_css_class("mbtn"); if meth == "PlayPause" { b.add_css_class("pp"); }
            b.set_tooltip_text(Some(tip)); b.set_sensitive(ok); b.set_valign(gtk::Align::Center);
            let (name, w) = (m.name.clone(), Rc::downgrade(q));
            b.connect_clicked(move |_| { status::media_control(&name, meth); let w = w.clone();
                glib::timeout_add_local_once(std::time::Duration::from_millis(250), move || if let Some(q) = w.upgrade() { refresh_media(&q) }); });
            card.append(&b);
        }
        mb.append(&card);
    }
    if !first { layout(q); }
}

fn power_menu(q: &Q) {
    q.borrow().dialog_open.set(true);
    let d = gtk::Window::builder().title(tr("Power")).decorated(false).build(); d.set_widget_name("qswin");
    d.init_layer_shell(); d.set_namespace("polder-dialog"); d.set_layer(Layer::Overlay); d.set_keyboard_mode(KeyboardMode::Exclusive); d.set_exclusive_zone(-1);
    let card = gtk::Box::new(gtk::Orientation::Vertical, 14); card.set_widget_name("pwcard");
    card.append(&lbl(tr("What do you want to do?"), "pwtitle", 0));
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let mut opts = vec![(tr("Cancel"), 0), (tr("Sign out"), 1), (tr("Restart"), 2), (tr("Shut down"), 3)];
    if wayland() { opts.push((tr("Sleep"), 4)); }
    for (l, r) in opts {
        let b = gtk::Button::with_label(l); b.add_css_class("pill"); if r != 0 { b.add_css_class("active"); }
        let (d2, w) = (d.clone(), Rc::downgrade(q));
        b.connect_clicked(move |_| {
            d2.destroy();
            if let Some(q) = w.upgrade() { q.borrow().dialog_open.set(false); q.borrow().win.present(); }
            let iso = std::env::var("POLDEROS_ISO").is_ok();
            // SAFETY: the prototype never really powers off the box; the ISO session (POLDEROS_ISO) does it for real.
            if (1..=3).contains(&r) { println!("would run: {}", ["", "logout", "systemctl reboot", "systemctl poweroff"][r]); }
            if iso { match r {
                1 => run(&["sh", "-c", "loginctl terminate-session \"$XDG_SESSION_ID\""]), 2 => run(&["systemctl", "reboot"]), 3 => run(&["systemctl", "poweroff"]),
                4 => { run(&["sh", "-c", "\"$1\" || notify-send \"$2\" \"$3\"",
                             "polder-suspend", &cpath("lock/suspend-now.sh"), tr("Sleep did not start"), tr("Locking or sleep failed. Please try again.")]); quit() }
                _ => {} } }
        });
        row.append(&b);
    }
    card.append(&row); d.set_child(Some(&card)); d.present();
}

fn build(app: &gtk::Application) -> Q {
    let sh = gdk::Display::default().and_then(|d| d.monitors().item(0)).and_then(|m| m.downcast::<gdk::Monitor>().ok()).map(|m| m.geometry().height()).unwrap_or(768);
    let win = gtk::ApplicationWindow::new(app).upcast::<gtk::Window>();
    win.set_title(Some(tr("Quick Settings"))); win.set_widget_name("qswin"); win.set_decorated(false);
    win.init_layer_shell(); win.set_namespace("polder-quicksettings"); win.set_layer(Layer::Overlay);
    win.set_anchor(Edge::Right, true); win.set_anchor(Edge::Bottom, true);
    win.set_margin(Edge::Right, MARGIN_R); win.set_margin(Edge::Bottom, SHELF); win.set_exclusive_zone(0); win.set_keyboard_mode(KeyboardMode::OnDemand);
    let prov = gtk::CssProvider::new(); gtk::style_context_add_provider_for_display(&gdk::Display::default().unwrap(), &prov, 800);
    let ns = notify_state();
    let hist: Vec<Value> = ns["history"].as_array().cloned().unwrap_or_default().into_iter().rev().collect();
    let compact = !hist.is_empty();
    let col = gtk::Box::new(gtk::Orientation::Vertical, GAP); col.set_size_request(W, -1); win.set_child(Some(&col));
    let histbox = gtk::Box::new(gtk::Orientation::Vertical, 0); col.append(&histbox);
    let panel = gtk::Box::new(gtk::Orientation::Vertical, 12); panel.set_widget_name("panel"); col.append(&panel);
    // header
    let hdr = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let now = glib::DateTime::now_local().unwrap();
    hdr.append(&pill(&{ let (weekday, day, month) = (weekday(now.day_of_week()), now.day_of_month(), month(now.month() as u32)); tf!("{weekday} {month} {day}" ; weekday, month, day) }, Some("x-office-calendar-symbolic")));
    let sp = gtk::Box::new(gtk::Orientation::Horizontal, 0); sp.set_hexpand(true); hdr.append(&sp);
    if std::path::Path::new("/tmp/osb-update.json").exists() {   // ChromeOS 'Update' pill -> reboot (ISO only)
        let up = pill(tr("Update"), Some("go-up-symbolic")); up.add_css_class("active"); up.set_tooltip_text(Some(tr("Restart to update")));
        up.connect_clicked(|_| if std::env::var("POLDEROS_ISO").is_ok() { run(&["systemctl", "reboot"]) } else { println!("update pill: reboot (prototype: skipped)") });
        hdr.append(&up);
    }
    hdr.append(&pill(&theme::version(), None));
    panel.append(&hdr);
    let mediabox = gtk::Box::new(gtk::Orientation::Horizontal, 0); panel.append(&mediabox);
    // tiles
    let ts = tiles();
    if compact {   // ChromeOS-like: one row of round toggles when notifications exist
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_homogeneous(true);
        for t in &ts { row.append(&tile_widget(t, true)); }
        panel.append(&row);
    } else {
        let g = gtk::Grid::new(); g.set_column_spacing(8); g.set_row_spacing(8); g.set_column_homogeneous(true);
        for (i, t) in ts.iter().enumerate() { g.attach(&tile_widget(t, false), (i % 2) as i32, (i / 2) as i32, 1, 1); }
        panel.append(&g);
    }
    // sliders: only with a real audio stack / backlight
    if have("pactl") || have("amixer") {
        panel.append(&slider("audio-volume-high-symbolic", if have("pactl") { volume() } else { 70.0 }, |v| {
            if have("pactl") { run(&["pactl", "set-sink-volume", "@DEFAULT_SINK@", &format!("{v}%")]) } else { run(&["amixer", "set", "Master", &format!("{v}%")]) } }));
    }
    if backlight() {
        panel.append(&slider("display-brightness-symbolic", cur_bri(), |v| run(&["brightnessctl", "-c", "backlight", "set", &format!("{}%", v.max(5))])));
    }
    // footer
    let ft = gtk::Box::new(gtk::Orientation::Horizontal, 8); ft.set_widget_name("footer");
    let pw = round_btn("system-shutdown-symbolic"); ft.append(&pw);
    let lk = round_btn("system-lock-screen-symbolic"); ft.append(&lk);
    let av = gtk::Label::new(Some(&initial())); av.add_css_class("avatar"); ft.append(&av);
    if let Some(b) = battery() { let l = gtk::Label::new(Some(&b)); l.add_css_class("battery"); l.set_margin_start(4); ft.append(&l); }
    let sp = gtk::Box::new(gtk::Orientation::Horizontal, 0); sp.set_hexpand(true); ft.append(&sp);
    let st = round_btn("emblem-system-symbolic"); st.connect_clicked(|_| { run(&["python3", &cpath("settings/instellingen.py")]); quit() }); ft.append(&st);
    panel.append(&ft);
    lk.connect_clicked(|_| {   // lock screen starts after QS is gone so it can take the keyboard
        let mut c = Command::new("sh"); c.args(["-c", "sleep 0.3; exec \"$0\"", &cpath("lock/lock-now.sh")]);
        use std::os::unix::process::CommandExt; c.process_group(0); let _ = c.spawn(); quit()
    });

    let q: Q = Rc::new(RefCell::new(Qs { win: win.clone(), histbox, panel, mediabox, hist, msig: None, dialog_open: Cell::new(false), prov, palm: None, sh }));
    let w = Rc::downgrade(&q); pw.connect_clicked(move |_| if let Some(q) = w.upgrade() { power_menu(&q) });
    reload_css(&q); refresh_media(&q); layout(&q);
    let w = Rc::downgrade(&q);
    glib::timeout_add_local(std::time::Duration::from_secs(1), move || { if let Some(q) = w.upgrade() { refresh_media(&q); reload_css(&q); } glib::ControlFlow::Continue });
    let k = gtk::EventControllerKey::new();
    k.connect_key_pressed(|_, key, _, _| { if key == gdk::Key::Escape { quit() } glib::Propagation::Proceed });
    win.add_controller(k);
    let (w, seen) = (Rc::downgrade(&q), Rc::new(Cell::new(false)));
    win.connect_is_active_notify(move |win| {
        if win.is_active() { seen.set(true); return; }
        if !seen.get() { return; }
        let w = w.clone();
        glib::timeout_add_local_once(std::time::Duration::from_millis(150), move || if let Some(q) = w.upgrade() {
            let me = q.borrow(); if !me.win.is_active() && !me.dialog_open.get() { quit() } });
    });
    // polder-comp closes overlay panels on an outside click (layer_surface.closed): same as qs.py's destroy -> quit
    win.connect_destroy(|_| quit());
    win.connect_close_request(|_| quit());
    win.present();
    ncall("MarkRead", None);
    q
}

fn main() -> glib::ExitCode {
    let pid = pidfile();
    if let Some(p) = std::fs::read_to_string(&pid).ok().and_then(|s| s.trim().parse::<i32>().ok()) {   // toggle: close the open panel
        let _ = std::fs::remove_file(&pid);
        if unsafe { libc::kill(p, libc::SIGTERM) } == 0 { return glib::ExitCode::SUCCESS; }
    }
    // The pill click itself moved focus away and closed the panel a moment ago: that click meant "close", not "reopen".
    let closed = theme::rundir().join("osb-qs.closed");
    if theme::mtime(&closed).and_then(|t| t.elapsed().ok()).map(|e| e.as_millis() < 600).unwrap_or(false) { let _ = std::fs::remove_file(&closed); return glib::ExitCode::SUCCESS; }
    let _ = std::fs::write(&pid, std::process::id().to_string());
    if let Some(c) = std::fs::read_to_string("/tmp/osb-cal.pid").ok().and_then(|s| s.trim().parse::<i32>().ok()) { unsafe { libc::kill(c, libc::SIGTERM); } }   // exclusive with the calendar
    if gtk::init().is_err() || !gtk4_layer_shell::is_supported() { eprintln!("polder-quicksettings needs wlr-layer-shell"); let _ = std::fs::remove_file(&pid); return glib::ExitCode::FAILURE; }
    glib::unix_signal_add_local(libc::SIGTERM, || quit());
    let app = gtk::Application::new(Some("nl.polderos.QuickSettings"), gio::ApplicationFlags::NON_UNIQUE);
    let keep: Rc<RefCell<Option<Q>>> = Rc::new(RefCell::new(None)); let k = keep.clone();
    app.connect_activate(move |a| { if k.borrow().is_none() { *k.borrow_mut() = Some(build(a)); } });
    app.run_with_args::<&str>(&[])
}
