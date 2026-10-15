#![allow(dead_code)]
//! Polder SafeHarbor: herstelpunten (btrfs + snapper) bekijken, maken en terugzetten.
//! All privileged work goes through the polkit helper (safeharbor/helper/polder-safeharbor-helper); the command used
//! is $POLDER_SAFEHARBOR_HELPER (default: pkexec /usr/libexec/polder-safeharbor-helper).
//! `polder-safeharbor --check` (session autostart) only sends notifications: failed previous boot, running from a
//! read-only snapshot, finished rollback. On non-btrfs systems (live ISO) the window shows a "niet beschikbaar" state.
//! `--settings` opens the Instellingen tab, `--status` prints the helper status JSON.
#[path = "../i18n.rs"] #[macro_use] mod i18n;
#[allow(unused_imports)] use i18n::tr;
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
    let Some((cmd, rest)) = a.split_first() else { return Err(tr("no helper configured").into()) };
    match std::process::Command::new(cmd).args(rest).output() {
        Err(e) => Err(format!("helper niet gevonden: {e}")),
        Ok(o) if o.status.success() => serde_json::from_slice(&o.stdout).map_err(|e| format!("onleesbaar antwoord: {e}")),
        Ok(o) => {
            let e = String::from_utf8_lossy(&o.stderr).trim().to_string();
            Err(match o.status.code() {
                Some(126) | Some(127) if e.is_empty() || e.contains("dismissed") || e.contains("Not authorized") => tr("Permission not granted.").into(),
                _ => if e.is_empty() { tr("Something went wrong.").into() } else { e.lines().last().unwrap_or("").to_string() },
            })
        }
    }
}
fn unavailable(reason: &str) -> Value { serde_json::json!({"available": false, "reason": reason, "snapshots": []}) }
fn status() -> Value {
    if std::env::var("POLDER_SAFEHARBOR_HELPER").is_err() && !std::path::Path::new(HELPER).exists() {
        return unavailable(tr("SafeHarbor is not installed on this system."));
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
/// Snapshot descriptions written by the apt hook are stored in Dutch; rebuild them from the userdata in the UI language.
fn desc_label(s: &Value) -> String {
    let d = s["description"].as_str().unwrap_or("").to_string();
    if ud(s, "polder") != "apt" { return d; }
    let num = |k: &str| ud(s, k).parse::<u64>().unwrap_or(0);
    let (n, i, u, r) = (num("packages"), num("installed"), num("upgraded"), num("removed"));
    let (auto, pol) = (ud(s, "trigger") == "unattended-upgrades", ud(s, "important") == "yes");
    let what = if u > 0 { match (auto, pol) { (true, true) => tr("Before automatic Polder update"), (false, true) => tr("Before Polder update"),
                                              (true, false) => tr("Before automatic update"), _ => tr("Before update") } }
        else if i > 0 && r == 0 { if auto { tr("Before automatic installation") } else { tr("Before installation") } }
        else if r > 0 && i == 0 { if auto { tr("Before automatic removal") } else { tr("Before removal") } }
        else if auto { tr("Before automatic change") } else { tr("Before change") };
    format!("{what}: {}", i18n::fmt(i18n::trn("{} package", "{} packages", n), &[&n], &[]))
}
fn origin(s: &Value) -> &'static str {
    match (ud(s, "polder"), ud(s, "trigger")) {
        ("apt", "unattended-upgrades") => tr("Automatic update"),
        ("apt", _) => tr("Software change"),
        ("manual", _) => tr("Manual"),
        _ => match s["type"].as_str() {
            Some("pre") | Some("post") => tr("Software change"),
            _ => if s["cleanup"].as_str() == Some("timeline") { tr("Timeline") } else { tr("Manual") },
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
        let r = gio::spawn_blocking(move || helper(&args)).await.unwrap_or_else(|_| Err(tr("helper crashed").into()));
        a.borrow_mut().busy = false;
        done(&a, r);
        refresh(&a);
    });
}
fn refresh(a: &A) {
    let a = a.clone();
    glib::spawn_future_local(async move {
        let st = gio::spawn_blocking(status).await.unwrap_or_else(|_| unavailable(tr("helper crashed")));
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
    let c = gtk::Button::with_label(tr("Cancel")); c.add_css_class("flat2");
    let o = gtk::Button::with_label(ok); o.add_css_class("pill");
    row.append(&c); row.append(&o); v.append(&row); d.set_child(Some(&v));
    let d1 = d.clone(); c.connect_clicked(move |_| d1.close());
    let d2 = d.clone(); o.connect_clicked(move |_| { d2.close(); on_ok(); });
    d.present();
}
fn reboot_prompt(a: &A, what: &str) {
    let a2 = a.clone();
    dialog(a, tr("Restart?"), &tf!("{what} Restart the computer to use the restored version. Your current version is kept as a backup." ; what),
           tr("Restart now"), move || act(&a2, vec!["reboot".into()], |a, r| if let Err(e) = r { toast(a, &e) }));
}
fn rollback(a: &A, n: i64, desc: String, permanent: bool) {
    let a2 = a.clone();
    let (title, body) = if permanent {
        (tr("Make this version permanent?").to_string(), tf!("The version you are using now (restore point {n}: {desc}) becomes your normal system after a restart. Your personal files stay unchanged." ; n, desc))
    } else {
        (tr("Restore to this version?").to_string(), tf!("The system goes back to restore point {n}: {desc}. Apps and system settings are restored; your personal files stay unchanged. The current version is kept as a backup." ; n, desc))
    };
    dialog(a, &title, &body, if permanent { tr("Make permanent") } else { tr("Restore") }, move || {
        act(&a2, vec!["rollback".into(), n.to_string()], move |a, r| match r {
            Ok(_) => reboot_prompt(a, &tf!("Restore point {n} is ready." ; n)),
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
        for (t, c) in [(tr("SafeHarbor is not available here"), "title"), (st["reason"].as_str().unwrap_or(""), "sub"),
                       (tr("Restore points work once Polder OS is installed on a btrfs disk with the SafeHarbor layout."), "sub")] {
            let l = lbl(t, c); l.set_xalign(0.5); l.set_justify(gtk::Justification::Center); l.set_max_width_chars(56); v.append(&l);
        }
        snaps.append(&v);
        settings.append(&lbl(tr("Settings are only available when SafeHarbor is active."), "sub"));
        return;
    }
    let list = st["snapshots"].as_array().cloned().unwrap_or_default();
    let booted = st["booted_snapshot"].as_i64();
    if let Some(n) = booted {
        let desc = list.iter().find(|s| s["number"].as_i64() == Some(n)).map(desc_label).unwrap_or_default();
        let a2 = a.clone();
        banners.append(&banner(&tf!("You are using an earlier version (restore point {n})" ; n),
            tr("This version is read-only: changes disappear on restart. Does everything work again? Then make it your permanent version."), false,
            Some((tr("Make this the permanent version"), Box::new(move || rollback(&a2, n, desc.clone(), true))))));
    }
    if st["failed_boot"].is_object() {
        let a2 = a.clone();
        banners.append(&banner(tr("The previous boot did not succeed"),
            tr("Polder OS did not start up completely last time. Restore an earlier version below, or choose ‘earlier versions’ in the boot menu."), true,
            Some((tr("Got it"), Box::new(move || act(&a2, vec!["ack-failed-boot".into()], |_, _| {}))))));
    }
    let fresh = st["rolled_back"]["time"].as_f64().map(|t| glib::real_time() as f64 / 1e6 - t < 3.0 * 86400.0).unwrap_or(false);
    if let (Some(rb), None, true) = (st["rolled_back"].as_object(), booted, fresh) {   // shown for 3 days after a rollback
        let n = rb.get("number").and_then(|v| v.as_i64()).unwrap_or(0);
        let d = rb.get("description").and_then(|v| v.as_str()).unwrap_or("");
        banners.append(&banner(&format!("Hersteld naar herstelpunt {n}"), &tf!("{d}. The previous version is kept as a backup." ; d), false, None));
    }
    // ---- Herstelpunten
    let head = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let ht = lbl(&tf!("{} restore points", list.len()), "sub"); ht.set_hexpand(true); head.append(&ht);
    let mk = gtk::Button::with_label(tr("Create restore point now")); mk.add_css_class("flat2");
    let a2 = a.clone(); mk.connect_clicked(move |_| act(&a2, vec!["create".into(), tr("Manual restore point").into()], |a, r| match r {
        Ok(v) => toast(a, &tf!("Restore point {} created", v["number"])), Err(e) => toast(a, &e) }));
    if booted.is_some() { mk.set_sensitive(false); }
    head.append(&mk); snaps.append(&head);
    if list.is_empty() { snaps.append(&lbl(tr("No restore points yet. One is created automatically before every software update."), "empty")); }
    let card = gtk::ListBox::new(); card.add_css_class("card"); card.set_selection_mode(gtk::SelectionMode::None);
    let rolled = st["rolled_back"]["number"].as_i64();
    for s in list.iter().rev() {
        let n = s["number"].as_i64().unwrap_or(0);
        let desc = Some(desc_label(s)).filter(|d| !d.is_empty()).unwrap_or(tr("Restore point").to_string());
        let row = gtk::ListBoxRow::new(); row.add_css_class("snap"); row.set_activatable(false);
        let h = gtk::Box::new(gtk::Orientation::Horizontal, 12);
        let v = gtk::Box::new(gtk::Orientation::Vertical, 3); v.set_hexpand(true);
        let top = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        top.append(&lbl(&desc, "sdesc"));
        if booted == Some(n) { let c = lbl(tr("In use now"), "chip"); c.add_css_class("cur"); top.append(&c); }
        else if booted.is_none() && rolled == Some(n) { top.append(&lbl(tr("Restored"), "chip")); }
        if ud(s, "important") == "yes" { top.append(&lbl(tr("Polder update"), "chip")); }
        v.append(&top);
        let meta = format!("{}  ·  {}  ·  #{n}", nl_date(s["date"].as_str().unwrap_or("")), origin(s));
        let m = lbl(&meta, "smeta"); m.set_wrap(false); m.set_ellipsize(gtk::pango::EllipsizeMode::End); v.append(&m);
        h.append(&v);
        if booted != Some(n) {
            let b = gtk::Button::with_label(tr("Restore to this version")); b.add_css_class("flat2"); b.set_valign(gtk::Align::Center);
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
            Ok(_) => toast(a, if on { tr("Automatic restore points are on") } else { tr("Automatic restore points are off") }), Err(e) => toast(a, &e) });
        glib::Propagation::Proceed });
    card.append(&setting_row(tr("Restore point before every update"), tr("Also for automatic updates and Polder updates, with a second point afterwards."), sw.upcast_ref()));
    let ret = st["retention"].as_i64().unwrap_or(10);
    let sp = gtk::SpinButton::with_range(2.0, 50.0, 1.0); sp.set_value(ret as f64);
    let a2 = a.clone(); sp.connect_value_changed(move |s| {
        let n = s.value_as_int(); let a3 = a2.clone(); let s2 = s.clone();
        glib::timeout_add_local_once(std::time::Duration::from_millis(700), move || if s2.value_as_int() == n {
            act(&a3, vec!["set-retention".into(), n.to_string()], move |a, r| match r { Ok(_) => toast(a, &tf!("Keep at most {n} restore points" ; n)), Err(e) => toast(a, &e) }) });
    });
    card.append(&setting_row(tr("Number of restore points to keep"), &tf!("Older points are cleaned up automatically; points before Polder updates: at most {}.", (ret / 2).max(2)), sp.upcast_ref()));
    settings.append(&card);
    settings.append(&lbl(tr("Every restore point is also listed in the boot menu under ‘Polder OS - earlier versions (SafeHarbor)’. Computer no longer starts properly? Choose an earlier version there."), "smeta"));
    settings.append(&lbl(tr("Your home folder (@home) is never restored: restoring only touches the system."), "smeta"));
}

fn build(app: &gtk::Application, page: &str) -> A {
    let prov = gtk::CssProvider::new();
    #[allow(deprecated)] prov.load_from_data(&css(&theme::palette()));
    gtk::style_context_add_provider_for_display(&gtk::gdk::Display::default().unwrap(), &prov, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    let win = gtk::ApplicationWindow::builder().application(app).title(tr("SafeHarbor")).default_width(780).default_height(540).build();
    win.add_css_class("sh");
    let ov = gtk::Overlay::new();
    let root = gtk::Box::new(gtk::Orientation::Vertical, 14); root.set_margin_top(20); root.set_margin_bottom(16); root.set_margin_start(24); root.set_margin_end(24);
    let hd = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    let ic = gtk::Image::from_icon_name("document-revert-symbolic"); ic.set_pixel_size(32); hd.append(&ic);
    let tv = gtk::Box::new(gtk::Orientation::Vertical, 0); tv.set_hexpand(true);
    tv.append(&lbl(tr("SafeHarbor"), "title")); tv.append(&lbl(tr("Restore points of your system. Did something go wrong after an update? Put back an earlier version."), "sub"));
    hd.append(&tv); root.append(&hd);
    let banners = gtk::Box::new(gtk::Orientation::Vertical, 8); root.append(&banners);
    let stack = gtk::Stack::new(); stack.set_vexpand(true);
    let snaps = gtk::Box::new(gtk::Orientation::Vertical, 10);
    let settings = gtk::Box::new(gtk::Orientation::Vertical, 12);
    stack.add_titled(&snaps, Some("snapshots"), tr("Restore points")); stack.add_titled(&settings, Some("settings"), tr("Settings"));
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
    let note = |t: &str, b: &str| { let _ = std::process::Command::new("notify-send").args(["-a", tr("SafeHarbor"), "-i", "document-revert-symbolic", t, b]).status(); };
    if st["failed_boot"].is_object() { note(tr("The previous boot did not succeed"), tr("Open SafeHarbor to restore an earlier version.")); }
    if let Some(n) = st["booted_snapshot"].as_i64() {
        note(&tf!("You are using an earlier version (restore point {n})" ; n), tr("Read-only. Open SafeHarbor and choose ‘Make this the permanent version’ if everything works."));
    } else if let Some(t) = st["rolled_back"]["time"].as_f64() {
        let seen = std::path::PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".cache/osb/safeharbor-seen");
        if std::fs::read_to_string(&seen).ok().and_then(|s| s.trim().parse::<f64>().ok()) != Some(t) {
            note(&tf!("Restored to restore point {}", st["rolled_back"]["number"]), st["rolled_back"]["description"].as_str().unwrap_or(""));
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
