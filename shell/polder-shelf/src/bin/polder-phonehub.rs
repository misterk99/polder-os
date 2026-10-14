#![allow(dead_code)]
//! Polder Telefoon-hub (ChromeOS Phone Hub / Phone Link style) on KDE Connect: battery, network, phone notifications
//! (dismiss / reply), find my phone, send file, shared clipboard, photos + files via sftp, and the pairing flow.
//! Overlay layer surface above the shelf; run again to close. Every value comes from kdeconnectd over D-Bus.
#[path = "../theme.rs"] mod theme;
#[path = "../kdc.rs"] mod kdc;
use gtk::{gdk, gio, glib, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use kdc::{Dev, Info};
use std::{cell::RefCell, rc::Rc};

const W: i32 = 400;
#[derive(Clone, Debug, PartialEq)]
enum St { NotInstalled, NotRunning, NoDevice(Vec<Dev>), Paired(Dev, Info) }

struct Hub { win: gtk::Window, body: gtk::Box, sig: Option<St>, toast: gtk::Label, photos: Option<(String, Vec<(String, String)>)>, prov: gtk::CssProvider, palm: Option<std::time::SystemTime> }
type H = Rc<RefCell<Hub>>;

fn pidfile() -> std::path::PathBuf { theme::rundir().join("polder-phonehub.pid") }
fn quit() -> ! { let _ = std::fs::remove_file(pidfile()); let _ = std::fs::write(theme::rundir().join("polder-phonehub.closed"), ""); std::process::exit(0) }
fn run(argv: &[&str]) {
    let mut c = std::process::Command::new(argv[0]); c.args(&argv[1..]).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null());
    use std::os::unix::process::CommandExt; c.process_group(0);
    if let Ok(mut ch) = c.spawn() { std::thread::spawn(move || ch.wait()); }
}
fn open_path(p: &str) {
    let rf = theme::config_dir().join("files/run-files.sh");
    if std::path::Path::new(p).is_dir() && rf.exists() { run(&[&rf.to_string_lossy(), p]) } else { run(&["gio", "open", p]) }
}
fn lbl(t: &str, cls: &str) -> gtk::Label { let l = gtk::Label::builder().label(t).xalign(0.0).wrap(true).max_width_chars(40).build(); l.set_wrap_mode(gtk::pango::WrapMode::WordChar); if !cls.is_empty() { l.add_css_class(cls); } l }
fn pill(t: &str, active: bool) -> gtk::Button { let b = gtk::Button::with_label(t); b.add_css_class("pill"); if active { b.add_css_class("active"); } b }

fn snapshot() -> St {
    if !kdc::running() { return if kdc::installed() { St::NotRunning } else { St::NotInstalled }; }
    let devs = kdc::devices();
    match devs.iter().find(|d| d.paired) {
        Some(d) => { let i = if d.reachable { kdc::info(d) } else { Info::default() }; St::Paired(d.clone(), i) }
        None => St::NoDevice(devs.into_iter().filter(|d| d.reachable).collect()),
    }
}

fn toast(h: &H, t: &str) {
    let l = h.borrow().toast.clone(); l.set_text(t); l.set_visible(true);
    let l2 = l.clone(); glib::timeout_add_local_once(std::time::Duration::from_secs(4), move || l2.set_visible(false));
}
fn res(h: &H, r: Result<glib::Variant, String>, ok: &str) { match r { Ok(_) => toast(h, ok), Err(e) => toast(h, &format!("Mislukt: {e}")) } }

fn refresh(h: &H, force: bool) {
    let st = snapshot();
    if !force && h.borrow().sig.as_ref() == Some(&st) { return; }
    let body = h.borrow().body.clone();
    while let Some(c) = body.first_child() { body.remove(&c); }
    match &st {
        St::NotInstalled => {
            body.append(&lbl("KDE Connect is niet geïnstalleerd", "htitle"));
            body.append(&lbl("Installeer het pakket kdeconnect om je telefoon te koppelen (ook nodig op je telefoon: de app KDE Connect).", "hsub"));
        }
        St::NotRunning => {
            body.append(&lbl("KDE Connect staat uit", "htitle"));
            body.append(&lbl("Start de verbindingsdienst om je telefoon te vinden.", "hsub"));
            let b = pill("Starten", true); let w = Rc::downgrade(h);
            b.connect_clicked(move |_| if let Some(h) = w.upgrade() { if kdc::start() { toast(&h, "KDE Connect wordt gestart…") } else { toast(&h, "Starten is mislukt") } });
            body.append(&b);
        }
        St::NoDevice(devs) => {
            body.append(&lbl("Telefoon koppelen", "htitle"));
            if devs.is_empty() {
                body.append(&lbl("Open KDE Connect op je telefoon. Je telefoon en deze computer moeten op hetzelfde wifi-netwerk zitten.", "hsub"));
            }
            for d in devs {
                let card = gtk::Box::new(gtk::Orientation::Vertical, 8); card.add_css_class("card"); card.add_css_class("inner");
                let row = gtk::Box::new(gtk::Orientation::Horizontal, 10);
                let ic = gtk::Image::from_icon_name("phone-symbolic"); ic.set_pixel_size(24); ic.add_css_class("appicon"); row.append(&ic);
                let n = lbl(&d.name, "ntitle"); n.set_hexpand(true); row.append(&n); card.append(&row);
                let acts = gtk::Box::new(gtk::Orientation::Horizontal, 8);
                let id = d.id.clone();
                let mk = |t: &str, act: bool, m: &'static str, ok: &'static str| { let b = pill(t, act); let (w, id) = (Rc::downgrade(h), id.clone());
                    b.connect_clicked(move |_| if let Some(h) = w.upgrade() { res(&h, kdc::dev_call(&id, m, None), ok); refresh(&h, true) }); b };
                if d.by_peer {
                    card.append(&lbl(&format!("{} wil koppelen. Controleer dat deze code ook op je telefoon staat: {}", d.name, d.key), "hsub"));
                    acts.append(&mk("Accepteren", true, "acceptPairing", "Gekoppeld")); acts.append(&mk("Weigeren", false, "cancelPairing", "Geweigerd"));
                } else if d.requested {
                    card.append(&lbl(&format!("Bevestig op je telefoon. Code: {}", d.key), "hsub"));
                    acts.append(&mk("Annuleren", false, "cancelPairing", "Geannuleerd"));
                } else { acts.append(&mk("Koppelen", true, "requestPairing", "Koppelverzoek verstuurd")); }
                card.append(&acts); body.append(&card);
            }
            let b = pill("Opnieuw zoeken", false); let w = Rc::downgrade(h);
            b.connect_clicked(move |_| if let Some(h) = w.upgrade() { res(&h, kdc::call(kdc::ROOT, "org.kde.kdeconnect.daemon", "forceOnNetworkChange", None), "Zoeken…") });
            body.append(&b);
        }
        St::Paired(d, i) => build_paired(h, &body, d, i),
    }
    h.borrow_mut().sig = Some(st);
    // gtk4-layer-shell only grows a mapped surface: remap at the new natural height when the content got shorter
    let win = h.borrow().win.clone();
    if win.is_visible() {
        let (_, nat, _, _) = win.child().unwrap().measure(gtk::Orientation::Vertical, W);
        if nat + 8 < win.height() {
            win.set_visible(false); win.set_default_size(W, 1);
            let w2 = win.clone(); glib::timeout_add_local_once(std::time::Duration::from_millis(50), move || w2.present());
        }
    }
}

fn signal_bars(n: i32) -> &'static str { match n { i32::MIN..=0 => "network-cellular-signal-none-symbolic", 1 => "network-cellular-signal-weak-symbolic",
    2 => "network-cellular-signal-ok-symbolic", 3 => "network-cellular-signal-good-symbolic", _ => "network-cellular-signal-excellent-symbolic" } }

fn build_paired(h: &H, body: &gtk::Box, d: &Dev, i: &Info) {
    let has = |n: &str| d.plugins.iter().any(|x| x == n);
    // header: name + live status
    let hdr = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    let ic = gtk::Image::from_icon_name("phone-symbolic"); ic.set_pixel_size(28); ic.add_css_class("appicon"); hdr.append(&ic);
    let col = gtk::Box::new(gtk::Orientation::Vertical, 2); col.set_hexpand(true);
    col.append(&lbl(&d.name, "htitle"));
    let st = gtk::Box::new(gtk::Orientation::Horizontal, 6);
    st.append(&lbl(if d.reachable { "Verbonden" } else { "Niet bereikbaar" }, "hsub"));
    if let Some((c, ch)) = i.battery {
        let lv = (c + 5) / 10 * 10;
        st.append(&gtk::Image::from_icon_name(&format!("battery-level-{lv}{}-symbolic", if ch { "-charging" } else { "" })));
        st.append(&lbl(&format!("{c}%{}", if ch { " (laadt op)" } else { "" }), "hsub"));
    }
    if let Some((t, s)) = &i.net { st.append(&gtk::Image::from_icon_name(signal_bars(*s))); st.append(&lbl(t, "hsub")); }
    col.append(&st); hdr.append(&col); body.append(&hdr);
    if !d.reachable { body.append(&lbl("Je telefoon is gekoppeld maar niet in de buurt of niet op hetzelfde netwerk.", "hsub")); }
    else {
        // actions
        let g = gtk::Grid::new(); g.set_column_spacing(8); g.set_row_spacing(8); g.set_column_homogeneous(true);
        let mut n = 0;
        let mut add = |w: &gtk::Widget| { g.attach(w, n % 2, n / 2, 1, 1); n += 1; };
        let tile = |icon: &str, t: &str| { let b = gtk::Button::new(); b.add_css_class("tile"); let bx = gtk::Box::new(gtk::Orientation::Horizontal, 10);
            let im = gtk::Image::from_icon_name(icon); im.set_pixel_size(20); bx.append(&im); let l = lbl(t, "title"); l.set_wrap(false); bx.append(&l); b.set_child(Some(&bx)); b };
        if has("kdeconnect_findmyphone") {
            let b = tile("find-location-symbolic", "Telefoon zoeken"); let (w, id) = (Rc::downgrade(h), d.id.clone());
            b.connect_clicked(move |_| if let Some(h) = w.upgrade() { res(&h, kdc::plugin_call(&id, "findmyphone", "findmyphone", "ring", None), "Je telefoon gaat over") });
            add(b.upcast_ref());
        }
        if has("kdeconnect_share") {
            let b = tile("document-send-symbolic", "Bestand sturen"); let (w, id) = (Rc::downgrade(h), d.id.clone());
            b.connect_clicked(move |_| if let Some(h) = w.upgrade() { send_file(&h, &id) });
            add(b.upcast_ref());
        }
        if let Some(on) = i.clipboard {
            let b = gtk::ToggleButton::new(); b.add_css_class("tile"); b.set_active(on);
            let bx = gtk::Box::new(gtk::Orientation::Horizontal, 10); let im = gtk::Image::from_icon_name("edit-paste-symbolic"); im.set_pixel_size(20); bx.append(&im);
            let tb = gtk::Box::new(gtk::Orientation::Vertical, 0); let l = lbl("Klembord delen", "title"); l.set_wrap(false); tb.append(&l);
            tb.append(&lbl(if on { "Aan" } else { "Uit" }, "sub")); bx.append(&tb); b.set_child(Some(&bx));
            let (w, id) = (Rc::downgrade(h), d.id.clone());
            b.connect_toggled(move |b| if let Some(h) = w.upgrade() {
                res(&h, kdc::dev_call(&id, "setPluginEnabled", Some(("kdeconnect_clipboard", b.is_active()).to_variant())),
                    if b.is_active() { "Klembord wordt gedeeld" } else { "Klembord delen uit" }); refresh(&h, true) });
            add(b.upcast_ref());
        }
        if has("kdeconnect_sftp") {
            let b = tile("folder-pictures-symbolic", "Foto's en bestanden"); let (w, id) = (Rc::downgrade(h), d.id.clone());
            b.connect_clicked(move |_| if let Some(h) = w.upgrade() {
                match kdc::sftp_dirs(&id) { Ok(r) => { h.borrow_mut().photos = Some(r); refresh(&h, true) } Err(e) => toast(&h, &e) } });
            add(b.upcast_ref());
        }
        body.append(&g);
        if let Some((mp, dirs)) = h.borrow().photos.clone() { body.append(&photos(&mp, &dirs)); }
        // phone notifications
        if has("kdeconnect_notifications") {
            body.append(&lbl(&format!("Meldingen van je telefoon ({})", i.notifs.len()), "histtitle"));
            if i.notifs.is_empty() { body.append(&lbl("Geen meldingen", "hsub")); }
            for nt in &i.notifs { body.append(&notif_card(h, &d.id, nt)); }
        }
    }
    // footer
    let ft = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let un = pill("Ontkoppelen", false); let (w, id) = (Rc::downgrade(h), d.id.clone());
    un.connect_clicked(move |_| if let Some(h) = w.upgrade() { res(&h, kdc::dev_call(&id, "unpair", None), "Ontkoppeld"); h.borrow_mut().photos = None; refresh(&h, true) });
    ft.append(&un);
    let sp = gtk::Box::new(gtk::Orientation::Horizontal, 0); sp.set_hexpand(true); ft.append(&sp);
    let se = pill("Instellingen", false);
    se.connect_clicked(|_| { run(&["python3", &theme::config_dir().join("settings/instellingen.py").to_string_lossy(), "telefoon"]); quit() });
    ft.append(&se); body.append(&ft);
}

fn is_img(p: &std::path::Path) -> bool { p.extension().map(|e| ["jpg", "jpeg", "png", "webp", "heic"].contains(&e.to_string_lossy().to_lowercase().as_str())).unwrap_or(false) }
/// Recent photos (newest four from the camera folder) + the phone's shared folders, all from the sftp mount.
fn photos(mp: &str, dirs: &[(String, String)]) -> gtk::Box {
    let b = gtk::Box::new(gtk::Orientation::Vertical, 8); b.add_css_class("card"); b.add_css_class("inner");
    b.append(&lbl("Recente foto's", "ntitle"));
    let cam = dirs.iter().find(|(p, l)| l.eq_ignore_ascii_case("camera") || p.contains("DCIM")).map(|x| x.0.clone()).unwrap_or_else(|| mp.to_string());
    let mut imgs: Vec<_> = std::fs::read_dir(&cam).map(|r| r.flatten().map(|e| e.path()).filter(|p| is_img(p)).collect()).unwrap_or_default();
    imgs.sort_by_key(|p: &std::path::PathBuf| std::cmp::Reverse(theme::mtime(p)));
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    for p in imgs.iter().take(4) {
        let btn = gtk::Button::new(); btn.add_css_class("thumb");
        let pic = gtk::Picture::for_filename(p); pic.set_size_request(80, 80); pic.set_can_shrink(true); btn.set_child(Some(&pic));
        btn.set_tooltip_text(p.file_name().map(|f| f.to_string_lossy().to_string()).as_deref());
        let ps = p.to_string_lossy().to_string(); btn.connect_clicked(move |_| open_path(&ps)); row.append(&btn);
    }
    if imgs.is_empty() { b.append(&lbl("Geen foto's gevonden", "hsub")); } else { b.append(&row); }
    let fr = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    for (p, l) in dirs { let bt = pill(l, false); let p = p.clone(); bt.connect_clicked(move |_| open_path(&p)); fr.append(&bt); }
    let all = pill("Alle bestanden", false); let m = mp.to_string(); all.connect_clicked(move |_| open_path(&m)); fr.append(&all);
    b.append(&fr); b
}

fn notif_card(h: &H, dev: &str, n: &kdc::Notif) -> gtk::Box {
    let card = gtk::Box::new(gtk::Orientation::Vertical, 6); card.add_css_class("card"); card.add_css_class("inner");
    let top = gtk::Box::new(gtk::Orientation::Horizontal, 10);
    let col = gtk::Box::new(gtk::Orientation::Vertical, 2); col.set_hexpand(true);
    col.append(&lbl(&n.app, "app")); col.append(&lbl(&n.title, "ntitle")); if !n.text.is_empty() { col.append(&lbl(&n.text, "nbody")); }
    top.append(&col);
    if n.dismissable {
        let x = gtk::Button::from_icon_name("window-close-symbolic"); x.add_css_class("x"); x.set_valign(gtk::Align::Start); x.set_tooltip_text(Some("Wegvegen"));
        let (w, d, id) = (Rc::downgrade(h), dev.to_string(), n.id.clone());
        x.connect_clicked(move |_| if let Some(h) = w.upgrade() { res(&h, kdc::notif_call(&d, &id, "dismiss", None), "Melding weggeveegd"); refresh(&h, true) });
        top.append(&x);
    }
    card.append(&top);
    if !n.reply_id.is_empty() {   // only notifications the phone marked as repliable (KDE Connect replyId)
        let row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let e = gtk::Entry::new(); e.set_placeholder_text(Some("Antwoorden…")); e.set_hexpand(true); row.append(&e);
        let s = pill("Sturen", true);
        let (w, d, id, e2) = (Rc::downgrade(h), dev.to_string(), n.id.clone(), e.clone());
        let send = move || if let Some(h) = w.upgrade() { let t = e2.text().to_string(); if t.trim().is_empty() { return; }
            res(&h, kdc::notif_call(&d, &id, "sendReply", Some((t.as_str(),).to_variant())), "Antwoord verstuurd"); e2.set_text(""); };
        let s2 = send.clone(); s.connect_clicked(move |_| s2()); e.connect_activate(move |_| send());
        row.append(&s); card.append(&row);
    }
    card
}

/// GTK file chooser as a normal window; the overlay hides meanwhile so polder-comp's focus-out dismissal doesn't close the hub.
fn send_file(h: &H, id: &str) {
    let win = h.borrow().win.clone(); win.set_visible(false);
    #[allow(deprecated)]
    let fc = gtk::FileChooserDialog::new(Some("Bestand naar telefoon sturen"), None::<&gtk::Window>, gtk::FileChooserAction::Open,
                                         &[("Annuleren", gtk::ResponseType::Cancel), ("Sturen", gtk::ResponseType::Accept)]);
    #[allow(deprecated)] fc.set_select_multiple(true);
    let (w, id) = (Rc::downgrade(h), id.to_string());
    #[allow(deprecated)]
    fc.connect_response(move |fc, r| {
        let uris: Vec<String> = if r == gtk::ResponseType::Accept { let fs = fc.files();
            (0..fs.n_items()).filter_map(|i| fs.item(i).and_downcast::<gio::File>()).map(|f| f.uri().to_string()).collect() } else { vec![] };
        fc.destroy();
        if let Some(h) = w.upgrade() {
            h.borrow().win.present();
            if !uris.is_empty() { res(&h, kdc::plugin_call(&id, "share", "share", "shareUrls", Some((uris.clone(),).to_variant())),
                                      &format!("{} bestand(en) verstuurd", uris.len())); }
        }
    });
    fc.present();
}

fn build(app: &gtk::Application) -> H {
    let win = gtk::ApplicationWindow::new(app).upcast::<gtk::Window>();
    win.set_title(Some("Telefoon")); win.set_widget_name("qswin"); win.set_decorated(false);
    win.init_layer_shell(); win.set_namespace("polder-phonehub"); win.set_layer(Layer::Overlay);
    win.set_anchor(Edge::Right, true); win.set_anchor(Edge::Bottom, true); win.set_margin(Edge::Right, 10); win.set_margin(Edge::Bottom, 62);
    win.set_exclusive_zone(0); win.set_keyboard_mode(KeyboardMode::OnDemand);
    let prov = gtk::CssProvider::new(); gtk::style_context_add_provider_for_display(&gdk::Display::default().unwrap(), &prov, 800);
    let panel = gtk::Box::new(gtk::Orientation::Vertical, 12); panel.set_widget_name("panel"); panel.set_size_request(W, -1);
    let top = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let t = lbl("Telefoon", "histtitle"); t.set_hexpand(true); top.append(&t);
    let x = gtk::Button::from_icon_name("window-close-symbolic"); x.add_css_class("x"); x.set_tooltip_text(Some("Sluiten")); x.connect_clicked(|_| quit()); top.append(&x);
    panel.append(&top);
    let body = gtk::Box::new(gtk::Orientation::Vertical, 10); panel.append(&body);
    // toast floats over the panel bottom: it must not change the surface height (content would jump under the pointer)
    let toast = gtk::Label::new(None); toast.add_css_class("toast"); toast.set_visible(false);
    toast.set_valign(gtk::Align::End); toast.set_halign(gtk::Align::Center); toast.set_margin_bottom(56); toast.set_can_target(false);
    let ov = gtk::Overlay::new(); ov.set_child(Some(&panel)); ov.add_overlay(&toast);
    win.set_child(Some(&ov));
    let h: H = Rc::new(RefCell::new(Hub { win: win.clone(), body, sig: None, toast, photos: None, prov, palm: None }));
    let tick = |h: &H| { let m = theme::mtime(&theme::config_dir().join("palette.env"));
        let mut me = h.borrow_mut(); if me.palm != m || me.palm.is_none() { me.palm = m;
            #[allow(deprecated)] me.prov.load_from_data(&(theme::qs_css(&theme::palette()) + &theme::hub_css(&theme::palette()))); } };
    tick(&h); refresh(&h, true);
    let w = Rc::downgrade(&h);
    glib::timeout_add_local(std::time::Duration::from_secs(2), move || { if let Some(h) = w.upgrade() { tick(&h); refresh(&h, false); } glib::ControlFlow::Continue });
    let k = gtk::EventControllerKey::new(); k.connect_key_pressed(|_, key, _, _| { if key == gdk::Key::Escape { quit() } glib::Propagation::Proceed }); win.add_controller(k);
    win.connect_close_request(|w| { if w.is_visible() { quit() } glib::Propagation::Proceed });
    win.present();
    h
}

fn main() -> glib::ExitCode {
    let pid = pidfile();
    if let Some(p) = std::fs::read_to_string(&pid).ok().and_then(|s| s.trim().parse::<i32>().ok()) {
        let _ = std::fs::remove_file(&pid); if unsafe { libc::kill(p, libc::SIGTERM) } == 0 { return glib::ExitCode::SUCCESS; }
    }
    let closed = theme::rundir().join("polder-phonehub.closed");
    if theme::mtime(&closed).and_then(|t| t.elapsed().ok()).map(|e| e.as_millis() < 600).unwrap_or(false) { let _ = std::fs::remove_file(&closed); return glib::ExitCode::SUCCESS; }
    let _ = std::fs::write(&pid, std::process::id().to_string());
    if gtk::init().is_err() || !gtk4_layer_shell::is_supported() { eprintln!("polder-phonehub needs wlr-layer-shell"); let _ = std::fs::remove_file(&pid); return glib::ExitCode::FAILURE; }
    glib::unix_signal_add_local(libc::SIGTERM, || quit());
    let app = gtk::Application::new(Some("nl.polderos.PhoneHub"), gio::ApplicationFlags::NON_UNIQUE);
    let keep: Rc<RefCell<Option<H>>> = Rc::new(RefCell::new(None)); let k = keep.clone();
    app.connect_activate(move |a| { if k.borrow().is_none() { *k.borrow_mut() = Some(build(a)); } });
    app.run_with_args::<&str>(&[])
}
