#![allow(dead_code)]
//! Polder OS launcher in Rust (GTK4 + wlr-layer-shell): feature port of config/launcher/launcher.py.
//! Resident: SIGUSR1 toggles (launcher-toggle.sh), same PID file as launcher.py so only one of the two runs.
//! Empty query = app grid (drag & drop order, right-click pin menu); typing = grouped results: Webapp, Rekenmachine,
//! Apps, Instellingen, Bestanden, Internet. No fake results: .desktop files, Settings sections, the real file tree, real maths.
#[path = "../theme.rs"] mod theme;
#[path = "../menu.rs"] mod menu;
#[path = "../calc.rs"] mod calc;
use gtk::{gdk, gio, glib, pango, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use menu::Item;
use std::{cell::RefCell, path::{Path, PathBuf}, process::{Command, Stdio}, rc::Rc, sync::{Arc, Mutex}, time::{Duration, Instant, SystemTime}};

const W: i32 = 640; const H: i32 = 500; const MARGIN: i32 = 10; const SHELF: i32 = 62;
const SECTIONS: [(&str, &str, &str, &str); 16] = [
    ("Welkom bij Polder OS", "Rondleiding en eerste instellingen", "__welkom", "welkom welcome rondleiding tour eerste start introductie"),
    ("Sneltoetsen bekijken", "Toetsenbord · Ctrl+Alt+/", "__sneltoetsen", "sneltoetsen sneltoets shortcuts toetscombinaties toetsen keyboard"),
    ("Thema: licht, donker of automatisch", "Personalisatie", "personalisatie", "thema donker licht dark light modus automatisch nacht"),
    ("Achtergrond", "Personalisatie", "personalisatie", "achtergrond wallpaper bureaublad polderheuvel"),
    ("Accentkleur", "Personalisatie", "personalisatie", "accent kleur kleuren"),
    ("Meldingen", "Meldingen", "meldingen", "meldingen notificaties pop-ups popup"),
    ("Niet storen", "Meldingen", "meldingen", "niet storen dnd stil"),
    ("Agenda-abonnementen (iCal)", "Agenda", "agenda", "agenda kalender ical ics webcal feestdagen"),
    ("Toetsenbordindeling", "Toetsenbord en taal", "toetsenbord", "toetsenbord keyboard indeling layout taal qwerty"),
    ("Datum en tijd", "Datum en tijd", "datum", "datum tijd klok 24-uurs uur"),
    ("Weer-locatie", "Weer", "weer", "weer weather locatie stad plaats"),
    ("Webapps installeren", "Webapps", "webapps", "webapp webapps pwa site app installeren"),
    ("Telefoon koppelen", "Telefoon", "telefoon", "telefoon phone kde connect koppelen android iphone"),
    ("Polder Assistent en AI-sleutel", "Assistent", "assistent", "assistent assistant ai openai gemini claude sleutel key"),
    ("Polder Sync", "Sync", "sync", "sync synchroniseren back-up backup herstel github nextcloud dropbox andere pc"),
    ("Over Polder OS", "Versie, geheugen, systeem", "over", "over versie polder os systeem geheugen info"),
];

fn run(argv: &[&str]) {
    let mut c = Command::new(argv[0]); c.args(&argv[1..]).stdout(Stdio::null()).stderr(Stdio::null());
    use std::os::unix::process::CommandExt; c.process_group(0);
    match c.spawn() { Ok(mut ch) => { std::thread::spawn(move || ch.wait()); } Err(e) => eprintln!("run {argv:?}: {e}") }
}
fn cpath(rel: &str) -> String { theme::config_dir().join(rel).to_string_lossy().into() }
fn pidfile() -> PathBuf { theme::rundir().join("osb-launcher.pid") }
fn files_home() -> PathBuf { PathBuf::from(std::env::var("OSB_FILES_HOME").unwrap_or_else(|_| "/tmp/osb-files/Mijn bestanden".into())) }

/// Fuzzy score (launcher.py score): name prefix > word prefix > substring > subsequence; secondary fields x0.6.
pub fn score(q: &str, fields: &[&str]) -> f64 {
    let mut best = 0.0f64;
    for (i, f) in fields.iter().enumerate() {
        let f = f.to_lowercase(); if f.is_empty() { continue; }
        let w = if i == 0 { 1.0 } else { 0.6 };
        let s = if f.starts_with(q) { 100.0 } else if f.replace('-', " ").split_whitespace().any(|t| t.starts_with(q)) { 85.0 }
            else if f.contains(q) { 65.0 }
            else { let mut it = f.chars(); if q.chars().count() >= 3 && q.chars().all(|c| it.any(|x| x == c)) { 30.0 } else { 0.0 } };
        best = best.max(s * w);
    }
    best
}

#[derive(Clone)] struct FEntry { name: String, path: PathBuf, dir: bool, mtime: i64 }
/// In-memory index of the Files home (max 20000 entries, hidden skipped), refreshed in a thread every 5 min.
#[derive(Default)] struct FileIndex { items: Vec<FEntry>, t: Option<Instant>, busy: bool }
fn refresh(ix: &Arc<Mutex<FileIndex>>) {
    { let mut g = ix.lock().unwrap(); if g.busy { return; } g.busy = true; }
    let ix = ix.clone();
    std::thread::spawn(move || {
        let (mut out, t0) = (vec![], Instant::now()); let mut stack = vec![files_home()];
        'w: while let Some(d) = stack.pop() {
            let Ok(rd) = std::fs::read_dir(&d) else { continue };
            for e in rd.flatten() {
                let name = e.file_name().to_string_lossy().to_string(); if name.starts_with('.') { continue; }
                let p = e.path(); let Ok(md) = std::fs::metadata(&p) else { continue };
                let mt = md.modified().ok().and_then(|m| m.duration_since(SystemTime::UNIX_EPOCH).ok()).map(|d| d.as_secs() as i64).unwrap_or(0);
                if md.is_dir() { stack.push(p.clone()); }
                out.push(FEntry { name, path: p, dir: md.is_dir(), mtime: mt });
                if out.len() > 20000 || t0.elapsed() > Duration::from_secs(5) { break 'w; }
            }
        }
        let mut g = ix.lock().unwrap(); g.items = out; g.t = Some(Instant::now()); g.busy = false;
    });
}
fn search_files(ix: &Arc<Mutex<FileIndex>>, q: &str, n: usize) -> Vec<FEntry> {
    let stale = ix.lock().unwrap().t.map(|t| t.elapsed() > Duration::from_secs(300)).unwrap_or(true);
    if stale { refresh(ix); }
    let items = ix.lock().unwrap().items.clone();
    let mut hits: Vec<(f64, FEntry)> = items.into_iter().map(|e| (score(q, &[&e.name]), e)).filter(|h| h.0 >= 60.0).collect();
    hits.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(b.1.mtime.cmp(&a.1.mtime)));
    hits.into_iter().take(n).map(|h| h.1).collect()
}

fn css(p: &std::collections::HashMap<String, String>) -> String {
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    format!(r#"
window#lwin {{ background: transparent; }}
#lbox {{ background: {s}; border-radius: 24px; padding: 16px; color: {os}; font-family: Roboto; }}
entry#search {{ background: {sv}; border: none; box-shadow: none; outline: none; border-radius: 22px; padding: 8px 16px; min-height: 28px; color: {os}; font-size: 15px; caret-color: {a}; }}
entry#search image {{ color: {osv}; }}
button.app {{ background: transparent; border: none; box-shadow: none; border-radius: 16px; padding: 8px 4px; color: {os}; }}
button.app:hover, flowboxchild:focus button.app {{ background: {sv}; }}
flowboxchild {{ background: transparent; padding: 0; }}
.applabel {{ font-size: 12px; }}
list {{ background: transparent; }}
row {{ border-radius: 14px; padding: 6px 10px; color: {os}; background: transparent; }}
row:hover {{ background: {sv}; }}
row:selected, row:selected label {{ background: {ac}; color: {oac}; }}
row.hdr, row.hdr:hover {{ background: transparent; padding: 10px 10px 2px 10px; }}
.hdrl {{ font-size: 12px; font-weight: 500; color: {osv}; }}
.rt {{ font-size: 14px; }}
.rs {{ font-size: 12px; color: {osv}; }}
row:selected .rs {{ color: {oac}; }}
.calc {{ font-size: 20px; font-weight: 500; }}
scrollbar {{ background: transparent; }}
"#, s = g("SURFACE"), sv = g("SURFACE_VARIANT"), os = g("ON_SURFACE"), osv = g("ON_SURFACE_VARIANT"), a = g("ACCENT"),
        ac = g("ACCENT_CONTAINER"), oac = g("ON_ACCENT_CONTAINER")) + &theme::shelf_css(p)
}

#[derive(Clone)] enum Act { App(gio::DesktopAppInfo), Calc(String), Webapp(String, Option<String>), Set(String), File(PathBuf, bool), Web(String) }
struct L {
    win: gtk::Window, entry: gtk::SearchEntry, stack: gtk::Stack, grid: gtk::FlowBox, list: gtk::ListBox,
    apps: Vec<gio::DesktopAppInfo>, rows: Vec<(gtk::ListBoxRow, Act)>, files: Arc<Mutex<FileIndex>>,
    prov: gtk::CssProvider, palm: Option<SystemTime>, menu: Option<menu::PopMenu>, screen: (i32, i32),
}
type R = Rc<RefCell<L>>;

fn app_icon(a: &gio::DesktopAppInfo) -> gio::Icon { a.icon().unwrap_or_else(|| gio::ThemedIcon::new("application-x-executable").upcast()) }
fn app_order() -> Vec<String> { theme::settings().get("app_order").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default() }
fn sorted_apps() -> Vec<gio::DesktopAppInfo> {
    let order = app_order();
    let mut apps: Vec<gio::DesktopAppInfo> = gio::AppInfo::all().into_iter().filter(|a| a.should_show()).filter_map(|a| a.downcast::<gio::DesktopAppInfo>().ok()).collect();
    let key = |a: &gio::DesktopAppInfo| { let id = a.id().map(|s| s.to_string()).unwrap_or_default();
        (order.iter().position(|x| *x == id).unwrap_or(order.len()), a.display_name().to_lowercase()) };
    apps.sort_by_key(|a| key(a)); apps
}
fn aid(a: &gio::DesktopAppInfo) -> String { a.id().map(|s| s.to_string()).unwrap_or_default() }

fn load_apps(r: &R) { let apps = sorted_apps(); r.borrow_mut().apps = apps; build_grid(r); }

fn build_grid(r: &R) {
    let (grid, apps) = { let l = r.borrow(); (l.grid.clone(), l.apps.clone()) };
    while let Some(c) = grid.first_child() { grid.remove(&c); }
    for a in apps {
        let b = gtk::Button::new(); b.add_css_class("app");
        let v = gtk::Box::new(gtk::Orientation::Vertical, 6);
        let im = gtk::Image::from_gicon(&app_icon(&a)); im.set_pixel_size(48); v.append(&im);
        let l = gtk::Label::new(Some(&a.display_name())); l.set_ellipsize(pango::EllipsizeMode::End); l.set_max_width_chars(11); l.add_css_class("applabel");
        v.append(&l); b.set_child(Some(&v));
        b.set_tooltip_text(Some(&a.description().map(|d| d.to_string()).unwrap_or_else(|| a.display_name().to_string())));
        { let (r, a) = (r.clone(), a.clone()); b.connect_clicked(move |_| launch_app(&r, &a)); }
        let rc = gtk::GestureClick::new(); rc.set_button(3);
        { let (r, a, b2) = (r.clone(), a.clone(), b.clone()); rc.connect_pressed(move |_, _, x, y| app_menu(&r, &b2, x, y, &a, true)); }
        b.add_controller(rc);
        // drag & drop order (launcher.py Revision 17): drop app A on app B -> A moves next to B, saved in app_order
        let ds = gtk::DragSource::new(); ds.set_actions(gdk::DragAction::MOVE);
        { let id = aid(&a); ds.connect_prepare(move |_, _, _| Some(gdk::ContentProvider::for_value(&id.to_value()))); }
        { let ic = app_icon(&a); ds.connect_drag_begin(move |s, _| {
            let it = gtk::IconTheme::for_display(&gdk::Display::default().unwrap());
            let p = it.lookup_by_gicon(&ic, 48, 1, gtk::TextDirection::None, gtk::IconLookupFlags::empty()); s.set_icon(Some(&p), 24, 24); }); }
        b.add_controller(ds);
        let dt = gtk::DropTarget::new(glib::Type::STRING, gdk::DragAction::MOVE);
        { let (r, dst) = (r.clone(), aid(&a)); dt.connect_drop(move |_, v, _, _| {
            if let Ok(src) = v.get::<String>() { let r = r.clone(); let dst = dst.clone(); glib::idle_add_local_once(move || reorder(&r, &src, &dst)); } true }); }
        b.add_controller(dt);
        grid.insert(&b, -1);
    }
}

fn reorder(r: &R, src: &str, dst: &str) {
    let orig: Vec<String> = r.borrow().apps.iter().map(aid).collect();
    if src == dst || !orig.iter().any(|x| x == src) { return; }
    let (si, di) = (orig.iter().position(|x| x == src).unwrap(), orig.iter().position(|x| x == dst).unwrap());
    let mut ids = orig.clone(); ids.retain(|x| x != src);
    let at = ids.iter().position(|x| x == dst).unwrap() + if si < di { 1 } else { 0 };
    ids.insert(at, src.to_string());
    theme::update_setting("app_order", serde_json::Value::from(ids)); println!("reorder {src} -> {dst}"); load_apps(r);
}

fn app_menu(r: &R, w: &impl IsA<gtk::Widget>, x: f64, y: f64, a: &gio::DesktopAppInfo, grid: bool) {
    let id = aid(a); let pinned = theme::pinned(&theme::settings()).contains(&id);
    let pin = move |on: bool, id: String| { let mut p: Vec<String> = theme::pinned(&theme::settings()).into_iter().filter(|x| *x != id).collect(); if on { p.push(id) } theme::set_pinned(p); };
    let id2 = id.clone();
    let mut items = vec![if pinned { Item::Entry("view-pin-symbolic", "Losmaken van plank".into(), Some(Box::new(move || pin(false, id2.clone())))) }
                         else { Item::Entry("view-pin-symbolic", "Vastzetten aan plank".into(), Some(Box::new(move || pin(true, id2.clone())))) }];
    { let (r, a) = (r.clone(), a.clone()); items.push(Item::Entry("media-playback-start-symbolic", "Openen".into(), Some(Box::new(move || launch_app(&r, &a))))); }
    if grid { let r = r.clone(); items.push(Item::Sep); items.push(Item::Entry("view-sort-ascending-symbolic", "Sorteren op naam".into(),
        Some(Box::new(move || { theme::update_setting("app_order", serde_json::Value::from(Vec::<String>::new())); load_apps(&r); })))); }
    // pointer in screen coordinates = widget point -> window + the layer surface's position
    let win = r.borrow().win.clone(); let sc = r.borrow().screen;
    let pt = w.as_ref().compute_point(&win, &gtk::graphene::Point::new(x as f32, y as f32)).unwrap_or(gtk::graphene::Point::new(0.0, 0.0));
    let (sx, sy) = (MARGIN + pt.x() as i32, sc.1 - SHELF - H + pt.y() as i32);
    let m = menu::show(items, sx, sy, false, Some(&a.display_name()), sc);
    r.borrow_mut().menu = Some(m);
    // menu_closed(): back to the launcher with focus in the search field
    let r2 = r.clone();
    glib::timeout_add_local(Duration::from_millis(100), move || {
        let open = r2.borrow().menu.as_ref().map(|m| m.is_open()).unwrap_or(false);
        if open { return glib::ControlFlow::Continue; }
        let mut l = r2.borrow_mut(); l.menu = None;
        if l.win.is_visible() { let (w, e) = (l.win.clone(), l.entry.clone()); drop(l); w.present(); e.grab_focus(); e.set_position(-1); }
        glib::ControlFlow::Break
    });
}

fn refresh_style(r: &R) {
    let pal = theme::config_dir().join("palette.env"); let m = theme::mtime(&pal);
    let mut l = r.borrow_mut(); if m != l.palm { l.palm = m; #[allow(deprecated)] l.prov.load_from_data(&css(&theme::palette())); }
}
fn show_l(r: &R) {
    refresh_style(r);
    let (w, e, st) = { let l = r.borrow(); (l.win.clone(), l.entry.clone(), l.stack.clone()) };
    e.set_text(""); st.set_visible_child_name("grid"); w.present(); e.grab_focus();
    let f = Path::new("/tmp/osb-launcher.shown");
    if std::fs::OpenOptions::new().create(true).write(true).open(f).is_ok() { let _ = std::fs::File::options().write(true).open(f).and_then(|f| f.set_modified(SystemTime::now())); }
}
fn hide_l(r: &R) { let w = r.borrow().win.clone(); w.set_visible(false); }
fn toggle(r: &R) { if r.borrow().win.is_visible() { hide_l(r) } else { show_l(r) } }

fn header(r: &R, t: &str) {
    let row = gtk::ListBoxRow::new(); row.set_selectable(false); row.set_activatable(false); row.add_css_class("hdr");
    let l = gtk::Label::builder().label(t).xalign(0.0).build(); l.add_css_class("hdrl"); row.set_child(Some(&l));
    let list = r.borrow().list.clone(); list.append(&row);
}
fn row(r: &R, icon: Result<gio::Icon, &str>, title: &str, sub: &str, act: Act, big: bool) -> gtk::ListBoxRow {
    let row = gtk::ListBoxRow::new(); let b = gtk::Box::new(gtk::Orientation::Horizontal, 14);
    let img = match icon { Ok(g) => gtk::Image::from_gicon(&g), Err(n) => gtk::Image::from_icon_name(n) }; img.set_pixel_size(28); b.append(&img);
    let v = gtk::Box::new(gtk::Orientation::Vertical, 0); v.set_valign(gtk::Align::Center); v.set_hexpand(true);
    let t = gtk::Label::builder().label(title).xalign(0.0).ellipsize(pango::EllipsizeMode::End).build(); t.add_css_class(if big { "calc" } else { "rt" }); v.append(&t);
    if !sub.is_empty() { let s = gtk::Label::builder().label(sub).xalign(0.0).ellipsize(pango::EllipsizeMode::End).build(); s.add_css_class("rs"); v.append(&s); }
    b.append(&v); row.set_child(Some(&b));
    if let Act::App(a) = &act {   // right-click a search result app -> pin menu
        let g = gtk::GestureClick::new(); g.set_button(3); let (r2, a, rw) = (r.clone(), a.clone(), row.clone());
        g.connect_pressed(move |_, _, x, y| app_menu(&r2, &rw, x, y, &a, false)); row.add_controller(g);
    }
    let list = r.borrow().list.clone(); list.append(&row); r.borrow_mut().rows.push((row.clone(), act)); row
}

fn on_changed(r: &R) {
    let q = r.borrow().entry.text().trim().to_string();
    let (list, stack) = { let l = r.borrow(); (l.list.clone(), l.stack.clone()) };
    if q.is_empty() { stack.set_visible_child_name("grid"); return; }
    let ql = q.to_lowercase();
    while let Some(c) = list.first_child() { list.remove(&c); }
    r.borrow_mut().rows.clear();
    let mut first: Option<gtk::ListBoxRow> = None;
    {
        if let Some((url, name)) = webapp_cmd(&q) {
            header(r, "Webapp");
            let sub = format!("{}  ·  Enter installeert", name.as_ref().map(|n| format!("Naam: {n}")).unwrap_or_else(|| "Pictogram en naam komen van de website".into()));
            first = Some(row(r, Err("web-browser-symbolic"), &format!("{url} als app installeren"), &sub, Act::Webapp(url, name), true));
        } }
    if let Some(res) = calc::calc(&q) {
        header(r, "Rekenmachine");
        let rw = row(r, Err("accessories-calculator-symbolic"), &format!("= {res}"), &format!("{q}  ·  Enter kopieert het resultaat"), Act::Calc(res), true);
        first = first.or(Some(rw));
    }
    let apps = r.borrow().apps.clone();
    let mut sc: Vec<(f64, gio::DesktopAppInfo)> = apps.into_iter().map(|a| {
        let kw: Vec<String> = a.keywords().iter().map(|k| k.to_string()).collect();
        (score(&ql, &[&a.display_name(), &a.generic_name().map(|g| g.to_string()).unwrap_or_default(), &kw.join(" "), &aid(&a)]), a) }).collect();
    sc.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let apps: Vec<_> = sc.into_iter().filter(|x| x.0 >= 30.0).take(5).map(|x| x.1).collect();
    if !apps.is_empty() {
        header(r, "Apps");
        for a in apps {
            let sub = a.generic_name().map(|s| s.to_string()).or(a.description().map(|s| s.to_string())).unwrap_or_default();
            let rw = row(r, Ok(app_icon(&a)), &a.display_name(), &sub, Act::App(a.clone()), false); first = first.or(Some(rw));
        }
    }
    let mut sets: Vec<(f64, usize)> = SECTIONS.iter().enumerate().map(|(i, (t, sub, _, k))| (score(&ql, &[t, k, sub]), i)).collect();
    sets.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let sets: Vec<usize> = sets.into_iter().filter(|x| x.0 >= 45.0).take(3).map(|x| x.1).collect();
    if !sets.is_empty() {
        header(r, "Instellingen");
        for i in sets { let (t, sub, sec, _) = SECTIONS[i];
            let rw = row(r, Err("emblem-system-symbolic"), t, &format!("Instellingen › {sub}"), Act::Set(sec.into()), false); first = first.or(Some(rw)); }
    }
    if ql.chars().count() >= 2 {
        let fx = r.borrow().files.clone(); let files = search_files(&fx, &ql, 5);
        if !files.is_empty() {
            header(r, "Bestanden"); let home = files_home(); let base = home.parent().map(Path::to_path_buf).unwrap_or_default();
            for f in files {
                let rel = f.path.parent().and_then(|p| p.strip_prefix(&base).ok()).map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
                let when = glib::DateTime::from_unix_local(f.mtime).ok().and_then(|d| d.format("%d-%m-%Y %H:%M").ok()).map(|s| s.to_string()).unwrap_or_default();
                let icon = if f.dir { Err("folder-symbolic") } else { let (ct, _) = gio::content_type_guess(Some(&f.path), &[]); Ok(gio::content_type_get_icon(&ct)) };
                let rw = row(r, icon, &f.name, &format!("{rel} · gewijzigd {when}"), Act::File(f.path.clone(), f.dir), false); first = first.or(Some(rw));
            }
        }
    }
    header(r, "Internet");
    let web = row(r, Err("web-browser-symbolic"), &format!("Zoeken op het web: {q}"), "Google in Chromium", Act::Web(q.clone()), false);
    stack.set_visible_child_name("results");
    list.select_row(Some(&first.unwrap_or(web)));
}

/// launcher.py Revision 25 regex: ^(?:installeer|install)\s+(\S+\.\S+)(?:\s+als\s+app)?(?:\s+(.+))?$ (case-insensitive)
fn webapp_cmd(q: &str) -> Option<(String, Option<String>)> {
    let mut w = q.split_whitespace();
    let k = w.next()?.to_lowercase(); if k != "installeer" && k != "install" { return None; }
    let url = w.next()?; let dot = url.char_indices().skip(1).any(|(i, c)| c == '.' && i + 1 < url.len()); if !dot { return None; }
    let mut rest: Vec<&str> = w.collect();
    if rest.len() >= 2 && rest[0].eq_ignore_ascii_case("als") && rest[1].eq_ignore_ascii_case("app") { rest.drain(..2); }
    Some((url.to_string(), if rest.is_empty() { None } else { Some(rest.join(" ")) }))
}
fn move_sel(r: &R, d: i32) {
    let (list, rows) = { let l = r.borrow(); (l.list.clone(), l.rows.iter().map(|x| x.0.clone()).collect::<Vec<_>>()) };
    if rows.is_empty() { return; }
    let cur = list.selected_row(); let i = cur.and_then(|c| rows.iter().position(|x| *x == c)).map(|i| i as i32).unwrap_or(-1);
    let i = (i + d).clamp(0, rows.len() as i32 - 1) as usize;
    list.select_row(Some(&rows[i])); let (_, h) = (0, 0); let _ = h;
    if let Some(adj) = list.parent().and_then(|p| p.parent()).and_then(|s| s.downcast::<gtk::ScrolledWindow>().ok()).map(|s| s.vadjustment()) {
        if let Some(b) = rows[i].compute_bounds(&list) { let (y, hh) = (b.y() as f64, b.height() as f64);
            if y < adj.value() { adj.set_value(y) } else if y + hh > adj.value() + adj.page_size() { adj.set_value(y + hh - adj.page_size()) } }
    }
}

fn run_row(r: &R, row: &gtk::ListBoxRow) {
    let act = r.borrow().rows.iter().find(|x| x.0 == *row).map(|x| x.1.clone()); let Some(act) = act else { return };
    match act {
        Act::App(a) => { launch_app(r, &a); return; }
        Act::Calc(v) => {
            gdk::Display::default().unwrap().clipboard().set_text(&v.replace(' ', ""));   // resident process keeps owning the selection
            run(&["notify-send", "-a", "Rekenmachine", "Gekopieerd", &v]);
        }
        Act::Webapp(url, name) => {
            std::thread::spawn(move || {
                let mut c = Command::new("python3"); c.arg(cpath("webapps/webapps.py")).arg("install").arg(&url); if let Some(n) = &name { c.arg(n); }
                match c.output() {
                    Ok(o) if o.status.success() => {
                        let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap_or_default();
                        let (n, i) = (v["name"].as_str().unwrap_or(&url).to_string(), v["icon"].as_str().unwrap_or("web-browser").to_string());
                        let _ = Command::new("notify-send").args(["-a", "Webapps", "-i", &i, "Webapp geïnstalleerd", &format!("{n} staat nu in de launcher")]).status();
                    }
                    Ok(o) => { let e = String::from_utf8_lossy(&o.stderr); let last = e.trim().lines().last().unwrap_or("onbekende fout").chars().take(200).collect::<String>();
                        let _ = Command::new("notify-send").args(["-a", "Webapps", "Installeren mislukt", &last]).status(); }
                    Err(e) => { let _ = Command::new("notify-send").args(["-a", "Webapps", "Installeren mislukt", &e.to_string()]).status(); }
                }
            });
        }
        Act::Set(s) if s == "__welkom" => run(&["python3", &cpath("welcome/welkom.py")]),
        Act::Set(s) if s == "__sneltoetsen" => run(&["python3", &cpath("shortcuts/sneltoetsen.py")]),
        Act::Set(s) => run(&["python3", &cpath("settings/instellingen.py"), &s]),
        Act::File(p, true) => run(&[&cpath("files/run-files.sh"), &p.to_string_lossy()]),
        Act::File(p, false) => run(&["gio", "open", &p.to_string_lossy()]),
        Act::Web(q) => {
            let url = format!("https://www.google.com/search?q={}", form_quote(&q));
            // same profile as the shelf's Chromium -> opens as a tab in the running browser (session rewrites /tmp/protohome/chromium to this)
            let prof = std::env::var("POLDER_CHROMIUM_PROFILE").unwrap_or_else(|_| format!("{}/.config/chromium", std::env::var("HOME").unwrap_or_default()));
            run(&["chromium", &format!("--user-data-dir={prof}"), "--no-first-run", &url]);
        }
    }
    hide_l(r);
}
/// urllib.parse.quote_plus
fn form_quote(s: &str) -> String {
    s.bytes().map(|b| match b { b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => (b as char).to_string(), b' ' => "+".into(), _ => format!("%{b:02X}") }).collect()
}
fn launch_app(r: &R, a: &gio::DesktopAppInfo) {
    let ctx = gdk::Display::default().map(|d| d.app_launch_context());
    if let Err(e) = a.launch(&[], ctx.as_ref()) { eprintln!("launch {e}"); }
    hide_l(r);
}

fn build(app: &gtk::Application) {
    let win = gtk::Window::builder().title("Polder Launcher").decorated(false).resizable(false).application(app).build();
    win.set_widget_name("lwin"); win.set_default_size(W, H);
    let prov = gtk::CssProvider::new(); let disp = gdk::Display::default().unwrap();
    gtk::style_context_add_provider_for_display(&disp, &prov, 800);
    let mons = disp.monitors(); let screen = mons.item(0).and_downcast::<gdk::Monitor>().map(|m| { let g = m.geometry(); (g.width(), g.height()) }).unwrap_or((1366, 768));
    if gtk4_layer_shell::is_supported() {
        win.init_layer_shell(); win.set_namespace("polder-launcher"); win.set_layer(Layer::Overlay);
        win.set_anchor(Edge::Left, true); win.set_anchor(Edge::Bottom, true); win.set_margin(Edge::Left, MARGIN); win.set_margin(Edge::Bottom, SHELF);
        win.set_exclusive_zone(0); win.set_keyboard_mode(KeyboardMode::Exclusive);
    }
    let bx = gtk::Box::new(gtk::Orientation::Vertical, 12); bx.set_widget_name("lbox"); bx.set_size_request(W, H); win.set_child(Some(&bx));
    let entry = gtk::SearchEntry::new(); entry.set_widget_name("search");
    entry.set_placeholder_text(Some("Zoek op je apparaat, in apps, instellingen, op internet…")); bx.append(&entry);
    let stack = gtk::Stack::new(); stack.set_vexpand(true); bx.append(&stack);
    let grid = gtk::FlowBox::new(); grid.set_max_children_per_line(5); grid.set_min_children_per_line(5);
    grid.set_selection_mode(gtk::SelectionMode::None); grid.set_homogeneous(true); grid.set_valign(gtk::Align::Start);
    let sc = gtk::ScrolledWindow::new(); sc.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic); sc.set_child(Some(&grid)); stack.add_named(&sc, Some("grid"));
    let list = gtk::ListBox::new();
    let sc2 = gtk::ScrolledWindow::new(); sc2.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic); sc2.set_child(Some(&list)); stack.add_named(&sc2, Some("results"));
    let files = Arc::new(Mutex::new(FileIndex::default())); refresh(&files);
    let r: R = Rc::new(RefCell::new(L { win: win.clone(), entry: entry.clone(), stack, grid, list: list.clone(), apps: vec![], rows: vec![], files, prov, palm: None, menu: None, screen }));
    load_apps(&r);
    { let r = r.clone(); let mon = gio::AppInfoMonitor::get(); mon.connect_changed(move |_| load_apps(&r)); std::mem::forget(mon); }
    { let r = r.clone(); entry.connect_changed(move |_| on_changed(&r)); }
    { let r = r.clone(); entry.connect_activate(move |_| { let (st, l) = { let x = r.borrow(); (x.stack.clone(), x.list.clone()) };
        if st.visible_child_name().as_deref() == Some("results") { if let Some(row) = l.selected_row() { run_row(&r, &row) } } }); }
    { let r = r.clone(); entry.connect_stop_search(move |_| hide_l(&r)); }
    { let r = r.clone(); list.connect_row_activated(move |_, row| run_row(&r, row)); }
    let k = gtk::EventControllerKey::new(); k.set_propagation_phase(gtk::PropagationPhase::Capture);
    { let r = r.clone(); k.connect_key_pressed(move |_, key, _, _| {
        if key == gdk::Key::Escape { hide_l(&r); return glib::Propagation::Stop; }
        let res = r.borrow().stack.visible_child_name().as_deref() == Some("results");
        if res && (key == gdk::Key::Down || key == gdk::Key::Up) { move_sel(&r, if key == gdk::Key::Down { 1 } else { -1 }); return glib::Propagation::Stop; }
        glib::Propagation::Proceed }); }
    win.add_controller(k);
    { let r = r.clone(); win.connect_is_active_notify(move |w| if !w.is_active() {
        let r = r.clone(); glib::timeout_add_local_once(Duration::from_millis(150), move || {
            let l = r.borrow(); let busy = l.menu.is_some(); let (w, act) = (l.win.clone(), l.win.is_active()); drop(l);
            if !busy && !act && w.is_visible() { w.set_visible(false); } }); }); }
    { let r = r.clone(); win.connect_close_request(move |_| { hide_l(&r); glib::Propagation::Stop }); }
    { let r = r.clone(); glib::unix_signal_add_local(libc::SIGUSR1, move || { let r = r.clone(); glib::idle_add_local_once(move || toggle(&r)); glib::ControlFlow::Continue }); }
    glib::unix_signal_add_local(libc::SIGTERM, || { let _ = std::fs::remove_file(pidfile()); std::process::exit(0) });
    std::mem::forget(app.hold());
    if std::env::args().any(|a| a == "--show") { show_l(&r); }
}

fn main() {
    if let Ok(p) = std::fs::read_to_string(pidfile()) {
        if let Ok(p) = p.trim().parse::<i32>() { if p > 0 && unsafe { libc::kill(p, 0) } == 0 { println!("already running"); return; } }
    }
    let _ = std::fs::write(pidfile(), std::process::id().to_string());
    let app = gtk::Application::builder().application_id("org.polderos.Launcher").flags(gio::ApplicationFlags::NON_UNIQUE).build();
    app.connect_activate(build);
    app.run_with_args::<&str>(&[]);
}
