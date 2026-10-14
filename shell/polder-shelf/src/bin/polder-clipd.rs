#![allow(dead_code)]
//! Polder OS clipboard history in Rust (ChromeOS Super+V): port of config/clip/clipd.py (Wayland path).
//! Resident: watches the clipboard through wlr-data-control (`wl-paste --watch`), records text + images (max 10,
//! ~/.cache/osb/clipboard/history.json, same format as clipd.py), skips content flagged by password managers
//! (x-kde-passwordManagerHint). SIGUSR1 toggles the popup, SIGUSR2 clears. Choosing an item puts it on the clipboard
//! (wl-copy keeps serving it), focus returns to the previous window and Ctrl+V (Ctrl+Shift+V in terminals) is typed.
#[path = "../theme.rs"] mod theme;
use gtk::{gdk, gdk_pixbuf, glib, pango, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use serde_json::{json, Value};
use std::{cell::{Cell, RefCell}, io::{BufRead, BufReader, Read, Write}, path::PathBuf, process::{Command, Stdio}, rc::Rc,
          sync::{Arc, Mutex}, time::{Duration, Instant, SystemTime}};

const MAX: usize = 10; const W: i32 = 340;
const SECRET: [&str; 2] = ["x-kde-passwordManagerHint", "x-kde-passwordmanagerhint"];
const TERMS: [&str; 10] = ["foot", "footclient", "xfce4-terminal", "gnome-terminal-server", "xterm", "uxterm", "konsole", "terminator", "alacritty", "kitty"];
const TEXT: [&str; 5] = ["text/plain", "text/plain;charset=utf-8", "UTF8_STRING", "STRING", "TEXT"];

fn dir() -> PathBuf { PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".cache/osb/clipboard") }
fn idx() -> PathBuf { dir().join("history.json") }
fn pidfile() -> PathBuf { theme::rundir().join("osb-clipd.pid") }
fn now() -> f64 { SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap().as_secs_f64() }
fn enabled() -> bool { theme::sbool(&theme::settings(), "clipboard_history", true) }
fn out(argv: &[&str], timeout: u64) -> Vec<u8> {
    let Ok(mut c) = Command::new(argv[0]).args(&argv[1..]).stdout(Stdio::piped()).stderr(Stdio::null()).spawn() else { return vec![] };
    let mut so = c.stdout.take().unwrap(); let h = std::thread::spawn(move || { let mut b = vec![]; let _ = so.read_to_end(&mut b); b });
    let end = Instant::now() + Duration::from_secs(timeout);
    loop { if let Ok(Some(_)) = c.try_wait() { break; } if Instant::now() > end { let _ = c.kill(); let _ = c.wait(); break; } std::thread::sleep(Duration::from_millis(5)); }
    h.join().unwrap_or_default()
}
fn md5(d: &[u8]) -> String { glib::compute_checksum_for_data(glib::ChecksumType::Md5, d).map(|s| s.to_string()).unwrap_or_default() }

fn css(p: &std::collections::HashMap<String, String>) -> String {
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    format!(r#"
window#cwin {{ background: transparent; }}
#ccard {{ background: {s}; border-radius: 16px; border: 1px solid {sv}; padding: 10px; color: {os}; font-family: Roboto; }}
.chead {{ font-weight: 500; font-size: 13px; padding: 2px 6px 6px 6px; }}
button.clear {{ background: transparent; border: none; box-shadow: none; color: {a}; font-weight: 500; padding: 2px 8px; border-radius: 12px; min-height: 0; }}
button.clear:hover {{ background: {sv}; }}
list {{ background: transparent; }}
row {{ background: transparent; border-radius: 12px; padding: 6px 8px; color: {os}; }}
row:hover {{ background: {sv}; }}
row:selected, row:selected label {{ background: {ac}; color: {oac}; }}
.ctext {{ font-size: 13px; }}
.cnum {{ font-size: 11px; color: {osv}; min-width: 14px; }}
button.cdel {{ background: transparent; border: none; box-shadow: none; padding: 2px; border-radius: 12px; min-width: 24px; min-height: 24px; color: {osv}; }}
button.cdel:hover {{ background: {o}; }}
.cempty {{ color: {osv}; font-size: 13px; padding: 14px; }}
"#, s = g("SURFACE"), sv = g("SURFACE_VARIANT"), os = g("ON_SURFACE"), osv = g("ON_SURFACE_VARIANT"), a = g("ACCENT"),
        ac = g("ACCENT_CONTAINER"), oac = g("ON_ACCENT_CONTAINER"), o = g("OUTLINE"))
}

struct C { hist: Vec<Value>, win: Option<gtk::Window>, list: Option<gtk::ListBox>, ours: Cell<bool>, prev: Arc<Mutex<Option<String>>>,
           prov: gtk::CssProvider, palm: Option<SystemTime> }
type R = Rc<RefCell<C>>;

fn save(r: &R) {
    let h = r.borrow().hist.clone(); let _ = std::fs::create_dir_all(dir());
    let tmp = idx().with_extension("json.tmp");
    if std::fs::write(&tmp, serde_json::to_string(&h).unwrap_or_default()).is_ok() { let _ = std::fs::rename(tmp, idx()); }
    let keep: Vec<String> = h.iter().filter_map(|x| x["img"].as_str().map(String::from)).collect();
    if let Ok(rd) = std::fs::read_dir(dir()) { for e in rd.flatten() { let p = e.path();
        if p.extension().map(|x| x == "png").unwrap_or(false) && !keep.contains(&p.to_string_lossy().to_string()) { let _ = std::fs::remove_file(p); } } }
}
fn record(r: &R, item: Value) {
    { let mut c = r.borrow_mut(); let k = item["key"].clone(); c.hist.retain(|h| h["key"] != k); c.hist.insert(0, item.clone()); c.hist.truncate(MAX); }
    save(r); println!("recorded {} {}", item["kind"].as_str().unwrap_or(""), item["text"].as_str().unwrap_or("").chars().take(30).collect::<String>());
}
fn changed(r: &R) {
    if r.borrow().ours.get() || !enabled() { return; }
    let types: Vec<String> = String::from_utf8_lossy(&out(&["wl-paste", "-l"], 3)).split_whitespace().map(String::from).collect();
    if types.iter().any(|t| SECRET.contains(&t.as_str())) { println!("skipped: password-manager hint"); return; }
    if let Some(it) = ["image/png", "image/jpeg"].iter().find(|t| types.iter().any(|x| x == *t)) {
        let data = out(&["wl-paste", "-n", "-t", it], 5);
        let l = gdk_pixbuf::PixbufLoader::new(); if l.write(&data).is_err() || l.close().is_err() { return; }
        let Some(pb) = l.pixbuf() else { return };
        let px = pb.read_pixel_bytes(); let n = px.len().min(65536);
        let mut kd = px[..n].to_vec(); kd.extend_from_slice(format!("{}x{}", pb.width(), pb.height()).as_bytes());
        let key = format!("i{}", md5(&kd)); let path = dir().join(format!("{key}.png")); let _ = std::fs::create_dir_all(dir());
        if pb.savev(&path, "png", &[]).is_err() { return; }
        record(r, json!({"kind": "image", "img": path.to_string_lossy(), "w": pb.width(), "h": pb.height(), "key": key, "t": now()}));
    } else if types.iter().any(|t| TEXT.contains(&t.as_str())) {
        let t = String::from_utf8_lossy(&out(&["wl-paste", "-n", "-t", "text"], 5)).to_string();
        if t.trim().is_empty() || t.chars().count() > 100000 { return; }
        record(r, json!({"kind": "text", "text": t, "key": format!("t{}", md5(t.as_bytes())), "t": now()}));
    }
}

fn helper() -> String {
    if let Ok(h) = std::env::var("POLDER_TOPLEVELS") { return h; }
    for d in std::env::var("PATH").unwrap_or_default().split(':') { let p = std::path::Path::new(d).join("polder-toplevels"); if p.exists() { return p.to_string_lossy().into(); } }
    theme::config_dir().join("../compositor/polder-comp/tools/polder-toplevels").to_string_lossy().into()
}
/// app_id of the activated toplevel (wltop.toplevels snapshot), so the paste chord fits the target app.
fn active_app() -> Option<String> {
    let mut p = Command::new(helper()).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().ok()?;
    let so = p.stdout.take()?; let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || { for l in BufReader::new(so).lines().map_while(Result::ok) { if tx.send(l).is_err() { break; } } });
    let mut tl: std::collections::BTreeMap<i64, Value> = Default::default(); let end = Instant::now() + Duration::from_millis(400);
    while let Some(left) = end.checked_duration_since(Instant::now()) {
        let Ok(l) = rx.recv_timeout(left) else { break }; let Ok(ev) = serde_json::from_str::<Value>(&l) else { continue };
        let id = ev["id"].as_i64().unwrap_or(-1);
        match ev["ev"].as_str() { Some("state") => { tl.insert(id, ev); } Some("closed") => { tl.remove(&id); } _ => {} }
    }
    let _ = p.kill(); let _ = p.wait();
    tl.values().find(|t| t["activated"].as_bool().unwrap_or(false)).map(|t| t["app_id"].as_str().unwrap_or("").to_lowercase())
}

fn hide_c(r: &R) { let w = r.borrow_mut().win.take(); r.borrow_mut().list = None; if let Some(w) = w { w.destroy(); } }
fn toggle(r: &R) { if r.borrow().win.is_some() { hide_c(r) } else if enabled() { show_c(r) } }

fn show_c(r: &R) {
    { let m = theme::mtime(&theme::config_dir().join("palette.env")); let mut c = r.borrow_mut();
      if m != c.palm { c.palm = m; #[allow(deprecated)] c.prov.load_from_data(&css(&theme::palette())); } }
    { let prev = r.borrow().prev.clone(); *prev.lock().unwrap() = None; std::thread::spawn(move || { let a = active_app(); *prev.lock().unwrap() = a; }); }
    // a fresh layer surface per opening: polder-comp closes on-demand overlay panels when they lose focus
    let w = gtk::Window::builder().title("Klembord").decorated(false).resizable(false).build(); w.set_widget_name("cwin");
    if gtk4_layer_shell::is_supported() {
        w.init_layer_shell(); w.set_namespace("polder-clipboard"); w.set_layer(Layer::Overlay);
        w.set_anchor(Edge::Bottom, true); w.set_margin(Edge::Bottom, 70); w.set_exclusive_zone(0); w.set_keyboard_mode(KeyboardMode::OnDemand);
    }
    { let r2 = r.clone(); let w2 = w.clone(); w.connect_close_request(move |_| { if r2.borrow().win.as_ref() == Some(&w2) { r2.borrow_mut().win = None; } glib::Propagation::Proceed }); }
    { let r2 = r.clone(); let w2 = w.clone(); w.connect_is_active_notify(move |x| if !x.is_active() {
        let (r3, w3) = (r2.clone(), w2.clone()); glib::timeout_add_local_once(Duration::from_millis(120), move || {
            if r3.borrow().win.as_ref() == Some(&w3) && !w3.is_active() { hide_c(&r3); } }); }); }
    let k = gtk::EventControllerKey::new();
    { let r2 = r.clone(); k.connect_key_pressed(move |_, key, _, _| {
        if key == gdk::Key::Escape { hide_c(&r2); return glib::Propagation::Stop; }
        if let Some(c) = key.to_unicode().and_then(|c| c.to_digit(10)) { let n = r2.borrow().hist.len();
            if (1..=9).contains(&c) && (c as usize) <= n { let r3 = r2.clone(); glib::idle_add_local_once(move || choose(&r3, c as usize - 1)); return glib::Propagation::Stop; } }
        if key == gdk::Key::Delete && !r2.borrow().hist.is_empty() {
            let sel = r2.borrow().list.as_ref().and_then(|l| l.selected_row()).map(|x| x.index());
            if let Some(i) = sel.filter(|i| *i >= 0) { let r3 = r2.clone(); glib::idle_add_local_once(move || delete(&r3, i as usize)); }
            return glib::Propagation::Stop;
        }
        glib::Propagation::Proceed }); }
    w.add_controller(k);
    r.borrow_mut().win = Some(w.clone()); build(r); w.present();
}

fn build(r: &R) {
    let Some(w) = r.borrow().win.clone() else { return };
    let card = gtk::Box::new(gtk::Orientation::Vertical, 4); card.set_widget_name("ccard"); card.set_size_request(W, -1);
    let hist = r.borrow().hist.clone();
    let hd = gtk::Box::new(gtk::Orientation::Horizontal, 0);
    let l = gtk::Label::builder().label("Klembord").xalign(0.0).hexpand(true).build(); l.add_css_class("chead"); hd.append(&l);
    if !hist.is_empty() { let b = gtk::Button::with_label("Alles wissen"); b.add_css_class("clear"); let r2 = r.clone(); b.connect_clicked(move |_| clear(&r2)); hd.append(&b); }
    card.append(&hd);
    let list = gtk::ListBox::new(); { let r2 = r.clone(); list.connect_row_activated(move |_, row| { let i = row.index() as usize; let r3 = r2.clone(); glib::idle_add_local_once(move || choose(&r3, i)); }); }
    card.append(&list);
    if hist.is_empty() {
        let e = gtk::Label::new(Some("Nog niets gekopieerd.\nKopieer tekst of een afbeelding om die hier terug te vinden.")); e.set_justify(gtk::Justification::Center);
        e.add_css_class("cempty"); card.append(&e);
    }
    for (i, h) in hist.iter().enumerate() {
        let row = gtk::ListBoxRow::new(); let bx = gtk::Box::new(gtk::Orientation::Horizontal, 10);
        let n = gtk::Label::new(Some(&(i + 1).to_string())); n.add_css_class("cnum"); bx.append(&n);
        let img = h["img"].as_str().unwrap_or("");
        if h["kind"] == "image" && std::path::Path::new(img).exists() {
            if let Ok(pb) = gdk_pixbuf::Pixbuf::from_file_at_scale(img, 160, 56, true) {
                #[allow(deprecated)] let pic = gtk::Picture::for_pixbuf(&pb); pic.set_size_request(pb.width(), pb.height());
                let fx = gtk::Fixed::new(); fx.put(&pic, 0.0, 0.0); fx.set_size_request(pb.width(), pb.height()); bx.append(&fx);
            }
            let s = gtk::Label::builder().label(format!("Afbeelding {}×{}", h["w"], h["h"])).xalign(0.0).hexpand(true).build(); s.add_css_class("cnum"); bx.append(&s);
        } else {
            let t = h["text"].as_str().unwrap_or("").split_whitespace().collect::<Vec<_>>().join(" ");
            let l = gtk::Label::builder().label(t).xalign(0.0).ellipsize(pango::EllipsizeMode::End).max_width_chars(34).hexpand(true).build(); l.add_css_class("ctext"); bx.append(&l);
        }
        let d = gtk::Button::from_icon_name("window-close-symbolic"); d.add_css_class("cdel"); d.set_tooltip_text(Some("Verwijderen"));
        { let r2 = r.clone(); d.connect_clicked(move |_| { let r3 = r2.clone(); glib::idle_add_local_once(move || delete(&r3, i)); }); }
        bx.append(&d); row.set_child(Some(&bx)); list.append(&row);
    }
    w.set_child(Some(&card)); r.borrow_mut().list = Some(list.clone());
    // select + focus the first row: arrow keys then move the selection (Delete removes the selected item)
    if let Some(row) = list.row_at_index(0) { list.select_row(Some(&row)); glib::idle_add_local_once(move || { row.grab_focus(); }); }
    // shrink the mapped layer surface to the new content (gtk4-layer-shell keeps the old size otherwise)
    w.set_default_size(W, 1);
}
fn delete(r: &R, i: usize) { { let mut c = r.borrow_mut(); if i < c.hist.len() { c.hist.remove(i); } } save(r); build(r); }
fn clear(r: &R) { r.borrow_mut().hist.clear(); save(r); if r.borrow().win.is_some() { build(r); } }

fn choose(r: &R, i: usize) {
    let Some(h) = r.borrow().hist.get(i).cloned() else { return };
    r.borrow().ours.set(true);
    // wl-copy forks into the background and keeps serving the selection after we hide
    let res = if h["kind"] == "image" { std::fs::File::open(h["img"].as_str().unwrap_or("")).ok().and_then(|f| Command::new("wl-copy").args(["-t", "image/png"]).stdin(f).status().ok()) }
        else { Command::new("wl-copy").stdin(Stdio::piped()).spawn().ok().and_then(|mut c| { if let Some(mut si) = c.stdin.take() { let _ = si.write_all(h["text"].as_str().unwrap_or("").as_bytes()); } c.wait().ok() }) };
    if res.is_none() { eprintln!("wl-copy failed"); }
    { let mut c = r.borrow_mut(); let it = c.hist.remove(i); c.hist.insert(0, it); }
    save(r);
    { let r2 = r.clone(); glib::timeout_add_local_once(Duration::from_millis(600), move || r2.borrow().ours.set(false)); }
    hide_c(r);
    let prev = r.borrow().prev.clone();
    glib::timeout_add_local_once(Duration::from_millis(200), move || {
        let Some(p) = prev.lock().unwrap().clone().filter(|p| !p.is_empty()) else { return };
        let term = TERMS.contains(&p.as_str());   // focus went back to that window when our panel unmapped; type the chord (virtual keyboard)
        let mut a = vec!["-M", "ctrl"]; if term { a.extend(["-M", "shift"]); } a.extend(["-k", "v"]); if term { a.extend(["-m", "shift"]); } a.extend(["-m", "ctrl"]);
        let _ = Command::new("wtype").args(&a).status();
        println!("pasted {} into {p}", if term { "ctrl+shift+v" } else { "ctrl+v" });
    });
}

fn main() {
    if let Ok(p) = std::fs::read_to_string(pidfile()) { if let Ok(p) = p.trim().parse::<i32>() { if p > 0 && unsafe { libc::kill(p, 0) } == 0 { println!("already running"); return; } } }
    let _ = std::fs::write(pidfile(), std::process::id().to_string());
    gtk::init().expect("gtk"); let _ = std::fs::create_dir_all(dir());
    let hist: Vec<Value> = std::fs::read_to_string(idx()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let prov = gtk::CssProvider::new(); gtk::style_context_add_provider_for_display(&gdk::Display::default().unwrap(), &prov, 800);
    let r: R = Rc::new(RefCell::new(C { hist, win: None, list: None, ours: Cell::new(false), prev: Arc::new(Mutex::new(None)), prov, palm: None }));
    // GTK only sees clipboard changes while focused on Wayland -> wlr-data-control via wl-paste --watch
    match Command::new("wl-paste").args(["--watch", "echo", "changed"]).stdout(Stdio::piped()).spawn() {
        Ok(mut ch) => {
            use std::os::fd::AsRawFd; let mut so = ch.stdout.take().unwrap(); let fd = so.as_raw_fd(); let r2 = r.clone(); std::mem::forget(ch);
            glib::source::unix_fd_add_local(fd, glib::IOCondition::IN | glib::IOCondition::HUP, move |_, _| {
                let mut b = [0u8; 4096]; let n = so.read(&mut b).unwrap_or(0); if n == 0 { return glib::ControlFlow::Break; }
                changed(&r2); glib::ControlFlow::Continue });
        }
        Err(e) => eprintln!("wl-paste --watch: {e}"),
    }
    let ml = glib::MainLoop::new(None, false);
    { let r = r.clone(); glib::unix_signal_add_local(libc::SIGUSR1, move || { let r = r.clone(); glib::idle_add_local_once(move || toggle(&r)); glib::ControlFlow::Continue }); }
    { let r = r.clone(); glib::unix_signal_add_local(libc::SIGUSR2, move || { clear(&r); glib::ControlFlow::Continue }); }
    { let ml = ml.clone(); glib::unix_signal_add_local(libc::SIGTERM, move || { let _ = std::fs::remove_file(pidfile()); ml.quit(); glib::ControlFlow::Break }); }
    ml.run();
}
