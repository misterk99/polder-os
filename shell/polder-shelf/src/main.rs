//! Polder OS shelf in Rust (GTK4 + wlr-layer-shell): the Wayland bar of polder-comp. Feature port of config/shelf/shelf.py
//! (its Wayland path): launcher button, pinned + running apps (foreign-toplevel), running dot / active highlight,
//! right-click menus, recording + media pills, keyboard / weather / date / quick-settings pills, live theme, and the
//! wallpaper desktop surface with its right-click menu. The Python shelf stays as fallback.
mod apps; mod menu; mod status; mod theme; mod toplevels;
use gtk::{gdk, gio, glib, prelude::*};
use gtk4_layer_shell::{Edge, Layer, LayerShell};
use menu::Item;
use std::{cell::RefCell, path::PathBuf, process::{Command, Stdio}, rc::Rc, sync::{Arc, Mutex}, time::SystemTime};

const H: i32 = 52;
const SKIPCLS: [&str; 12] = ["tint2", "polder-shell.py", "qs.py", "osb-notifyd.py", "launcher.py", "shelf.py", "cal.py", "overview.py",
                             "clipd.py", "xfdesktop", "lock.py", "polder-shelf"];
const MONTHS: [&str; 12] = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

fn run(argv: &[&str]) {
    let mut c = Command::new(argv[0]); c.args(&argv[1..]).stdout(Stdio::null()).stderr(Stdio::null());
    use std::os::unix::process::CommandExt; c.process_group(0);
    if let Err(e) = c.spawn() { eprintln!("run {argv:?}: {e}"); }
}
fn cpath(rel: &str) -> String { theme::config_dir().join(rel).to_string_lossy().into() }

struct Shelf {
    win: gtk::Window, apps_box: gtk::Box, rec: gtk::Button, reclabel: gtk::Label, media: gtk::Button, medialabel: gtk::Label,
    kb: gtk::Button, wx: gtk::Button, date: gtk::Button, tray: gtk::Button,
    prov: gtk::CssProvider, palm: Option<SystemTime>, setm: Option<SystemTime>,
    db: apps::AppDb, tasks: Option<Rc<RefCell<toplevels::Tasks>>>, pinned: Vec<String>,
    wins: Vec<(i64, String, bool)>, active_app: Option<String>, sig: Option<(Vec<String>, Vec<String>, Option<String>)>,
    menu: Option<menu::PopMenu>, screen: (i32, i32),
    probe: Arc<Mutex<status::Probe>>, wxtext: Arc<Mutex<Option<String>>>, slow: i32, mpoll: i32, mstate: Option<status::Media>,
    key: String, desk: Desk,
}
type S = Rc<RefCell<Shelf>>;

struct Desk { win: gtk::Window, prov: gtk::CssProvider, wpm: Option<SystemTime> }
impl Desk {
    fn refresh(&mut self) {
        let mut wp = theme::config_dir().join("wallpaper.png");
        if !wp.exists() { wp = theme::config_dir().join("wallpapers/polderheuvel.png"); }
        let m = theme::mtime(&wp);
        if m.is_none() || m == self.wpm { return; }
        self.wpm = m;
        let secs = m.and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0);
        let dir = theme::rundir();
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() { let n = e.file_name().to_string_lossy().to_string(); if n.starts_with("polder-shelf-desk-") { let _ = std::fs::remove_file(e.path()); } }
        }
        let out: PathBuf = dir.join(format!("polder-shelf-desk-{secs}.png"));   // new path per change: GTK caches images by URL
        if std::fs::copy(&wp, &out).is_ok() {
            #[allow(deprecated)]
            self.prov.load_from_data(&format!("window#desk {{ background-image: url('file://{}'); background-size: cover; background-position: center; background-color: #000; }}", out.display()));
            self.win.queue_draw();
        }
    }
}

fn screen_size() -> (i32, i32) {
    gdk::Display::default().and_then(|d| d.monitors().item(0)).and_then(|m| m.downcast::<gdk::Monitor>().ok())
        .map(|m| { let g = m.geometry(); (g.width(), g.height()) }).unwrap_or((1280, 800))
}

fn pill(tip: &str) -> gtk::Button {
    let b = gtk::Button::new(); b.add_css_class("pill"); b.set_child(Some(&gtk::Box::new(gtk::Orientation::Horizontal, 8))); b.set_tooltip_text(Some(tip)); b
}
fn fill(btn: &gtk::Button, parts: Vec<gtk::Widget>) {
    let bx = btn.child().and_downcast::<gtk::Box>().unwrap();
    while let Some(c) = bx.first_child() { bx.remove(&c); }
    for p in parts { bx.append(&p); }
}
fn icon(name: &str) -> gtk::Widget { let im = gtk::Image::from_icon_name(&format!("{name}-symbolic")); im.set_pixel_size(18); im.upcast() }
fn label(t: &str) -> gtk::Widget { gtk::Label::new(Some(t)).upcast() }
fn kb_layout() -> String { std::env::var("XKB_DEFAULT_LAYOUT").unwrap_or_else(|_| "us".into()).split(',').next().unwrap_or("us").to_string() }
/// --right=<px from the screen's right edge to the pill's right edge> so the panel opens right above the pill.
fn right_of(s: &Shelf, b: &gtk::Button) -> String {
    let x = b.translate_coordinates(&s.win, 0.0, 0.0).map(|p| p.0).unwrap_or(0.0) as i32 + b.width();
    format!("--right={}", s.screen.0 - x)
}

fn build(app: &gtk::Application) -> S {
    let screen = screen_size();
    let win = gtk::ApplicationWindow::new(app).upcast::<gtk::Window>();
    win.set_title(Some("Polder Plank")); win.set_widget_name("shelf"); win.set_decorated(false);
    win.init_layer_shell(); win.set_namespace("polder-shelf"); win.set_layer(Layer::Top);
    for e in [Edge::Left, Edge::Right, Edge::Bottom] { win.set_anchor(e, true); }
    win.set_exclusive_zone(H);
    let prov = gtk::CssProvider::new();
    gtk::style_context_add_provider_for_display(&gdk::Display::default().unwrap(), &prov, 800);

    let bar = gtk::CenterBox::new(); bar.set_size_request(-1, H); win.set_child(Some(&bar));
    let launcher = gtk::Button::new(); launcher.add_css_class("lbtn"); launcher.set_valign(gtk::Align::Center); launcher.set_margin_start(6);
    let lic = theme::config_dir().join("launcher-icon.png");
    let lim = if lic.exists() { let p = gtk::Image::from_file(&lic); p.set_pixel_size(32); p } else { let p = gtk::Image::from_icon_name("view-app-grid-symbolic"); p.set_pixel_size(24); p };
    launcher.set_child(Some(&lim)); launcher.set_tooltip_text(Some("Launcher"));
    launcher.connect_clicked(|_| run(&[&cpath("launcher/launcher-toggle.sh")]));
    bar.set_start_widget(Some(&launcher));

    let outer = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let apps_box = gtk::Box::new(gtk::Orientation::Horizontal, 4);
    for m in [&apps_box] { m.set_margin_top(4); m.set_margin_bottom(4); m.set_margin_start(4); m.set_margin_end(4); }
    outer.append(&apps_box);
    let extra = gtk::Box::new(gtk::Orientation::Horizontal, 6); extra.set_valign(gtk::Align::Center); outer.append(&extra);
    let rec = gtk::Button::new(); rec.add_css_class("recpill"); let rb = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    rb.append(&gtk::Image::from_icon_name("media-playback-stop-symbolic")); let reclabel = gtk::Label::new(Some("0:00")); rb.append(&reclabel);
    rec.set_child(Some(&rb)); rec.set_tooltip_text(Some("Schermopname stoppen")); rec.set_visible(false);
    rec.connect_clicked(|_| status::stop_recording());
    let media = gtk::Button::new(); media.add_css_class("mediapill"); let mb = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    mb.append(&gtk::Image::from_icon_name("media-playback-pause-symbolic"));
    let medialabel = gtk::Label::new(None); medialabel.set_max_width_chars(18); medialabel.set_ellipsize(gtk::pango::EllipsizeMode::End); mb.append(&medialabel);
    media.set_child(Some(&mb)); media.set_visible(false);
    extra.append(&rec); extra.append(&media);
    bar.set_center_widget(Some(&outer));

    let right = gtk::Box::new(gtk::Orientation::Horizontal, 6); right.set_valign(gtk::Align::Center); right.set_margin_end(8);
    let (kb, wx, date, tray) = (pill("Toetsenbordindeling"), pill("Weer"), pill("Agenda"), pill("Snelle instellingen"));
    for p in [&kb, &wx, &date, &tray] { right.append(p); }
    wx.set_visible(false);
    bar.set_end_widget(Some(&right));

    // desktop surface: wallpaper on the background layer, so right-clicks on the empty desktop reach us
    let dwin = gtk::Window::builder().title("Polder Bureaublad").decorated(false).build(); dwin.set_widget_name("desk");
    dwin.set_application(Some(app));
    dwin.init_layer_shell(); dwin.set_namespace("polder-desktop"); dwin.set_layer(Layer::Background);
    for e in [Edge::Left, Edge::Right, Edge::Top, Edge::Bottom] { dwin.set_anchor(e, true); }
    dwin.set_exclusive_zone(-1);
    let dprov = gtk::CssProvider::new();
    #[allow(deprecated)] dwin.style_context().add_provider(&dprov, 900);

    let s: S = Rc::new(RefCell::new(Shelf {
        win: win.clone(), apps_box, rec, reclabel, media: media.clone(), medialabel, kb: kb.clone(), wx: wx.clone(), date: date.clone(), tray: tray.clone(),
        prov, palm: None, setm: None, db: apps::AppDb::new(), tasks: None, pinned: vec![], wins: vec![], active_app: None, sig: None,
        menu: None, screen, probe: Arc::new(Mutex::new(status::Probe::default())), wxtext: Arc::new(Mutex::new(None)), slow: 0, mpoll: 0,
        mstate: None, key: String::new(), desk: Desk { win: dwin.clone(), prov: dprov, wpm: None },
    }));

    let w = Rc::downgrade(&s);
    media.connect_clicked(move |_| if let Some(s) = w.upgrade() {
        let n = s.borrow().mstate.as_ref().map(|m| m.name.clone()); if let Some(n) = n { status::media_toggle(&n); s.borrow_mut().mpoll = 0; }
    });
    let w = Rc::downgrade(&s);
    kb.connect_clicked(move |b| if let Some(s) = w.upgrade() {
        let x = b.translate_coordinates(&s.borrow().win, 0.0, 0.0).map(|p| p.0).unwrap_or(0.0) as i32;
        let v = std::env::var("XKB_DEFAULT_VARIANT").unwrap_or_default();
        let items = vec![Item::Entry("input-keyboard-symbolic", format!("Indeling: {}{}", kb_layout(), if v.is_empty() { String::new() } else { format!(" ({v})") }), Some(Box::new(|| {}))),
                         Item::Entry("input-keyboard-symbolic", "Sneltoetsen".into(), Some(Box::new(|| run(&["python3", &cpath("shortcuts/sneltoetsen.py")]))))];
        open_menu(&s, items, x, None, Some("Toetsenbord"));
    });
    let w = Rc::downgrade(&s);
    wx.connect_clicked(move |b| if let Some(s) = w.upgrade() { let r = right_of(&s.borrow(), b); run(&["python3", &cpath("calendar/cal.py"), "--weather", &r]); });
    let w = Rc::downgrade(&s);
    date.connect_clicked(move |b| if let Some(s) = w.upgrade() { let r = right_of(&s.borrow(), b); run(&["python3", &cpath("calendar/cal.py"), &r]); });
    tray.connect_clicked(|_| run(&["python3", &cpath("quicksettings/qs.py")]));

    let g = gtk::GestureClick::new(); g.set_button(3);
    let w = Rc::downgrade(&s);
    g.connect_pressed(move |_, _, x, y| if let Some(s) = w.upgrade() {
        let settings = cpath("settings/instellingen.py");
        let (s1, s2) = (settings.clone(), settings);
        let items = vec![Item::Entry("preferences-desktop-wallpaper-symbolic", "Achtergrond en stijl".into(), Some(Box::new(move || run(&["python3", &s1, "personalisatie"])))),
                         Item::Entry("system-file-manager-symbolic", "Bestanden openen".into(), Some(Box::new(|| run(&[&cpath("files/run-files.sh")])))),
                         Item::Sep,
                         Item::Entry("emblem-system-symbolic", "Instellingen".into(), Some(Box::new(move || run(&["python3", &s2])))),
                         Item::Entry("input-keyboard-symbolic", "Sneltoetsen".into(), Some(Box::new(|| run(&["python3", &cpath("shortcuts/sneltoetsen.py")]))))];
        open_menu(&s, items, x as i32, Some(y as i32), None);
    });
    dwin.add_controller(g);

    let w = Rc::downgrade(&s);
    let tasks = toplevels::start(move || { let w = w.clone(); glib::idle_add_local_once(move || if let Some(s) = w.upgrade() { render(&s, false); }); });
    s.borrow_mut().tasks = Some(tasks);
    let w = Rc::downgrade(&s);
    let mon = gio::AppInfoMonitor::get();
    mon.connect_changed(move |_| if let Some(s) = w.upgrade() { s.borrow_mut().db.reload(); render(&s, true); });
    std::mem::forget(mon);   // keep the monitor alive for the process lifetime

    s.borrow_mut().desk.refresh();
    dwin.present();
    render(&s, true);
    update_status(&s);
    win.present();
    let w = Rc::downgrade(&s);
    glib::timeout_add_local(std::time::Duration::from_millis(700), move || match w.upgrade() { Some(s) => { tick(&s); glib::ControlFlow::Continue } None => glib::ControlFlow::Break });
    s
}

/// y None: shelf menu growing upwards from just above the bar; Some(y): desktop menu below the click point.
fn open_menu(s: &S, items: Vec<Item>, x: i32, y: Option<i32>, title: Option<&str>) {
    let old = s.borrow_mut().menu.take(); if let Some(m) = old { m.close(); }
    let sc = s.borrow().screen;
    let m = match y { None => menu::show(items, x, sc.1 - H - 6, true, title, sc), Some(y) => menu::show(items, x, y, false, title, sc) };
    s.borrow_mut().menu = Some(m);
}

fn tick(s: &S) {
    update_status(s);
    s.borrow_mut().desk.refresh();
    if update_extra(s) { render(s, true); }
    render(s, false);
}

fn update_status(s: &S) {
    let mut me = s.borrow_mut();
    me.slow -= 1;
    if me.slow <= 0 {
        me.slow = 14;
        let (p, wx) = (me.probe.clone(), me.wxtext.clone());
        std::thread::spawn(move || { let r = status::slow_probe(); *p.lock().unwrap() = r; *wx.lock().unwrap() = Some(status::weather_pill()); });
    }
    let sets = theme::settings();
    let (unread, dnd) = status::notify_state();
    let now = glib::DateTime::now_local().unwrap();
    let clock = if theme::sbool(&sets, "clock24", true) { format!("{:02}:{:02}", now.hour(), now.minute()) }
                else { format!("{}:{:02}", match now.hour() % 12 { 0 => 12, h => h }, now.minute()) };
    let show_date = theme::sbool(&sets, "show_date", true);
    let st = me.probe.lock().unwrap().clone();
    let wxt = me.wxtext.lock().unwrap().clone();
    let key = format!("{clock}|{show_date}|{unread}|{dnd}|{st:?}|{wxt:?}|{}|{}", theme::palette()["THEME"], now.day_of_month());
    if key == me.key { return; }
    me.key = key;
    fill(&me.kb, vec![label(&kb_layout().to_uppercase())]);
    me.date.set_visible(show_date);
    fill(&me.date, vec![label(&format!("{} {}", now.day_of_month(), MONTHS[(now.month() - 1) as usize]))]);
    let mut parts = vec![label(&clock)];
    if dnd { parts.push(icon("notifications-disabled")); }
    else if unread > 0 { let b = gtk::Label::new(Some(&unread.to_string())); b.add_css_class("badge"); parts.push(b.upcast()); }
    if st.upd { parts.push(icon("go-up")); }
    for i in [&st.wifi, &st.vol, &st.bat].into_iter().flatten() { parts.push(icon(i)); }
    fill(&me.tray, parts);
    match wxt.as_deref().and_then(|r| r.split_once(' ')) {
        Some((ic, t)) => { fill(&me.wx, vec![icon(ic), label(t)]); me.wx.set_visible(true); }
        None => me.wx.set_visible(false),
    }
}

fn update_extra(s: &S) -> bool {
    let mut me = s.borrow_mut(); let mut changed = false;
    let st = status::recording_start();
    if let Some(start) = st {
        let el = (SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap().as_secs_f64() - start).max(0.0) as i64;
        me.reclabel.set_text(&format!("{}:{:02}", el / 60, el % 60));
    }
    if st.is_some() != me.rec.is_visible() { me.rec.set_visible(st.is_some()); changed = true; }
    me.mpoll -= 1;
    if me.mpoll <= 0 {
        me.mpoll = 3; let m = status::media_active();
        let show = m.as_ref().map(|m| m.status == "Playing").unwrap_or(false);
        if let (true, Some(m)) = (show, m.as_ref()) {
            me.medialabel.set_text(&format!("{}{}", m.title, if m.artist.is_empty() { String::new() } else { format!(" · {}", m.artist) }));
        }
        me.mstate = m;
        if show != me.media.is_visible() { me.media.set_visible(show); changed = true; }
    }
    changed
}

fn render(s: &S, mut force: bool) {
    let mut me = s.borrow_mut();
    let pal = theme::config_dir().join("palette.env");
    let pm = theme::mtime(&pal);
    if pm != me.palm || force && me.palm.is_none() {   // live theme: osb/apply.py rewrites palette.env
        me.palm = pm;
        #[allow(deprecated)] me.prov.load_from_data(&theme::shelf_css(&theme::palette()));
    }
    let sm = theme::mtime(&theme::settings_file());
    if sm != me.setm || me.pinned.is_empty() && me.setm.is_none() {
        me.setm = sm; let p = theme::pinned(&theme::settings());
        me.pinned = p.into_iter().filter(|p| me.db.apps.contains_key(p)).collect(); force = true;
    }
    let (tl, act) = match &me.tasks { Some(t) => { let t = t.borrow(); (t.tl.clone(), t.active()) } None => Default::default() };
    me.wins = tl.iter().filter_map(|(i, t)| {
        let aid = if t.app_id.is_empty() { t.title.clone() } else { t.app_id.clone() };
        if aid.is_empty() || SKIPCLS.contains(&aid.to_lowercase().as_str()) { return None; }
        Some((*i, me.db.resolve(&aid), t.minimized))
    }).collect();
    me.active_app = me.wins.iter().find(|w| w.0 == act).map(|w| w.1.clone());
    let mut running: Vec<String> = vec![];
    for w in &me.wins { if !running.contains(&w.1) { running.push(w.1.clone()); } }
    let mut order = me.pinned.clone(); for a in &running { if !order.contains(a) { order.push(a.clone()); } }
    let sig = (order.clone(), running.clone(), me.active_app.clone());
    if !force && me.sig.as_ref() == Some(&sig) { return; }
    me.sig = Some(sig);
    while let Some(c) = me.apps_box.first_child() { me.apps_box.remove(&c); }
    let mut btns = vec![];
    for a in &order { btns.push(button(&me, s, a, running.contains(a))); }
    for b in btns { me.apps_box.append(&b); }
}

fn button(me: &Shelf, s: &S, app: &str, running: bool) -> gtk::Box {
    let b = gtk::Box::new(gtk::Orientation::Vertical, 2); b.add_css_class("sapp");
    if me.active_app.as_deref() == Some(app) { b.add_css_class("active"); }
    let ai = me.db.apps.get(app);
    let gi: gio::Icon = ai.and_then(|a| a.icon()).unwrap_or_else(|| gio::ThemedIcon::from_names(&[&app.trim_start_matches("cls:").to_lowercase(), "application-x-executable"]).upcast());
    let im = gtk::Image::from_gicon(&gi); im.set_pixel_size(34); b.append(&im);
    let d = gtk::Box::new(gtk::Orientation::Horizontal, 0); d.set_halign(gtk::Align::Center); d.add_css_class(if running { "dot" } else { "nodot" }); b.append(&d);
    b.set_tooltip_text(Some(&ai.map(|a| a.display_name().to_string()).unwrap_or_else(|| app.trim_start_matches("cls:").to_string())));
    let g = gtk::GestureClick::new(); g.set_button(0);
    let (w, app) = (Rc::downgrade(s), app.to_string());
    g.connect_pressed(move |g, n, _, _| {
        let Some(s) = w.upgrade() else { return };
        let btn = g.current_button(); let wdg = g.widget().unwrap();
        g.set_state(gtk::EventSequenceState::Claimed);
        match btn {
            3 => context(&s, &wdg, &app),
            2 => launch(&s, &app),
            1 if n == 1 => {
                let (ws, active, tasks) = { let me = s.borrow(); (app_windows(&me, &app), me.active_app.clone(), me.tasks.clone()) };
                match (ws.first(), tasks) {
                    (None, _) | (_, None) => launch(&s, &app),
                    (Some(id), Some(t)) => t.borrow_mut().send(if active.as_deref() == Some(app.as_str()) { "minimize" } else { "activate" }, *id),
                }
                let w = Rc::downgrade(&s);
                glib::timeout_add_local_once(std::time::Duration::from_millis(250), move || if let Some(s) = w.upgrade() { tick(&s) });
            }
            _ => {}
        }
    });
    b.add_controller(g);
    b
}

fn app_windows(me: &Shelf, app: &str) -> Vec<i64> { me.wins.iter().filter(|w| w.1 == app).map(|w| w.0).collect() }
fn launch(s: &S, app: &str) {
    let ai = s.borrow().db.apps.get(app).cloned();
    if let Some(ai) = ai { if let Err(e) = ai.launch(&[], gio::AppLaunchContext::NONE) { eprintln!("launch {e}"); } }
}
fn set_pin(app: &str, on: bool) {
    let mut p: Vec<String> = theme::pinned(&theme::settings()).into_iter().filter(|x| x != app).collect();
    if on { p.push(app.into()); }
    theme::set_pinned(p);
}

fn context(s: &S, wdg: &gtk::Widget, app: &str) {
    let (title, has_ai, pinned, ws, tasks, x) = {
        let me = s.borrow(); let ai = me.db.apps.get(app);
        (ai.map(|a| a.display_name().to_string()).unwrap_or_else(|| app.trim_start_matches("cls:").to_string()), ai.is_some(),
         me.pinned.iter().any(|p| p == app), app_windows(&me, app), me.tasks.clone(),
         wdg.translate_coordinates(&me.win, 0.0, 0.0).map(|p| p.0).unwrap_or(0.0) as i32)
    };
    let mut items = vec![];
    if has_ai {
        let a = app.to_string();
        items.push(Item::Entry("view-pin-symbolic", if pinned { "Losmaken" } else { "Vastzetten" }.into(), Some(Box::new(move || set_pin(&a, !pinned)))));
        let (a, w) = (app.to_string(), Rc::downgrade(s));
        items.push(Item::Entry("window-new-symbolic", "Nieuw venster".into(), Some(Box::new(move || if let Some(s) = w.upgrade() { launch(&s, &a) }))));
    }
    if !ws.is_empty() {
        items.push(Item::Sep);
        let lbl = if ws.len() == 1 { "Sluiten".to_string() } else { format!("Sluiten ({} vensters)", ws.len()) };
        items.push(Item::Entry("window-close-symbolic", lbl, Some(Box::new(move || if let Some(t) = &tasks { for id in &ws { t.borrow_mut().send("close", *id); } }))));
    }
    open_menu(s, items, x, None, Some(&title));
}

fn main() -> glib::ExitCode {
    let pid = theme::rundir().join("osb-shelf.pid");   // same single-instance file as shelf.py: only one shelf runs
    if let Some(p) = std::fs::read_to_string(&pid).ok().and_then(|s| s.trim().parse::<i32>().ok()) {
        if p != std::process::id() as i32 && unsafe { libc::kill(p, 0) } == 0 { println!("already running"); return glib::ExitCode::SUCCESS; }
    }
    let _ = std::fs::write(&pid, std::process::id().to_string());
    if gtk::init().is_err() || !gtk4_layer_shell::is_supported() { eprintln!("polder-shelf needs a Wayland compositor with wlr-layer-shell"); return glib::ExitCode::FAILURE; }
    let app = gtk::Application::new(Some("nl.polderos.Shelf"), gio::ApplicationFlags::NON_UNIQUE);
    let keep: Rc<RefCell<Option<S>>> = Rc::new(RefCell::new(None));
    let k = keep.clone();
    app.connect_activate(move |a| { if k.borrow().is_none() { *k.borrow_mut() = Some(build(a)); } });
    app.run_with_args::<&str>(&[])
}
