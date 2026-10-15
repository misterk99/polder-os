#![allow(dead_code)]
//! Polder SafeHarbor: herstelpunten (btrfs + snapper) bekijken, maken en terugzetten.
//! All privileged work goes through the polkit helper (safeharbor/helper/polder-safeharbor-helper); the command used
//! is $POLDER_SAFEHARBOR_HELPER (default: pkexec /usr/libexec/polder-safeharbor-helper).
//! `polder-safeharbor --check` (session autostart) only sends notifications: failed previous boot, running from a
//! read-only snapshot, finished rollback. On non-btrfs systems (live ISO) the window shows a "niet beschikbaar" state.
//! `--settings` opens the Instellingen tab, `--status` prints the helper status JSON.
#[path = "../theme.rs"] mod theme;
use gtk::{gio, glib, prelude::*};
use serde_json::Value;
use std::{cell::RefCell, rc::Rc};

const MONTHS: [&str; 12] = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
const HELPER: &str = "/usr/libexec/polder-safeharbor-helper";

fn helper_argv() -> Vec<String> {
    std::env::var("POLDER_SAFEHARBOR_HELPER").unwrap_or_else(|_| format!("pkexec {HELPER}"))
        .split_whitespace().map(String::from).collect()
}
/// Run the helper; Ok(json stdout) or Err(message).
fn helper(args: &[String]) -> Result<Value, String> {
    let mut a = helper_argv(); a.extend(args.iter().cloned());
    let Some((cmd, rest)) = a.split_first() else { return Err("geen helper ingesteld".into()) };
    match std::process::Command::new(cmd).args(rest).output() {
        Err(e) => Err(format!("helper niet gevonden: {e}")),
        Ok(o) if o.status.success() => serde_json::from_slice(&o.stdout).map_err(|e| format!("onleesbaar antwoord: {e}")),
        Ok(o) => {
            let e = String::from_utf8_lossy(&o.stderr).trim().to_string();
            Err(match o.status.code() {
                Some(126) | Some(127) if e.is_empty() || e.contains("dismissed") || e.contains("Not authorized") => "Geen toestemming gegeven.".into(),
                _ => if e.is_empty() { "Er ging iets mis.".into() } else { e.lines().last().unwrap_or("").to_string() },
            })
        }
    }
}
fn unavailable(reason: &str) -> Value { serde_json::json!({"available": false, "reason": reason, "snapshots": []}) }
fn status() -> Value {
    if std::env::var("POLDER_SAFEHARBOR_HELPER").is_err() && !std::path::Path::new(HELPER).exists() {
        return unavailable("SafeHarbor is op dit systeem niet geïnstalleerd.");
    }
    helper(&["status".into()]).unwrap_or_else(|e| unavailable(&e))
}

/// snapper date "2026-10-14 10:03:12" -> "Vandaag, 10:03" / "Gisteren, 10:03" / "12 okt 2026, 10:03"
fn nl_date(s: &str) -> String {
    let (d, t) = s.split_once(' ').unwrap_or((s, ""));
    let hm: String = t.chars().take(5).collect();
    let p: Vec<i32> = d.split('-').filter_map(|x| x.parse().ok()).collect();
    if p.len() != 3 { return s.into(); }
    if let (Ok(n), Ok(dt)) = (glib::DateTime::now_local(), glib::DateTime::from_local(p[0], p[1], p[2], 12, 0, 0.0)) {
        if let Ok(today) = glib::DateTime::from_local(n.year(), n.month(), n.day_of_month(), 12, 0, 0.0) {
            let days = today.difference(&dt).as_seconds() / 86400;
            if days == 0 { return format!("Vandaag, {hm}"); }
            if days == 1 { return format!("Gisteren, {hm}"); }
        }
    }
    format!("{} {} {}, {hm}", p[2], MONTHS[(p[1] as usize).clamp(1, 12) - 1], p[0])
}
fn ud<'a>(s: &'a Value, k: &str) -> &'a str { s["userdata"][k].as_str().unwrap_or("") }
fn origin(s: &Value) -> &'static str {
    match (ud(s, "polder"), ud(s, "trigger")) {
        ("apt", "unattended-upgrades") => "Automatische update",
        ("apt", _) => "Software-wijziging",
        ("manual", _) => "Handmatig",
        _ => match s["type"].as_str() {
            Some("pre") | Some("post") => "Software-wijziging",
            _ => if s["cleanup"].as_str() == Some("timeline") { "Tijdlijn" } else { "Handmatig" },
        },
    }
}

fn css(p: &std::collections::HashMap<String, String>) -> String {
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    format!(r#"
window.sh {{ background: {s}; color: {os}; font-family: Roboto; }}
.title {{ font-size: 22px; font-weight: 500; }}
.sub {{ color: {osv}; font-size: 13px; }}
.banner {{ background: {ac}; color: {oac}; border-radius: 16px; padding: 14px 16px; }}
.banner.warn {{ background: #fce8e6; color: #5c1612; }}
.banner .btitle {{ font-weight: 500; font-size: 14px; }}
.card {{ background: {sv}; border-radius: 16px; padding: 4px; }}
row.snap {{ padding: 10px 12px; border-radius: 12px; background: transparent; }}
.sdesc {{ font-size: 14px; font-weight: 500; }}
.smeta {{ font-size: 12px; color: {osv}; }}
.chip {{ font-size: 11px; border-radius: 8px; padding: 2px 8px; background: alpha({a}, 0.12); color: {a}; }}
.chip.cur {{ background: {a}; color: {s}; }}
button.pill {{ border-radius: 18px; padding: 6px 16px; background: {a}; color: {s}; border: none; box-shadow: none; font-weight: 500; }}
button.flat2 {{ border-radius: 18px; padding: 6px 14px; background: transparent; color: {a}; border: 1px solid alpha({osv}, 0.4); box-shadow: none; font-weight: 500; }}
button.flat2:hover {{ background: alpha({a}, 0.08); }}
.empty {{ color: {osv}; padding: 30px; }}
.toast {{ background: #303134; color: #f1f3f4; border-radius: 8px; padding: 10px 16px; }}
"#, s = g("SURFACE"), sv = g("SURFACE_VARIANT"), os = g("ON_SURFACE"), osv = g("ON_SURFACE_VARIANT"), a = g("ACCENT"),
        ac = g("ACCENT_CONTAINER"), oac = g("ON_ACCENT_CONTAINER"))
}

struct App { win: gtk::ApplicationWindow, snaps: gtk::Box, settings: gtk::Box, banners: gtk::Box, toast: gtk::Revealer, toast_l: gtk::Label, st: Value, busy: bool }
type A = Rc<RefCell<App>>;

fn lbl(t: &str, cls: &str) -> gtk::Label { let l = gtk::Label::builder().label(t).xalign(0.0).wrap(true).build(); if !cls.is_empty() { l.add_css_class(cls); } l }
fn clear(b: &gtk::Box) { while let Some(c) = b.first_child() { b.remove(&c); } }
fn toast(a: &A, t: &str) {
    let (r, l) = { let x = a.borrow(); (x.toast.clone(), x.toast_l.clone()) };
    l.set_label(t); r.set_reveal_child(true);
    glib::timeout_add_seconds_local_once(4, move || r.set_reveal_child(false));
}
/// Run a helper command off the main thread, then refresh.
fn act(a: &A, args: Vec<String>, done: impl FnOnce(&A, Result<Value, String>) + 'static) {
    if a.borrow().busy { return; } a.borrow_mut().busy = true;
    let a = a.clone();
    glib::spawn_future_local(async move {
        let r = gio::spawn_blocking(move || helper(&args)).await.unwrap_or_else(|_| Err("helper gecrasht".into()));
        a.borrow_mut().busy = false;
        done(&a, r);
        refresh(&a);
    });
}
fn refresh(a: &A) {
    let a = a.clone();
    glib::spawn_future_local(async move {
        let st = gio::spawn_blocking(status).await.unwrap_or_else(|_| unavailable("helper gecrasht"));
        a.borrow_mut().st = st; render(&a);
    });
}

fn dialog(a: &A, title: &str, body: &str, ok: &str, on_ok: impl Fn() + 'static) {
    let parent = a.borrow().win.clone();
    let d = gtk::Window::builder().transient_for(&parent).modal(true).resizable(false).default_width(440).title(title).build();
    d.add_css_class("sh");
    let v = gtk::Box::new(gtk::Orientation::Vertical, 12); v.set_margin_top(22); v.set_margin_bottom(18); v.set_margin_start(24); v.set_margin_end(24);
    v.append(&lbl(title, "title"));
    let b = lbl(body, "sub"); b.set_max_width_chars(50); v.append(&b);
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_halign(gtk::Align::End); row.set_margin_top(8);
    let c = gtk::Button::with_label("Annuleren"); c.add_css_class("flat2");
    let o = gtk::Button::with_label(ok); o.add_css_class("pill");
    row.append(&c); row.append(&o); v.append(&row); d.set_child(Some(&v));
    let d1 = d.clone(); c.connect_clicked(move |_| d1.close());
    let d2 = d.clone(); o.connect_clicked(move |_| { d2.close(); on_ok(); });
    d.present();
}
fn reboot_prompt(a: &A, what: &str) {
    let a2 = a.clone();
    dialog(a, "Opnieuw opstarten?", &format!("{what} Start de computer opnieuw op om de herstelde versie te gebruiken. Je huidige versie wordt bewaard als reservekopie."),
           "Nu opnieuw opstarten", move || act(&a2, vec!["reboot".into()], |a, r| if let Err(e) = r { toast(a, &e) }));
}
fn rollback(a: &A, n: i64, desc: String, permanent: bool) {
    let a2 = a.clone();
    let (title, body) = if permanent {
        ("Deze versie vast maken?".to_string(), format!("De versie die je nu gebruikt (herstelpunt {n}: {desc}) wordt na een herstart je normale systeem. Je persoonlijke bestanden blijven ongewijzigd."))
    } else {
        ("Herstellen naar deze versie?".to_string(), format!("Het systeem gaat terug naar herstelpunt {n}: {desc}. Apps en systeeminstellingen worden teruggezet; je persoonlijke bestanden blijven ongewijzigd. De huidige versie wordt bewaard als reservekopie."))
    };
    dialog(a, &title, &body, if permanent { "Vast maken" } else { "Herstellen" }, move || {
        act(&a2, vec!["rollback".into(), n.to_string()], move |a, r| match r {
            Ok(_) => reboot_prompt(a, &format!("Herstelpunt {n} is klaargezet.")),
            Err(e) => toast(a, &format!("Herstellen mislukt: {e}")),
        });
    });
}
fn banner(title: &str, body: &str, warn: bool, btn: Option<(&str, Box<dyn Fn()>)>) -> gtk::Box {
    let b = gtk::Box::new(gtk::Orientation::Horizontal, 12); b.add_css_class("banner"); if warn { b.add_css_class("warn"); }
    let v = gtk::Box::new(gtk::Orientation::Vertical, 2); v.set_hexpand(true);
    v.append(&lbl(title, "btitle")); v.append(&lbl(body, "")); b.append(&v);
    if let Some((t, f)) = btn { let x = gtk::Button::with_label(t); x.add_css_class("pill"); x.set_valign(gtk::Align::Center); x.connect_clicked(move |_| f()); b.append(&x); }
    b
}
fn setting_row(title: &str, sub: &str, w: &gtk::Widget) -> gtk::ListBoxRow {
    let r = gtk::ListBoxRow::new(); r.add_css_class("snap"); r.set_activatable(false);
    let h = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    let v = gtk::Box::new(gtk::Orientation::Vertical, 3); v.set_hexpand(true);
    v.append(&lbl(title, "sdesc")); v.append(&lbl(sub, "smeta")); h.append(&v);
    w.set_valign(gtk::Align::Center); h.append(w); r.set_child(Some(&h)); r
}

fn render(a: &A) {
    let (snaps, settings, banners, st) = { let x = a.borrow(); (x.snaps.clone(), x.settings.clone(), x.banners.clone(), x.st.clone()) };
    clear(&snaps); clear(&settings); clear(&banners);
    if !st["available"].as_bool().unwrap_or(false) {
        let v = gtk::Box::new(gtk::Orientation::Vertical, 10); v.set_valign(gtk::Align::Center); v.set_vexpand(true); v.add_css_class("empty");
        let i = gtk::Image::from_icon_name("drive-harddisk-symbolic"); i.set_pixel_size(64); v.append(&i);
        for (t, c) in [("SafeHarbor is hier niet beschikbaar", "title"), (st["reason"].as_str().unwrap_or(""), "sub"),
                       ("Herstelpunten werken zodra Polder OS is geïnstalleerd op een btrfs-schijf met de SafeHarbor-indeling.", "sub")] {
            let l = lbl(t, c); l.set_xalign(0.5); l.set_justify(gtk::Justification::Center); l.set_max_width_chars(56); v.append(&l);
        }
        snaps.append(&v);
        settings.append(&lbl("Instellingen zijn pas beschikbaar als SafeHarbor actief is.", "sub"));
        return;
    }
    let list = st["snapshots"].as_array().cloned().unwrap_or_default();
    let booted = st["booted_snapshot"].as_i64();
    if let Some(n) = booted {
        let desc = list.iter().find(|s| s["number"].as_i64() == Some(n)).and_then(|s| s["description"].as_str()).unwrap_or("").to_string();
        let a2 = a.clone();
        banners.append(&banner(&format!("Je gebruikt een eerdere versie (herstelpunt {n})"),
            "Deze versie is alleen-lezen: wijzigingen verdwijnen bij een herstart. Werkt alles weer? Maak er dan je vaste versie van.", false,
            Some(("Maak dit de vaste versie", Box::new(move || rollback(&a2, n, desc.clone(), true))))));
    }
    if st["failed_boot"].is_object() {
        let a2 = a.clone();
        banners.append(&banner("Het vorige opstarten is niet gelukt",
            "Polder OS is de vorige keer niet volledig opgestart. Herstel hieronder een eerdere versie, of kies bij het opstarten ‘eerdere versies’ in het menu.", true,
            Some(("Begrepen", Box::new(move || act(&a2, vec!["ack-failed-boot".into()], |_, _| {}))))));
    }
    let fresh = st["rolled_back"]["time"].as_f64().map(|t| glib::real_time() as f64 / 1e6 - t < 3.0 * 86400.0).unwrap_or(false);
    if let (Some(rb), None, true) = (st["rolled_back"].as_object(), booted, fresh) {   // shown for 3 days after a rollback
        let n = rb.get("number").and_then(|v| v.as_i64()).unwrap_or(0);
        let d = rb.get("description").and_then(|v| v.as_str()).unwrap_or("");
        banners.append(&banner(&format!("Hersteld naar herstelpunt {n}"), &format!("{d}. De vorige versie is bewaard als reservekopie."), false, None));
    }
    // ---- Herstelpunten
    let head = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let ht = lbl(&format!("{} herstelpunten", list.len()), "sub"); ht.set_hexpand(true); head.append(&ht);
    let mk = gtk::Button::with_label("Nu herstelpunt maken"); mk.add_css_class("flat2");
    let a2 = a.clone(); mk.connect_clicked(move |_| act(&a2, vec!["create".into(), "Handmatig herstelpunt".into()], |a, r| match r {
        Ok(v) => toast(a, &format!("Herstelpunt {} gemaakt", v["number"])), Err(e) => toast(a, &e) }));
    if booted.is_some() { mk.set_sensitive(false); }
    head.append(&mk); snaps.append(&head);
    if list.is_empty() { snaps.append(&lbl("Nog geen herstelpunten. Vóór elke software-update wordt er automatisch een gemaakt.", "empty")); }
    let card = gtk::ListBox::new(); card.add_css_class("card"); card.set_selection_mode(gtk::SelectionMode::None);
    let rolled = st["rolled_back"]["number"].as_i64();
    for s in list.iter().rev() {
        let n = s["number"].as_i64().unwrap_or(0);
        let desc = s["description"].as_str().filter(|d| !d.is_empty()).unwrap_or("Herstelpunt").to_string();
        let row = gtk::ListBoxRow::new(); row.add_css_class("snap"); row.set_activatable(false);
        let h = gtk::Box::new(gtk::Orientation::Horizontal, 12);
        let v = gtk::Box::new(gtk::Orientation::Vertical, 3); v.set_hexpand(true);
        let top = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        top.append(&lbl(&desc, "sdesc"));
        if booted == Some(n) { let c = lbl("Nu in gebruik", "chip"); c.add_css_class("cur"); top.append(&c); }
        else if booted.is_none() && rolled == Some(n) { top.append(&lbl("Hersteld", "chip")); }
        if ud(s, "important") == "yes" { top.append(&lbl("Polder-update", "chip")); }
        v.append(&top);
        let meta = format!("{}  ·  {}  ·  #{n}", nl_date(s["date"].as_str().unwrap_or("")), origin(s));
        let m = lbl(&meta, "smeta"); m.set_wrap(false); m.set_ellipsize(gtk::pango::EllipsizeMode::End); v.append(&m);
        h.append(&v);
        if booted != Some(n) {
            let b = gtk::Button::with_label("Herstel naar deze versie"); b.add_css_class("flat2"); b.set_valign(gtk::Align::Center);
            let a2 = a.clone(); b.connect_clicked(move |_| rollback(&a2, n, desc.clone(), false));
            h.append(&b);
        }
        row.set_child(Some(&h)); card.append(&row);
    }
    if !list.is_empty() { snaps.append(&gtk::ScrolledWindow::builder().vexpand(true).hscrollbar_policy(gtk::PolicyType::Never).child(&card).build()); }
    // ---- Instellingen
    let card = gtk::ListBox::new(); card.add_css_class("card"); card.set_selection_mode(gtk::SelectionMode::None);
    let sw = gtk::Switch::new(); sw.set_active(st["auto"].as_bool().unwrap_or(true));
    let a2 = a.clone(); sw.connect_state_set(move |_, on| {
        act(&a2, vec!["set-auto".into(), if on { "on" } else { "off" }.into()], move |a, r| match r {
            Ok(_) => toast(a, if on { "Automatische herstelpunten staan aan" } else { "Automatische herstelpunten staan uit" }), Err(e) => toast(a, &e) });
        glib::Propagation::Proceed });
    card.append(&setting_row("Herstelpunt vóór elke update", "Ook bij automatische updates en Polder-updates, met een tweede punt erna.", sw.upcast_ref()));
    let ret = st["retention"].as_i64().unwrap_or(10);
    let sp = gtk::SpinButton::with_range(2.0, 50.0, 1.0); sp.set_value(ret as f64);
    let a2 = a.clone(); sp.connect_value_changed(move |s| {
        let n = s.value_as_int(); let a3 = a2.clone(); let s2 = s.clone();
        glib::timeout_add_local_once(std::time::Duration::from_millis(700), move || if s2.value_as_int() == n {
            act(&a3, vec!["set-retention".into(), n.to_string()], move |a, r| match r { Ok(_) => toast(a, &format!("Maximaal {n} herstelpunten bewaren")), Err(e) => toast(a, &e) }) });
    });
    card.append(&setting_row("Aantal herstelpunten bewaren", &format!("Oudere punten worden automatisch opgeruimd; punten vóór Polder-updates: maximaal {}.", (ret / 2).max(2)), sp.upcast_ref()));
    settings.append(&card);
    settings.append(&lbl("Elk herstelpunt staat ook in het opstartmenu onder ‘Polder OS - eerdere versies (SafeHarbor)’. Start de computer niet meer goed op? Kies daar een eerdere versie.", "smeta"));
    settings.append(&lbl("Je thuismap (@home) wordt nooit teruggezet: herstellen raakt alleen het systeem.", "smeta"));
}

fn build(app: &gtk::Application, page: &str) -> A {
    let prov = gtk::CssProvider::new();
    #[allow(deprecated)] prov.load_from_data(&css(&theme::palette()));
    gtk::style_context_add_provider_for_display(&gtk::gdk::Display::default().unwrap(), &prov, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    let win = gtk::ApplicationWindow::builder().application(app).title("SafeHarbor").default_width(780).default_height(540).build();
    win.add_css_class("sh");
    let ov = gtk::Overlay::new();
    let root = gtk::Box::new(gtk::Orientation::Vertical, 14); root.set_margin_top(20); root.set_margin_bottom(16); root.set_margin_start(24); root.set_margin_end(24);
    let hd = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    let ic = gtk::Image::from_icon_name("document-revert-symbolic"); ic.set_pixel_size(32); hd.append(&ic);
    let tv = gtk::Box::new(gtk::Orientation::Vertical, 0); tv.set_hexpand(true);
    tv.append(&lbl("SafeHarbor", "title")); tv.append(&lbl("Herstelpunten van je systeem. Ging er iets mis na een update? Zet een eerdere versie terug.", "sub"));
    hd.append(&tv); root.append(&hd);
    let banners = gtk::Box::new(gtk::Orientation::Vertical, 8); root.append(&banners);
    let stack = gtk::Stack::new(); stack.set_vexpand(true);
    let snaps = gtk::Box::new(gtk::Orientation::Vertical, 10);
    let settings = gtk::Box::new(gtk::Orientation::Vertical, 12);
    stack.add_titled(&snaps, Some("snapshots"), "Herstelpunten"); stack.add_titled(&settings, Some("settings"), "Instellingen");
    let ss = gtk::StackSwitcher::new(); ss.set_stack(Some(&stack)); ss.set_halign(gtk::Align::Start);
    root.append(&ss); root.append(&stack);
    if page == "settings" { stack.set_visible_child_name("settings"); }
    ov.set_child(Some(&root));
    let toast_l = lbl("", "toast");
    let toast = gtk::Revealer::builder().child(&toast_l).halign(gtk::Align::Center).valign(gtk::Align::End).margin_bottom(20).build();
    ov.add_overlay(&toast); win.set_child(Some(&ov));
    let a = Rc::new(RefCell::new(App { win: win.clone(), snaps, settings, banners, toast, toast_l, st: Value::Null, busy: false }));
    win.present(); refresh(&a);
    a
}

/// Session autostart: notifications only.
fn check() {
    let st = status();
    if !st["available"].as_bool().unwrap_or(false) { return; }
    let note = |t: &str, b: &str| { let _ = std::process::Command::new("notify-send").args(["-a", "SafeHarbor", "-i", "document-revert-symbolic", t, b]).status(); };
    if st["failed_boot"].is_object() { note("Het vorige opstarten is niet gelukt", "Open SafeHarbor om een eerdere versie te herstellen."); }
    if let Some(n) = st["booted_snapshot"].as_i64() {
        note(&format!("Je gebruikt een eerdere versie (herstelpunt {n})"), "Alleen-lezen. Open SafeHarbor en kies ‘Maak dit de vaste versie’ als alles werkt.");
    } else if let Some(t) = st["rolled_back"]["time"].as_f64() {
        let seen = std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".cache/osb/safeharbor-seen");
        if std::fs::read_to_string(&seen).ok().and_then(|s| s.trim().parse::<f64>().ok()) != Some(t) {
            note(&format!("Hersteld naar herstelpunt {}", st["rolled_back"]["number"]), st["rolled_back"]["description"].as_str().unwrap_or(""));
            if let Some(d) = seen.parent() { let _ = std::fs::create_dir_all(d); }
            let _ = std::fs::write(&seen, t.to_string());
        }
    }
}

fn main() -> glib::ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--check") { check(); return glib::ExitCode::SUCCESS; }
    if args.iter().any(|a| a == "--status") { println!("{}", status()); return glib::ExitCode::SUCCESS; }
    let page = if args.iter().any(|a| a == "--settings") { "settings" } else { "snapshots" }.to_string();
    let app = gtk::Application::new(Some("nl.polderos.SafeHarbor"), gio::ApplicationFlags::empty());
    let keep: Rc<RefCell<Option<A>>> = Rc::new(RefCell::new(None)); let k = keep.clone();
    app.connect_activate(move |ap| {
        if let Some(a) = k.borrow().as_ref() { a.borrow().win.present(); return; }
        *k.borrow_mut() = Some(build(ap, &page));
    });
    app.run_with_args::<&str>(&[])
}
