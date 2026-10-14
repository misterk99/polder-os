#![allow(dead_code)]
//! Polder OS notification service in Rust (GTK4 + wlr-layer-shell): port of config/notify/osb-notifyd.py.
//! Owns org.freedesktop.Notifications, shows ChromeOS-style toasts bottom-right (QS column), keeps history/unread/DND in
//! $OSB_NOTIFY_DIR/state.json in exactly the osb-notifyd.py format (read by QS, shelf, phone hub), and exposes
//! org.osbuilder.Notify (ClearAll, Dismiss, MarkRead, SetDnd, Invoke).
#[path = "../theme.rs"] mod theme;
use gtk::{gdk, gio, glib, pango, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use serde_json::{json, Value};
use std::{cell::RefCell, io::{BufRead, BufReader, Write}, process::{Command, Stdio}, rc::Rc, time::{Duration, Instant, SystemTime}};

const CARD_W: i32 = 420; const GAP: i32 = 8; const SHELF: i32 = 62; const MARGIN: i32 = 10; const TIMEOUT: u32 = 6000;
const FDO_PATH: &str = "/org/freedesktop/Notifications"; const FDO: &str = "org.freedesktop.Notifications";
const NAME: &str = "org.osbuilder.Notify"; const PATH: &str = "/org/osbuilder/Notify";
const XML: &str = r#"<node>
<interface name="org.freedesktop.Notifications">
 <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
  <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
  <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
 <method name="CloseNotification"><arg type="u" direction="in"/></method>
 <method name="GetCapabilities"><arg type="as" direction="out"/></method>
 <method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
  <arg type="s" direction="out"/><arg type="s" direction="out"/></method>
 <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
 <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface>
<interface name="org.osbuilder.Notify">
 <method name="ClearAll"/><method name="MarkRead"/>
 <method name="Dismiss"><arg type="u" direction="in"/></method>
 <method name="SetDnd"><arg type="b" direction="in"/></method>
 <method name="Invoke"><arg type="u" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>"#;

fn css(p: &std::collections::HashMap<String, String>) -> String {
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    format!(r#"
window.ntoast {{ background: transparent; }}
.card {{ background: {s}; border-radius: 20px; padding: 12px 14px; color: {os}; border: 1px solid {o}; font-family: Roboto; }}
.card.popup {{ border-radius: 24px; padding: 14px 16px; }}
.app {{ font-size: 11px; color: {osv}; }}
.ntitle {{ font-weight: 500; font-size: 13px; }}
.nbody {{ font-size: 12px; color: {osv}; }}
button.x {{ background: transparent; border: none; box-shadow: none; padding: 0; min-width: 24px; min-height: 24px; border-radius: 12px; color: {osv}; }}
button.x:hover {{ background: {sv}; }}
button.act {{ background: {ac}; color: {oac}; border: none; box-shadow: none; border-radius: 16px; padding: 4px 14px; min-height: 28px; font-weight: 500; }}
button.act:hover {{ background: shade({ac}, 0.95); }}
.appicon {{ background: {ac}; border-radius: 16px; min-width: 32px; min-height: 32px; color: {oac}; }}
"#, s = g("SURFACE"), os = g("ON_SURFACE"), o = g("OUTLINE"), osv = g("ON_SURFACE_VARIANT"), sv = g("SURFACE_VARIANT"),
        ac = g("ACCENT_CONTAINER"), oac = g("ON_ACCENT_CONTAINER"))
}
fn icon_for(app: &str) -> &'static str {
    match app.to_lowercase().as_str() { "downloads" => "folder-download-symbolic", "systeem" => "emblem-system-symbolic",
        "chromium" => "web-browser-symbolic", "bestanden" => "system-file-manager-symbolic", _ => "dialog-information-symbolic" }
}
fn now() -> f64 { SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap().as_secs_f64() }
fn run(argv: &[&str]) {
    let mut c = Command::new(argv[0]); c.args(&argv[1..]).stdout(Stdio::null()).stderr(Stdio::null());
    use std::os::unix::process::CommandExt; c.process_group(0);
    match c.spawn() { Ok(mut ch) => { std::thread::spawn(move || ch.wait()); } Err(e) => eprintln!("run {argv:?}: {e}") }
}
fn wayland() -> bool { std::env::var("WAYLAND_DISPLAY").is_ok() }

/// wltop.raise_app: activate the newest toplevel whose app_id/title matches (foreign-toplevel helper). Blocking, call off the main thread.
fn raise_app(cls: &str) -> bool {
    let Ok(mut p) = Command::new(theme_helper()).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn() else { return false };
    let out = p.stdout.take().unwrap(); let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || { for l in BufReader::new(out).lines().map_while(Result::ok) { if tx.send(l).is_err() { break; } } });
    let mut tl: std::collections::BTreeMap<i64, Value> = Default::default(); let end = Instant::now() + Duration::from_millis(400);
    while let Some(left) = end.checked_duration_since(Instant::now()) {
        let Ok(l) = rx.recv_timeout(left) else { break };
        let Ok(ev) = serde_json::from_str::<Value>(&l) else { continue }; let id = ev["id"].as_i64().unwrap_or(-1);
        match ev["ev"].as_str() { Some("state") => { tl.insert(id, ev); } Some("closed") => { tl.remove(&id); } _ => {} }
    }
    let c = cls.to_lowercase();
    let hit = tl.iter().filter(|(_, t)| { let a = t["app_id"].as_str().unwrap_or("").to_lowercase(); let ti = t["title"].as_str().unwrap_or("").to_lowercase();
        a == c || ti == c || a.ends_with(&format!(".{c}")) }).map(|(i, _)| *i).max();
    if let Some(i) = hit { if let Some(si) = p.stdin.as_mut() { let _ = writeln!(si, "activate {i}"); let _ = si.flush(); } std::thread::sleep(Duration::from_millis(200)); }
    let _ = p.kill(); let _ = p.wait(); hit.is_some()
}
fn theme_helper() -> String {
    if let Ok(h) = std::env::var("POLDER_TOPLEVELS") { return h; }
    for d in std::env::var("PATH").unwrap_or_default().split(':') { let p = std::path::Path::new(d).join("polder-toplevels"); if p.exists() { return p.to_string_lossy().into(); } }
    theme::config_dir().join("../compositor/polder-comp/tools/polder-toplevels").to_string_lossy().into()
}
/// open_app(): fallback for notifications without a 'default' action: open/raise the sending app.
fn open_app(n: &Value) {
    let d = n["desktop"].as_str().unwrap_or(""); let app = if d.is_empty() { n["app"].as_str().unwrap_or("") } else { d }.to_lowercase();
    let home = std::env::var("OSB_FILES_HOME").unwrap_or_else(|_| "/tmp/osb-files/Mijn bestanden".into());
    let cfg = theme::config_dir();
    match app.as_str() {
        "downloads" | "bestanden" | "files" | "thunar" => { let sub = if app == "downloads" { "Downloads" } else { "" };
            run(&[&cfg.join("files/run-files.sh").to_string_lossy(), &format!("{home}/{sub}")]) }
        "chromium" | "google chrome" | "chrome" => {
            let prof = std::env::var("POLDER_CHROMIUM_PROFILE").unwrap_or_else(|_| format!("{}/.config/chromium", std::env::var("HOME").unwrap_or_default()));
            std::thread::spawn(move || if !raise_app("chromium") { run(&["chromium", &format!("--user-data-dir={prof}"), "--no-first-run"]) }); }
        "systeem" | "system" => run(&["xfce4-settings-manager"]),
        _ => { std::thread::spawn(move || {
            if wayland() && raise_app(&app) { return; }
            glib::MainContext::default().invoke(move || {   // GIO launch on the main thread
                match gio::DesktopAppInfo::new(&format!("{app}.desktop")) {
                    Some(i) => { let ctx = gdk::Display::default().map(|d| d.app_launch_context()); if let Err(e) = i.launch(&[], ctx.as_ref()) { eprintln!("launch {app}: {e}") } }
                    None => eprintln!("no app for {app}") } }); }); }
    }
}

struct D { state: Value, next_id: u64, popups: Vec<(u64, gtk::Window)>, conn: Option<gio::DBusConnection>, prov: gtk::CssProvider, palm: Option<SystemTime> }
type R = Rc<RefCell<D>>;

fn state_file() -> std::path::PathBuf { theme::notify_dir().join("state.json") }
fn load_state() -> Value {
    let v: Value = std::fs::read_to_string(state_file()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
    if v.is_object() && v["history"].is_array() { v } else { json!({"history": [], "unread": 0, "dnd": false}) }
}
fn save(r: &R) {   // json.dump + os.replace, same layout as osb-notifyd.py
    let f = state_file(); let tmp = f.with_extension("json.tmp");
    if std::fs::write(&tmp, serde_json::to_string(&r.borrow().state).unwrap_or_default()).is_ok() { let _ = std::fs::rename(tmp, f); }
}
fn hist(r: &R) -> Vec<Value> { r.borrow().state["history"].as_array().cloned().unwrap_or_default() }
fn set_hist(r: &R, h: Vec<Value>) { r.borrow_mut().state["history"] = Value::from(h); }

fn refresh_css(r: &R) {
    let m = theme::mtime(&theme::config_dir().join("palette.env")); let mut d = r.borrow_mut();
    if m != d.palm { d.palm = m; #[allow(deprecated)] d.prov.load_from_data(&css(&theme::palette())); }
}

fn emit(r: &R, sig: &str, v: glib::Variant) {
    if let Some(c) = r.borrow().conn.clone() { let _ = c.emit_signal(None, FDO_PATH, FDO, sig, Some(&v)); }
}

fn build_card(r: &R, n: &Value) -> gtk::Widget {
    let id = n["id"].as_u64().unwrap_or(0);
    let card = gtk::Box::new(gtk::Orientation::Horizontal, 12); card.add_css_class("card"); card.add_css_class("popup");
    let icon = n["icon"].as_str().filter(|s| !s.is_empty()).map(String::from).unwrap_or_else(|| icon_for(n["app"].as_str().unwrap_or("")).into());
    let ic = gtk::Image::from_icon_name(&icon); ic.set_pixel_size(24); ic.add_css_class("appicon"); ic.set_valign(gtk::Align::Start); card.append(&ic);
    let col = gtk::Box::new(gtk::Orientation::Vertical, 2); col.set_hexpand(true);
    let t = glib::DateTime::from_unix_local(n["time"].as_f64().unwrap_or(0.0) as i64).ok().and_then(|d| d.format("%H:%M").ok()).map(|s| s.to_string()).unwrap_or_default();
    let a = gtk::Label::builder().label(format!("{} · {t}", n["app"].as_str().unwrap_or(""))).xalign(0.0).build(); a.add_css_class("app"); col.append(&a);
    let ti = gtk::Label::builder().label(n["summary"].as_str().unwrap_or("")).xalign(0.0).ellipsize(pango::EllipsizeMode::End).build(); ti.add_css_class("ntitle"); col.append(&ti);
    if let Some(b) = n["body"].as_str().filter(|s| !s.is_empty()) {
        let l = gtk::Label::builder().label(b).xalign(0.0).wrap(true).wrap_mode(pango::WrapMode::WordChar).max_width_chars(40).lines(2).ellipsize(pango::EllipsizeMode::End).build();
        l.add_css_class("nbody"); col.append(&l);
    }
    if let Some(img) = n["image"].as_str().filter(|p| std::path::Path::new(p).is_file()) {   // Revision 18: thumbnail (screenshots)
        match gtk::gdk_pixbuf::Pixbuf::from_file_at_scale(img, 240, 120, true) {
            Ok(pb) => { #[allow(deprecated)] let pic = gtk::Picture::for_pixbuf(&pb); pic.add_css_class("nthumb");
                // fixed box: a Picture in a vertical box would scale up to the column width (height-for-width)
                pic.set_size_request(pb.width(), pb.height()); let fx = gtk::Fixed::new(); fx.put(&pic, 0.0, 0.0); fx.set_size_request(pb.width(), pb.height());
                fx.set_halign(gtk::Align::Start); fx.set_margin_top(6); col.append(&fx); }
            Err(e) => eprintln!("thumb {e}") }
    }
    let acts: Vec<(String, String)> = n["actions"].as_array().map(|a| a.iter().filter_map(|x| Some((x[0].as_str()?.to_string(), x[1].as_str()?.to_string()))).collect()).unwrap_or_default();
    let acts: Vec<_> = acts.into_iter().filter(|(k, _)| k != "default").collect();
    if !acts.is_empty() {
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_margin_top(6);
        for (k, l) in acts { let b = gtk::Button::with_label(&l); b.add_css_class("act"); let r = r.clone(); b.connect_clicked(move |_| invoke(&r, id, &k)); row.append(&b); }
        col.append(&row);
    }
    card.append(&col);
    let x = gtk::Button::from_icon_name("window-close-symbolic"); x.set_tooltip_text(Some("Sluiten")); x.add_css_class("x"); x.set_valign(gtk::Align::Start);
    { let r = r.clone(); x.connect_clicked(move |_| close_popup(&r, id, 2)); }
    card.append(&x);
    let g = gtk::GestureClick::new(); g.set_button(1);
    { let r = r.clone(); g.connect_released(move |g, _, _, _| { g.set_state(gtk::EventSequenceState::Claimed); let r = r.clone(); glib::idle_add_local_once(move || invoke(&r, id, "default")); }); }
    card.add_controller(g); card.set_cursor_from_name(Some("pointer"));
    card.upcast()
}

fn notify(r: &R, app: String, replaces: u32, icon: String, summary: String, body: String, actions: Vec<String>, hints: glib::VariantDict, timeout: i32) -> u32 {
    let nid = if replaces != 0 { replaces as u64 } else { r.borrow().next_id };
    { let mut d = r.borrow_mut(); d.next_id = d.next_id.max(nid + 1); }
    let hs = |k: &str| hints.lookup_value(k, None).and_then(|v| v.str().map(String::from)).unwrap_or_default();
    let acts: Vec<Value> = actions.chunks(2).filter(|c| c.len() == 2).map(|c| json!([c[0], c[1]])).collect();
    let mut n = json!({"id": nid, "app": if app.is_empty() { "Systeem".to_string() } else { app }, "icon": if !icon.is_empty() && !icon.contains('/') { icon.clone() } else { String::new() },
                       "summary": summary, "body": body, "time": now(), "actions": acts, "desktop": hs("desktop-entry")});
    let mut img = [hs("image-path"), hs("image_path")].into_iter().find(|s| !s.is_empty()).unwrap_or_else(|| if icon.starts_with('/') { icon.clone() } else { String::new() });
    if let Some(s) = img.strip_prefix("file://") { img = s.to_string(); }
    if !img.is_empty() && std::path::Path::new(&img).is_file() { n["image"] = Value::from(img); }
    let cfg = theme::settings();   // Instellingen > Meldingen, read per notification
    let (pop, keep) = (theme::sbool(&cfg, "notifications", true), theme::sbool(&cfg, "notif_history", true));
    let secs = cfg.get("popup_secs").and_then(|v| v.as_i64()).unwrap_or(6) as i32;
    if pop || keep {
        let mut h: Vec<Value> = hist(r).into_iter().filter(|x| x["id"].as_u64() != Some(nid)).collect(); h.push(n.clone());
        let k = h.len().saturating_sub(50); set_hist(r, h[k..].to_vec());
        let u = r.borrow().state["unread"].as_i64().unwrap_or(0); r.borrow_mut().state["unread"] = Value::from(u + 1);
    }
    let dnd = r.borrow().state["dnd"].as_bool().unwrap_or(false);
    if pop && !dnd { show_popup(r, &n, if timeout == -1 || timeout == 0 { secs * 1000 } else { timeout }); }
    save(r); nid as u32
}

fn show_popup(r: &R, n: &Value, timeout: i32) {
    refresh_css(r);
    let id = n["id"].as_u64().unwrap_or(0);
    close_windows(r, id);   // replaces_id: swap the card in place
    let w = gtk::Window::builder().title("Polder melding").decorated(false).resizable(false).build(); w.add_css_class("ntoast");
    if gtk4_layer_shell::is_supported() {
        w.init_layer_shell(); w.set_namespace("polder-toast"); w.set_layer(Layer::Overlay);
        w.set_anchor(Edge::Right, true); w.set_anchor(Edge::Bottom, true); w.set_margin(Edge::Right, MARGIN); w.set_margin(Edge::Bottom, SHELF);
        w.set_exclusive_zone(0); w.set_keyboard_mode(KeyboardMode::None);
    }
    let c = build_card(r, n); c.set_size_request(CARD_W, -1); w.set_child(Some(&c));
    r.borrow_mut().popups.push((id, w.clone())); relayout(r); w.present();
    let ms = if timeout == -1 || timeout == 0 || timeout > 60000 { TIMEOUT } else { timeout.max(1) as u32 };
    let (r2, w2) = (r.clone(), w.clone());
    glib::timeout_add_local_once(Duration::from_millis(ms as u64), move || {   // expired: hide, keep in history (reason 1)
        if r2.borrow().popups.iter().any(|(i, x)| *i == id && *x == w2) { close_popup(&r2, id, 1); } });
}
fn close_windows(r: &R, nid: u64) -> bool {
    let gone: Vec<gtk::Window> = { let mut d = r.borrow_mut(); let (g, k): (Vec<_>, Vec<_>) = d.popups.drain(..).partition(|(i, _)| *i == nid); d.popups = k; g.into_iter().map(|x| x.1).collect() };
    let any = !gone.is_empty(); for w in gone { w.destroy(); } any
}
fn close_popup(r: &R, nid: u64, reason: u32) {
    close_windows(r, nid); relayout(r);
    emit(r, "NotificationClosed", (nid as u32, reason).to_variant());
}
fn invoke(r: &R, nid: u64, key: &str) {
    let Some(n) = hist(r).into_iter().find(|h| h["id"].as_u64() == Some(nid)) else { return };
    let keys: Vec<String> = n["actions"].as_array().map(|a| a.iter().filter_map(|x| x[0].as_str().map(String::from)).collect()).unwrap_or_default();
    if keys.iter().any(|k| k == key) { emit(r, "ActionInvoked", (nid as u32, key).to_variant()); } else { open_app(&n); }
    set_hist(r, hist(r).into_iter().filter(|h| h["id"].as_u64() != Some(nid)).collect());
    close_popup(r, nid, 2); save(r);
}
fn relayout(r: &R) {
    let ws: Vec<gtk::Window> = r.borrow().popups.iter().map(|x| x.1.clone()).collect();
    let mut bottom = SHELF;
    for w in ws.iter().rev() {   // newest at the bottom
        let h = w.child().map(|c| c.measure(gtk::Orientation::Vertical, CARD_W).1).unwrap_or(80);
        w.set_default_size(CARD_W, h); w.set_margin(Edge::Bottom, bottom); bottom += h + GAP;
    }
}

fn on_call(r: &R, conn: gio::DBusConnection, method: &str, p: glib::Variant, inv: gio::DBusMethodInvocation) {
    r.borrow_mut().conn = Some(conn);
    let mut ret: Option<glib::Variant> = None;
    match method {
        "GetCapabilities" => ret = Some((vec!["body", "actions", "persistence"],).to_variant()),
        "GetServerInformation" => ret = Some(("Polder OS Meldingen", "Polder OS", "0.13", "1.2").to_variant()),
        "Notify" => {
            let g = |i: usize| p.child_value(i);
            let s = |i: usize| g(i).str().unwrap_or("").to_string();
            let acts: Vec<String> = g(5).get::<Vec<String>>().unwrap_or_default();
            let hints = glib::VariantDict::new(Some(&g(6)));
            let id = notify(r, s(0), g(1).get::<u32>().unwrap_or(0), s(2), s(3), s(4), acts, hints, g(7).get::<i32>().unwrap_or(-1));
            ret = Some((id,).to_variant());
        }
        "CloseNotification" => close_popup(r, p.child_value(0).get::<u32>().unwrap_or(0) as u64, 3),
        "ClearAll" => { let mut d = r.borrow_mut(); d.state["history"] = json!([]); d.state["unread"] = json!(0); }
        "Dismiss" => { let id = p.child_value(0).get::<u32>().unwrap_or(0) as u64; set_hist(r, hist(r).into_iter().filter(|h| h["id"].as_u64() != Some(id)).collect()); close_popup(r, id, 1); }
        "MarkRead" => r.borrow_mut().state["unread"] = json!(0),
        "Invoke" => { let id = p.child_value(0).get::<u32>().unwrap_or(0) as u64; let k = p.child_value(1).str().unwrap_or("").to_string(); invoke(r, id, &k); }
        "SetDnd" => { let on = p.child_value(0).get::<bool>().unwrap_or(false); r.borrow_mut().state["dnd"] = Value::from(on);
            if on { let ids: Vec<u64> = r.borrow().popups.iter().map(|x| x.0).collect(); for i in ids { close_popup(r, i, 1); } } }
        _ => {}
    }
    save(r); inv.return_value(ret.as_ref());
}

fn main() {
    gtk::init().expect("gtk");
    let dir = theme::notify_dir(); let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::write(dir.join("bus"), std::env::var("DBUS_SESSION_BUS_ADDRESS").unwrap_or_default());
    let state = load_state();
    let next = state["history"].as_array().map(|h| h.iter().filter_map(|x| x["id"].as_u64()).max().unwrap_or(0)).unwrap_or(0) + 1;
    let prov = gtk::CssProvider::new(); gtk::style_context_add_provider_for_display(&gdk::Display::default().unwrap(), &prov, 800);
    let r: R = Rc::new(RefCell::new(D { state, next_id: next, popups: vec![], conn: None, prov, palm: None }));
    refresh_css(&r); save(&r);
    let node = gio::DBusNodeInfo::for_xml(XML).expect("xml");
    let ml = glib::MainLoop::new(None, false);
    let (r2, n2) = (r.clone(), node.clone());
    let _o1 = gio::bus_own_name(gio::BusType::Session, FDO, gio::BusNameOwnerFlags::REPLACE,
        move |conn, _| {
            for (iname, path) in [(FDO, FDO_PATH), (NAME, PATH)] {
                let Some(iface) = n2.lookup_interface(iname) else { continue };
                let r3 = r2.clone();
                if let Err(e) = conn.register_object(path, &iface).method_call(move |c, _, _, _, m, p, inv| on_call(&r3, c, m, p, inv)).build() { eprintln!("register {path}: {e}"); }
            }
            r2.borrow_mut().conn = Some(conn);
        },
        |_, _| println!("owner of org.freedesktop.Notifications"),
        { let ml = ml.clone(); move |_, _| { println!("lost org.freedesktop.Notifications"); ml.quit(); } });
    let _o2 = gio::bus_own_name(gio::BusType::Session, NAME, gio::BusNameOwnerFlags::NONE, |_, _| {}, |_, _| {}, |_, _| {});
    { let ml = ml.clone(); glib::unix_signal_add_local(libc::SIGTERM, move || { ml.quit(); glib::ControlFlow::Break }); }
    ml.run();
}
