#![allow(dead_code)]
//! Polder Sluis: proefpolders (copy-on-write branches) of a project folder. Pump a polder dry, experiment inside it,
//! compare with the vasteland (the original folder) and let only the chosen changes in through the sluis.
//! GUI on top of `polder-sluisd` (all work happens there; JSON over stdout). `polder-sluis --new <map>` opens the
//! "Nieuwe proefpolder" dialog for a folder (Thunar: Openen in Sluis).
#[path = "../i18n.rs"] #[macro_use] mod i18n;
#[allow(unused_imports)] use i18n::tr;
#[path = "../theme.rs"] mod theme;
use gtk::{gio, glib, pango, prelude::*};
use serde_json::{json, Value};
use std::{cell::{Cell, RefCell}, io::{Read, Seek, SeekFrom}, rc::Rc};

fn sluisd() -> String {
    if let Ok(p) = std::env::var("POLDER_SLUISD") { return p; }
    if let Ok(e) = std::env::current_exe() { let s = e.with_file_name("polder-sluisd"); if s.exists() { return s.to_string_lossy().into(); } }
    "polder-sluisd".into()
}
fn call(args: &[String]) -> Value {
    match std::process::Command::new(sluisd()).args(args).output() {
        Ok(o) => serde_json::from_slice(&o.stdout).unwrap_or_else(|_| json!({"ok": false, "error": String::from_utf8_lossy(&o.stderr).trim().to_string()})),
        Err(e) => json!({"ok": false, "error": format!("polder-sluisd niet gevonden: {e}")}),
    }
}
fn err_of(v: &Value) -> Option<String> { if v["ok"] == json!(false) { Some(v["error"].as_str().unwrap_or(tr("Something went wrong.")).to_string()) } else { None } }
fn size_h(n: u64) -> String {
    let f = n as f64;
    if f < 1024.0 { format!("{n} B") } else if f < 1048576.0 { format!("{:.0} kB", f / 1024.0) } else if f < 1073741824.0 { format!("{:.1} MB", f / 1048576.0) } else { format!("{:.2} GB", f / 1073741824.0) }
}
fn date_h(t: i64) -> String {
    glib::DateTime::from_unix_local(t).ok().and_then(|d| d.format("%-d-%-m-%Y %H:%M").ok()).map(|s| s.to_string()).unwrap_or_default()
}
fn kind_nl(k: &str) -> &str { match k { "toegevoegd" => tr("New"), "gewijzigd" => tr("Modified"), "verwijderd" => tr("Deleted"), "rechten" => tr("Permissions"), "type" => tr("Type changed"), "hernoemd" => tr("Renamed"), x => x } }

fn css(p: &std::collections::HashMap<String, String>) -> String {
    let g = |k: &str| p.get(k).cloned().unwrap_or_default();
    format!(r#"
window.sl {{ background: {s}; color: {os}; font-family: Roboto; }}
.side {{ background: {sv}; padding: 14px 10px; }}
.h1 {{ font-size: 20px; font-weight: 500; }}
.h2 {{ font-size: 15px; font-weight: 500; }}
.sub {{ color: {osv}; font-size: 12px; }}
.tag {{ font-size: 11px; border-radius: 8px; padding: 1px 8px; background: alpha({a}, 0.12); color: {a}; }}
.tag.conflict, .tag.verwijderd {{ background: #fce8e6; color: #a50e0e; }}
.tag.toegevoegd {{ background: #e6f4ea; color: #137333; }}
.tag.arch {{ background: alpha({osv}, 0.15); color: {osv}; }}
list.polders, list.polders row {{ background: transparent; }}
list.polders row {{ border-radius: 12px; padding: 8px 10px; }}
list.polders row:selected {{ background: {ac}; color: {oac}; }}
.card {{ background: {sv}; border-radius: 14px; }}
list.changes {{ background: transparent; }}
list.changes row {{ padding: 4px 8px; border-radius: 10px; }}
list.changes row:selected {{ background: alpha({a}, 0.14); color: {os}; }}
.banner {{ background: {ac}; color: {oac}; border-radius: 12px; padding: 10px 14px; }}
.banner.warn {{ background: #fef7e0; color: #5f4200; }}
.banner.bad {{ background: #fce8e6; color: #5c1612; }}
button.pill {{ border-radius: 18px; padding: 6px 16px; background: {a}; color: {s}; border: none; box-shadow: none; font-weight: 500; }}
button.pill:disabled {{ background: alpha({osv}, 0.25); }}
button.flat2 {{ border-radius: 18px; padding: 5px 14px; background: transparent; color: {a}; border: 1px solid alpha({osv}, 0.4); box-shadow: none; font-weight: 500; }}
button.danger {{ color: #b3261e; }}
textview.diff, textview.diff text {{ font-family: monospace; font-size: 11px; background: {s}; }}
.difftitle {{ font-size: 12px; font-weight: 500; color: {osv}; padding: 4px 6px; }}
.toast {{ background: #303134; color: #f1f3f4; border-radius: 8px; padding: 10px 16px; }}
"#, s = g("SURFACE"), sv = g("SURFACE_VARIANT"), os = g("ON_SURFACE"), osv = g("ON_SURFACE_VARIANT"), a = g("ACCENT"),
        ac = g("ACCENT_CONTAINER"), oac = g("ON_ACCENT_CONTAINER"))
}

struct App {
    win: gtk::ApplicationWindow, plist: gtk::ListBox, detail: gtk::Box, toast: gtk::Revealer, toast_l: gtk::Label,
    polders: Vec<Value>, cur: Option<String>, changes: Value, selected: std::collections::BTreeSet<String>,
    force: std::collections::BTreeSet<String>, diff: gtk::Box, busy: bool,
    generation: u64, sessions: Vec<Session>, session_status: gtk::Label, allow_close: bool, close_prompt: bool,
}
type A = Rc<RefCell<App>>;

struct Session {
    child: std::process::Child, id: String, output: std::fs::File, wait_error_shown: bool,
}

fn next_generation(a: &A) -> u64 { let mut x = a.borrow_mut(); x.generation += 1; x.generation }
fn choose(a: &A, id: Option<String>) {
    let detail = {
        let mut x = a.borrow_mut();
        if x.cur == id { return; }
        x.selected.clear(); x.force.clear(); x.cur = id;
        x.detail.clone()
    };
    clear(&detail); detail.append(&lbl(tr("Loading changes…"), "sub"));
}

fn update_session_status(a: &A) {
    let x = a.borrow();
    x.session_status.set_label(&tf!("Running terminals: {}", x.sessions.len()));
}

/// Keep launch diagnostics private without leaving temporary files behind after a crash.
fn session_output() -> std::io::Result<std::fs::File> {
    use std::os::unix::fs::OpenOptionsExt;
    static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    loop {
        let p = std::env::temp_dir().join(format!("polder-sluis-{}-{}.log", std::process::id(), SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        match std::fs::OpenOptions::new().read(true).write(true).create_new(true).mode(0o600).open(&p) {
            Ok(f) => { std::fs::remove_file(p)?; return Ok(f); }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
}

fn start_terminal(a: &A, id: &str) {
    let launch = (|| -> std::io::Result<Session> {
        let output = session_output()?;
        let child = std::process::Command::new(sluisd()).args(["run", id, "--terminal"])
            .stdin(std::process::Stdio::null()).stdout(output.try_clone()?).stderr(output.try_clone()?).spawn()?;
        Ok(Session { child, id: id.into(), output, wait_error_shown: false })
    })();
    match launch {
        Ok(s) => { a.borrow_mut().sessions.push(s); update_session_status(a); toast(a, tr("Starting terminal in the test polder…")); }
        Err(e) => toast(a, &tf!("Could not start the terminal: {}", e)),
    }
}

fn session_failure(output: &str) -> String {
    let text = output.trim();
    if let Ok(v) = serde_json::from_str::<Value>(text) { if let Some(e) = err_of(&v) { return e; } }
    if text.is_empty() { tr("The terminal stopped unexpectedly.").into() } else { text.chars().take(1000).collect() }
}

fn poll_sessions(a: &A) {
    let mut completed = vec![];
    let mut errors = vec![];
    {
        let mut x = a.borrow_mut();
        for n in (0..x.sessions.len()).rev() {
            match x.sessions[n].child.try_wait() {
                Ok(Some(status)) => completed.push((x.sessions.remove(n), status)),
                Ok(None) => {},
                Err(e) if !x.sessions[n].wait_error_shown => {
                    x.sessions[n].wait_error_shown = true;
                    errors.push(tf!("Could not check the terminal: {}", e));
                }
                Err(_) => {},
            }
        }
    }
    for e in errors { toast(a, &e); }
    if completed.is_empty() { return; }
    update_session_status(a);
    for (mut session, status) in completed {
        if !status.success() {
            let mut output = String::new();
            let _ = session.output.seek(SeekFrom::Start(0));
            let _ = session.output.take(16 * 1024).read_to_string(&mut output);
            toast(a, &tf!("Terminal in ‘{}’: {}", session.id, session_failure(&output)));
        }
    }
    reload(a, None);
}

fn tilde(p: &str) -> String { let h = std::env::var("HOME").unwrap_or_default(); if !h.is_empty() && p.starts_with(&h) { format!("~{}", &p[h.len()..]) } else { p.to_string() } }
fn lbl(t: &str, cls: &str) -> gtk::Label { let l = gtk::Label::builder().label(t).xalign(0.0).wrap(!cls.split(' ').any(|c| c == "tag")).build(); l.set_wrap_mode(pango::WrapMode::WordChar); if !cls.is_empty() { for c in cls.split(' ') { l.add_css_class(c); } } l }
fn btn(t: &str, cls: &str) -> gtk::Button { let b = gtk::Button::with_label(t); for c in cls.split(' ') { if !c.is_empty() { b.add_css_class(c); } } b }
fn clear(b: &gtk::Box) { while let Some(c) = b.first_child() { b.remove(&c); } }
fn toast(a: &A, t: &str) {
    let (r, l) = { let x = a.borrow(); (x.toast.clone(), x.toast_l.clone()) };
    l.set_label(t); r.set_reveal_child(true);
    glib::timeout_add_seconds_local_once(5, move || r.set_reveal_child(false));
}
/// run polder-sluisd in a thread, then continue on the main loop
fn bg(a: &A, args: Vec<String>, done: impl FnOnce(&A, Value) + 'static) {
    let a = a.clone();
    glib::spawn_future_local(async move {
        let v = gio::spawn_blocking(move || call(&args)).await.unwrap_or(json!({"ok": false, "error": "crash"}));
        done(&a, v);
    });
}

fn dialog(a: &A, title: &str, body: &gtk::Widget, ok: &str, danger: bool, on_ok: impl Fn() + 'static) -> gtk::Window {
    let parent = a.borrow().win.clone();
    let d = gtk::Window::builder().transient_for(&parent).modal(true).resizable(false).default_width(500).title(title).build();
    d.add_css_class("sl");
    let v = gtk::Box::new(gtk::Orientation::Vertical, 12); v.set_margin_top(20); v.set_margin_bottom(16); v.set_margin_start(22); v.set_margin_end(22);
    v.append(&lbl(title, "h1")); v.append(body);
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_halign(gtk::Align::End); row.set_margin_top(6);
    let c = btn(tr("Cancel"), "flat2"); let o = btn(ok, if danger { "pill" } else { "pill" });
    row.append(&c); row.append(&o); v.append(&row); d.set_child(Some(&v));
    let d1 = d.clone(); c.connect_clicked(move |_| d1.close());
    let d2 = d.clone(); o.connect_clicked(move |_| { d2.close(); on_ok(); });
    d.present(); d
}

// ------------------------------------------------------------------ list + detail
fn reload(a: &A, select: Option<String>) {
    if select.is_some() { choose(a, select); }
    let generation = next_generation(a);
    bg(a, vec!["list".into()], move |a, v| {
        if a.borrow().generation != generation { return; }
        if let Some(e) = err_of(&v) { toast(a, &e); return; }
        let Some(polders) = v.as_array().cloned() else { toast(a, tr("Could not load the test polders.")); return; };
        let plist = a.borrow().plist.clone();
        while let Some(c) = plist.first_child() { plist.remove(&c); }
        for p in &polders {
            let r = gtk::ListBoxRow::new();
            let b = gtk::Box::new(gtk::Orientation::Vertical, 2);
            let top = gtk::Box::new(gtk::Orientation::Horizontal, 6);
            let n = lbl(p["meta"]["name"].as_str().unwrap_or(""), "h2"); n.set_hexpand(true); top.append(&n);
            b.append(&top);
            let st = p["status"].as_str().unwrap_or("");
            let t = lbl(&status_label(st), "tag"); if st == "Conflict" { t.add_css_class("conflict"); } if st == "Gearchiveerd" { t.add_css_class("arch"); }
            t.set_halign(gtk::Align::Start);
            let meta = gtk::Box::new(gtk::Orientation::Vertical, 3); meta.append(&t);
            meta.append(&lbl(&format!("{} wijz. · {}", p["changes"], size_h(p["usage"].as_u64().unwrap_or(0))), "sub"));
            b.append(&meta);
            r.set_child(Some(&b)); unsafe { r.set_data("id", p["meta"]["id"].as_str().unwrap_or("").to_string()); }
            plist.append(&r);
        }
        let want = a.borrow().cur.clone().filter(|w| polders.iter().any(|p| p["meta"]["id"].as_str() == Some(w)))
            .or_else(|| polders.first().and_then(|p| p["meta"]["id"].as_str().map(String::from)));
        a.borrow_mut().polders = polders.clone();
        if let Some(w) = want {
            let mut i = 0; while let Some(r) = plist.row_at_index(i) { if unsafe { r.data::<String>("id").map(|d| d.as_ref() == &w).unwrap_or(false) } { plist.select_row(Some(&r)); break; } i += 1; }
            open(a, &w);
        } else { choose(a, None); empty_state(a); }
    });
}
fn empty_state(a: &A) {
    let d = a.borrow().detail.clone(); clear(&d);
    let v = gtk::Box::new(gtk::Orientation::Vertical, 10); v.set_valign(gtk::Align::Center); v.set_vexpand(true); v.set_halign(gtk::Align::Center);
    let i = gtk::Image::from_icon_name("folder-new-symbolic"); i.set_pixel_size(64); v.append(&i);
    let t = lbl(tr("No test polders yet"), "h1"); t.set_xalign(0.5); v.append(&t);
    let s = lbl(tr("A test polder is a copy of a project folder where you can experiment freely. Your original folder, the mainland, stays untouched until you let changes through the lock."), "sub");
    s.set_justify(gtk::Justification::Center); s.set_max_width_chars(60); s.set_xalign(0.5); v.append(&s);
    let b = btn(tr("New test polder"), "pill"); b.set_halign(gtk::Align::Center); let a2 = a.clone(); b.connect_clicked(move |_| new_dialog(&a2, None)); v.append(&b);
    d.append(&v);
}
/// Engine status ids are stable (Dutch) strings; translate for display only.
fn status_label(st: &str) -> String { match st { "Actief" => tr("Active"), "Klaar om over te nemen" => tr("Ready to merge"), "Gearchiveerd" => tr("Archived"), "Conflict" => tr("Conflict"), x => x }.to_string() }
fn polder(a: &A, id: &str) -> Value { a.borrow().polders.iter().find(|p| p["meta"]["id"].as_str() == Some(id)).cloned().unwrap_or(Value::Null) }

fn open(a: &A, id: &str) {
    choose(a, Some(id.to_string()));
    let generation = next_generation(a);
    let id2 = id.to_string();
    bg(a, vec!["changes".into(), id.into()], move |a, v| {
        if a.borrow().generation != generation || a.borrow().cur.as_deref() != Some(&id2) { return; }
        {
            let mut x = a.borrow_mut();
            if let Some(changes) = v["changes"].as_array() {
                x.selected.retain(|p| changes.iter().any(|c| c["path"].as_str() == Some(p) && c["home"] != c["branch"]));
                let old = x.changes.clone();
                x.force.retain(|p| changes.iter().any(|c| c["path"].as_str() == Some(p) && c["conflict"] == true
                    && old["changes"].as_array().map(|cs| cs.iter().any(|o| o["path"] == c["path"] && o["home"] == c["home"] && o["branch"] == c["branch"])).unwrap_or(false)));
            }
            x.changes = v;
        }
        render(a, &id2);
    });
}

fn set_network(a: &A, id: &str, on: bool, sw: &gtk::Switch, updating: &Rc<Cell<bool>>) {
    let old = sw.state();
    sw.set_sensitive(false);
    let (sw, updating) = (sw.clone(), updating.clone());
    bg(a, vec!["network".into(), id.into(), if on { "on" } else { "off" }.into()], move |a, v| {
        let error = err_of(&v);
        let state = if error.is_some() { old } else { on };
        updating.set(true); sw.set_active(state); sw.set_state(state); updating.set(false);
        sw.set_sensitive(true);
        if let Some(e) = error { toast(a, &e); }
        else { toast(a, if on { tr("Internet is on for new programs in this test polder") } else { tr("Internet is off for new programs in this test polder") }); }
        reload(a, None);
    });
}

fn render(a: &A, id: &str) {
    let p = polder(a, id);
    let ch = a.borrow().changes.clone();
    let d = a.borrow().detail.clone(); clear(&d);
    let m = &p["meta"];
    let archived = m["archived"].as_bool().unwrap_or(false);
    // header
    let hd = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    let tv = gtk::Box::new(gtk::Orientation::Vertical, 2); tv.set_hexpand(true);
    tv.append(&lbl(m["name"].as_str().unwrap_or(""), "h1"));
    let desc = m["description"].as_str().unwrap_or("");
    tv.append(&lbl(&format!("Vasteland: {}  ·  gemaakt {}  ·  {} in gebruik{}", tilde(m["origin"].as_str().unwrap_or("")), date_h(m["created"].as_i64().unwrap_or(0)),
        size_h(p["usage"].as_u64().unwrap_or(0)), if desc.is_empty() { String::new() } else { format!("  ·  {desc}") }), "sub"));
    hd.append(&tv);
    let st = p["status"].as_str().unwrap_or(""); let t = lbl(&status_label(st), "tag"); t.set_valign(gtk::Align::Start); if st == "Conflict" { t.add_css_class("conflict"); } hd.append(&t);
    d.append(&hd);
    // actions
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let term = btn(tr("Terminal in the polder"), "pill"); term.set_sensitive(!archived);
    let a2 = a.clone(); let i2 = id.to_string(); term.connect_clicked(move |_| {
        start_terminal(&a2, &i2);
    });
    row.append(&term);
    let netl = lbl(tr("Internet"), "sub"); netl.set_wrap(false); netl.set_margin_start(8); row.append(&netl);
    let sw = gtk::Switch::new(); sw.set_active(m["network"].as_bool().unwrap_or(false)); sw.set_valign(gtk::Align::Center); sw.set_sensitive(!archived);
    sw.set_tooltip_text(Some(tr("Applies to newly started programs. Running programs keep their internet access.")));
    let updating = Rc::new(Cell::new(false));
    let a2 = a.clone(); let i2 = id.to_string();
    sw.connect_state_set(move |s, on| {
        if updating.get() { return glib::Propagation::Proceed; }
        // The active thumb follows the user gesture; restore it until persistence succeeds.
        let old = s.state();
        updating.set(true); s.set_active(old); updating.set(false);
        if !on { set_network(&a2, &i2, false, s, &updating); return glib::Propagation::Stop; }
        let body = lbl(tr("With internet, programs in the test polder can send data, download or do things online. Sluis cannot undo that: only files in your project folder stay in the polder. Only turn it on for programs you trust."), "sub");
        body.set_max_width_chars(56);
        let (a3, i3, s2, updating2) = (a2.clone(), i2.clone(), s.clone(), updating.clone());
        dialog(&a2, tr("Turn on internet in this test polder?"), body.upcast_ref(), tr("Turn on internet"), true, move || {
            set_network(&a3, &i3, true, &s2, &updating2);
        });
        glib::Propagation::Stop
    });
    row.append(&sw);
    let sp = gtk::Box::new(gtk::Orientation::Horizontal, 0); sp.set_hexpand(true); row.append(&sp);
    let arch = btn(if archived { tr("Unarchive") } else { tr("Archive") }, "flat2");
    let a2 = a.clone(); let i2 = id.to_string();
    arch.connect_clicked(move |_| { bg(&a2, vec![if archived { "unarchive" } else { "archive" }.into(), i2.clone()], move |a, v| {
        if let Some(e) = err_of(&v) { toast(a, &e) } else { toast(a, if archived { tr("Test polder is active again") } else { tr("Test polder archived") }); reload(a, None); } }); });
    row.append(&arch);
    let del = btn(tr("Discard"), "flat2 danger");
    let a2 = a.clone(); let i2 = id.to_string(); let name = m["name"].as_str().unwrap_or("").to_string();
    del.connect_clicked(move |_| {
        let body = lbl(&tf!("All changes in ‘{name}’ that you have not merged will be lost. Your original folder stays as it is." ; name), "sub"); body.set_max_width_chars(56);
        let (a3, i3) = (a2.clone(), i2.clone());
        dialog(&a2, tr("Discard test polder?"), body.upcast_ref(), tr("Discard"), true, move || bg(&a3, vec!["discard".into(), i3.clone()], |a, v| {
            if let Some(e) = err_of(&v) { toast(a, &e) } else { toast(a, tr("Test polder discarded")); reload(a, None); } }));
    });
    row.append(&del);
    d.append(&row);
    // banners
    if let Some(pm) = p["pending_merge"].as_str() {
        let b = gtk::Box::new(gtk::Orientation::Horizontal, 10); b.add_css_class("banner"); b.add_css_class("bad");
        let v = gtk::Box::new(gtk::Orientation::Vertical, 2); v.set_hexpand(true);
        v.append(&lbl(tr("Merge was interrupted"), "h2")); v.append(&lbl(tr("An earlier merge was not finished (for example because of a crash or power failure). Finish it or roll everything back; until then you cannot merge anything else."), ""));
        if let Some(fl) = p["rollback_failures"].as_array() {
            v.append(&lbl(tr("Rolling back was only partly possible. Fix the files below and roll back again:"), "h2"));
            for x in fl.iter().take(8) { v.append(&lbl(&format!("{} — {}", x[0].as_str().unwrap_or(""), x[1].as_str().unwrap_or("")), "sub")); }
        }
        b.append(&v);
        let partial = p["pending_phase"].as_str() == Some("rollback-partial");
        let f = btn(tr("Finish"), "pill"); f.set_sensitive(!partial); let r = btn(tr("Roll back"), "flat2");
        for (w, cmd) in [(&f, "resume"), (&r, "rollback")] {
            let a2 = a.clone(); let i2 = id.to_string(); let c = cmd.to_string(); let _ = pm;
            w.connect_clicked(move |_| { let c2 = c.clone(); bg(&a2, vec![c.clone(), i2.clone()], move |a, v| {
                if let Some(e) = err_of(&v) { toast(a, &e) } else { let r = &v["report"]; toast(a, &tf!("{}: {} file(s), {} failed", if c2 == "resume" { tr("Finished") } else { tr("Rolled back") }, r["done"].as_array().map(|x| x.len()).unwrap_or(0), r["failed"].as_array().map(|x| x.len()).unwrap_or(0))); reload(a, None); } }); });
            w.set_valign(gtk::Align::Center); b.append(w);
        }
        d.append(&b);
    }
    if !archived {
        let info = lbl(tr("Programs in the polder can only change your project folder inside the polder; the rest of your home folder is a throwaway copy there. It is not a secured virtual machine: what happens via the internet or devices cannot be undone."), "sub");
        d.append(&info);
    }
    if let Some(e) = err_of(&ch) { d.append(&lbl(&e, "banner bad")); return; }
    // changes + diff
    let list: Vec<Value> = ch["changes"].as_array().cloned().unwrap_or_default().into_iter().filter(|c| c["home"] != c["branch"]).collect();
    let pane = gtk::Paned::new(gtk::Orientation::Horizontal); pane.set_vexpand(true); pane.set_position(330); pane.set_shrink_end_child(false); pane.set_resize_end_child(true); pane.set_wide_handle(true);
    let left = gtk::Box::new(gtk::Orientation::Vertical, 6);
    let lh = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let n_conf = list.iter().filter(|c| c["conflict"] == json!(true)).count();
    let hl = lbl(&format!("{} wijzigingen{}", list.len(), if n_conf > 0 { tf!(", {n_conf} conflict(s)" ; n_conf) } else { String::new() }), "h2"); hl.set_hexpand(true); lh.append(&hl);
    let all = btn(tr("All without conflict"), "flat2"); lh.append(&all);
    left.append(&lh);
    let lb = gtk::ListBox::new(); lb.add_css_class("changes"); lb.set_selection_mode(gtk::SelectionMode::Single);
    let mut checks = vec![];
    // a rename shows once (new name); its deletion row is folded into it
    let folded: std::collections::BTreeSet<String> = list.iter().filter_map(|c| c["renamed_from"].as_str().map(String::from)).collect();
    for c in list.iter().filter(|c| !folded.contains(c["path"].as_str().unwrap_or(""))) {
        let path = c["path"].as_str().unwrap_or("").to_string();
        let r = gtk::ListBoxRow::new(); let h = gtk::Box::new(gtk::Orientation::Horizontal, 8);
        let cb = gtk::CheckButton::new(); cb.set_active(a.borrow().selected.contains(&path)); cb.set_sensitive(!archived);
        let conflict = c["conflict"] == json!(true);
        h.append(&cb);
        let kind = c["kind"].as_str().unwrap_or("");
        let tg = lbl(if conflict { tr("Conflict") } else { kind_nl(kind) }, "tag"); tg.add_css_class(if conflict { "conflict" } else { kind }); tg.set_valign(gtk::Align::Center); h.append(&tg);
        let shown = match c["renamed_from"].as_str() { Some(f) => format!("{f} → {path}"), None => path.clone() };
        let pl = lbl(&shown, ""); pl.set_wrap(false); pl.set_ellipsize(pango::EllipsizeMode::Middle); pl.set_hexpand(true); h.append(&pl);
        if c["warnings"].as_array().map(|w| w.iter().any(|x| x.as_str().map(|s| s == tr("changes permissions") || s == "symlink" || s.starts_with(tr("symlink points outside the folder: {target}").split('{').next().unwrap_or("\u{0}"))).unwrap_or(false))).unwrap_or(false) {
            let w = gtk::Image::from_icon_name("dialog-warning-symbolic"); w.set_tooltip_text(Some(&c["warnings"].as_array().unwrap().iter().filter_map(|x| x.as_str()).collect::<Vec<_>>().join("\n"))); h.append(&w);
        }
        r.set_child(Some(&h)); lb.append(&r);
        let a2 = a.clone(); let p2 = path.clone();
        cb.connect_toggled(move |cb| { let mut x = a2.borrow_mut(); if cb.is_active() { x.selected.insert(p2.clone()); } else { x.selected.remove(&p2); x.force.remove(&p2); } });
        checks.push((cb, path, conflict));
    }
    let checks2 = checks.clone();
    all.connect_clicked(move |_| for (cb, _, conf) in &checks2 { cb.set_active(!conf); });
    if list.is_empty() {
        lb.append(&lbl(if archived { tr("No changes.") } else { tr("No changes yet. Open a terminal in the polder and go ahead.") }, "sub"));
    }
    let sc = gtk::ScrolledWindow::builder().vexpand(true).hscrollbar_policy(gtk::PolicyType::Never).child(&lb).build();
    let card = gtk::Box::new(gtk::Orientation::Vertical, 0); card.add_css_class("card"); card.append(&sc); card.set_vexpand(true);
    left.append(&card);
    pane.set_start_child(Some(&left));
    let diff = gtk::Box::new(gtk::Orientation::Vertical, 6); diff.set_margin_start(8);
    diff.append(&lbl(tr("Choose a change to compare."), "sub"));
    pane.set_end_child(Some(&diff));
    a.borrow_mut().diff = diff;
    let a2 = a.clone(); let lst = list.clone(); let origin = ch["origin"].as_str().unwrap_or("").to_string(); let upper = ch["upper"].as_str().unwrap_or("").to_string();
    let paths: Vec<String> = checks.iter().map(|c| c.1.clone()).collect();
    lb.connect_row_selected(move |_, r| if let Some(r) = r { if let Some(p) = paths.get(r.index() as usize) {
        if let Some(c) = lst.iter().find(|c| c["path"].as_str() == Some(p)) { show_diff(&a2, c, &origin, &upper); } } });
    d.append(&pane);
    // merge bar
    let mb = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let ml = lbl(tr("Nothing reaches the mainland without your permission. You first see exactly what will happen."), "sub"); ml.set_hexpand(true); mb.append(&ml);
    let go = btn(tr("Merge selected…"), "pill"); go.set_sensitive(!archived && p["pending_merge"].is_null());
    let a2 = a.clone(); let i2 = id.to_string(); go.connect_clicked(move |_| dry_run(&a2, &i2));
    mb.append(&go); d.append(&mb);
}

// ------------------------------------------------------------------ diff view
fn read_text(p: &str) -> Option<String> {
    let m = std::fs::symlink_metadata(p).ok()?;
    if !m.is_file() || m.len() > 2 << 20 { return None; }
    let b = std::fs::read(p).ok()?;
    if b.iter().take(8192).any(|&c| c == 0) { return None; }
    String::from_utf8(b).ok()
}
/// line diff (LCS); None when too large
fn line_diff<'a>(a: &[&'a str], b: &[&'a str]) -> Option<Vec<(char, &'a str)>> {
    let (n, m) = (a.len(), b.len()); if n * m > 4_000_000 { return None; }
    let mut t = vec![0u16; (n + 1) * (m + 1)];
    for i in (0..n).rev() { for j in (0..m).rev() { t[i * (m + 1) + j] = if a[i] == b[j] { t[(i + 1) * (m + 1) + j + 1] + 1 } else { t[(i + 1) * (m + 1) + j].max(t[i * (m + 1) + j + 1]) }; } }
    let (mut i, mut j, mut out) = (0, 0, vec![]);
    while i < n && j < m { if a[i] == b[j] { out.push(('=', a[i])); i += 1; j += 1; } else if t[(i + 1) * (m + 1) + j] >= t[i * (m + 1) + j + 1] { out.push(('-', a[i])); i += 1; } else { out.push(('+', b[j])); j += 1; } }
    while i < n { out.push(('-', a[i])); i += 1; } while j < m { out.push(('+', b[j])); j += 1; }
    Some(out)
}
fn tv() -> (gtk::TextView, gtk::TextBuffer) {
    let v = gtk::TextView::new(); v.set_editable(false); v.set_cursor_visible(false); v.set_monospace(true); v.add_css_class("diff"); v.set_left_margin(6);
    let b = v.buffer();
    b.create_tag(Some("del"), &[("paragraph-background", &"#fbe3e1")]); b.create_tag(Some("add"), &[("paragraph-background", &"#e2f3e6")]);
    b.create_tag(Some("gap"), &[("paragraph-background", &"#eeeeee")]);
    (v, b)
}
fn meta_rows(st: &Value) -> String {
    match st["t"].as_str() {
        Some("File") => tf!("file · {} · permissions {:o}\nsha256 {}…", size_h(st["size"].as_u64().unwrap_or(0)), st["mode"].as_u64().unwrap_or(0), &st["hash"].as_str().unwrap_or("")[..16.min(st["hash"].as_str().unwrap_or("").len())]),
        Some("Link") => format!("symlink → {}", st["target"].as_str().unwrap_or("")),
        Some("Dir") => format!("map · rechten {:o}", st["mode"].as_u64().unwrap_or(0)),
        _ => tr("does not exist").into(),
    }
}
fn show_diff(a: &A, c: &Value, origin: &str, upper: &str) {
    let d = a.borrow().diff.clone(); clear(&d);
    let path = c["path"].as_str().unwrap_or("");
    let hp = format!("{origin}/{}", c["renamed_from"].as_str().unwrap_or(path)); let bp = format!("{upper}/{path}");
    let title = lbl(path, "h2"); title.set_wrap(false); title.set_ellipsize(pango::EllipsizeMode::Middle); d.append(&title);
    for w in c["warnings"].as_array().cloned().unwrap_or_default() { let l = lbl(&format!("⚠ {}", w.as_str().unwrap_or("")), "sub"); l.set_max_width_chars(30); d.append(&l); }
    if c["conflict"] == json!(true) {
        let b = gtk::Box::new(gtk::Orientation::Vertical, 6); b.add_css_class("banner"); b.add_css_class("warn");
        let cl = lbl(tr("Conflict: this file was also changed on the mainland since the polder was created. Merging replaces that change."), ""); cl.set_max_width_chars(30); b.append(&cl);
        let cb = gtk::CheckButton::new(); let cl = lbl(tr("Choose the polder version anyway (replace the mainland version)"), ""); cl.set_max_width_chars(30); cl.set_hexpand(true); let crow = gtk::Box::new(gtk::Orientation::Horizontal, 6); crow.append(&cb); crow.append(&cl);
        cb.set_active(a.borrow().force.contains(path));
        let a2 = a.clone(); let p2 = path.to_string();
        cb.connect_toggled(move |cb| { let mut x = a2.borrow_mut(); if cb.is_active() { x.force.insert(p2.clone()); x.selected.insert(p2.clone()); } else { x.force.remove(&p2); } });
        b.append(&crow); d.append(&b);
    }
    let (ht, bt) = (if c["home"]["t"] == "Absent" { Some(String::new()) } else { read_text(&hp) }, if c["branch"]["t"] == "Absent" { Some(String::new()) } else { read_text(&bp) });
    let heads = gtk::Box::new(gtk::Orientation::Horizontal, 6); heads.set_homogeneous(true);
    heads.append(&lbl(tr("Mainland (now)"), "difftitle")); heads.append(&lbl(tr("Test polder"), "difftitle")); d.append(&heads);
    match (ht, bt) {
        (Some(h), Some(b)) if c["home"]["t"] != "Link" && c["branch"]["t"] != "Link" => {
            let (hl, bl): (Vec<&str>, Vec<&str>) = (h.lines().collect(), b.lines().collect());
            let (lv, lbuf) = tv(); let (rv, rbuf) = tv();
            match line_diff(&hl, &bl) {
                Some(ops) => {
                    let mut i = 0;
                    while i < ops.len() {
                        if ops[i].0 == '=' { lbuf.insert(&mut lbuf.end_iter(), &format!("{}\n", ops[i].1)); rbuf.insert(&mut rbuf.end_iter(), &format!("{}\n", ops[i].1)); i += 1; continue; }
                        let (mut dels, mut adds) = (vec![], vec![]);
                        while i < ops.len() && ops[i].0 != '=' { if ops[i].0 == '-' { dels.push(ops[i].1) } else { adds.push(ops[i].1) } i += 1; }
                        for k in 0..dels.len().max(adds.len()) {
                            match dels.get(k) { Some(l) => lbuf.insert_with_tags_by_name(&mut lbuf.end_iter(), &format!("{l}\n"), &["del"]), None => lbuf.insert_with_tags_by_name(&mut lbuf.end_iter(), "\n", &["gap"]) }
                            match adds.get(k) { Some(l) => rbuf.insert_with_tags_by_name(&mut rbuf.end_iter(), &format!("{l}\n"), &["add"]), None => rbuf.insert_with_tags_by_name(&mut rbuf.end_iter(), "\n", &["gap"]) }
                        }
                    }
                }
                None => { lbuf.set_text(tr("(too large to compare line by line)")); rbuf.set_text(&meta_rows(&c["branch"])); }
            }
            let row = gtk::Box::new(gtk::Orientation::Horizontal, 6); row.set_homogeneous(true); row.set_vexpand(true);
            let ls = gtk::ScrolledWindow::builder().child(&lv).vexpand(true).hexpand(true).min_content_width(60).build(); let rs = gtk::ScrolledWindow::builder().child(&rv).vexpand(true).hexpand(true).min_content_width(60).build();
            rs.set_vadjustment(Some(&ls.vadjustment()));
            for s in [&ls, &rs] { let f = gtk::Frame::new(None); f.set_child(Some(s)); row.append(&f); }
            d.append(&row);
        }
        _ => {
            let row = gtk::Box::new(gtk::Orientation::Horizontal, 6); row.set_homogeneous(true);
            for st in [&c["home"], &c["branch"]] { let l = lbl(&meta_rows(st), "card"); l.set_margin_top(2); l.set_selectable(true); l.set_valign(gtk::Align::Start); let f = gtk::Box::new(gtk::Orientation::Vertical, 0); f.add_css_class("card"); l.set_margin_start(10); l.set_margin_end(10); l.set_margin_bottom(10); f.append(&l); row.append(&f); }
            d.append(&row);
            let base = lbl(&format!("Bij het maken van de polder: {}", meta_rows(&c["base"]).replace('\n', " · ")), "sub"); d.append(&base);
            if c["home"]["t"] == "File" || c["branch"]["t"] == "File" {
                let ob = btn(tr("Open both versions"), "flat2"); ob.set_halign(gtk::Align::Start);
                let (h2, b2) = (hp.clone(), bp.clone());
                ob.connect_clicked(move |_| { for p in [&h2, &b2] { if std::path::Path::new(p).exists() { let _ = gio::AppInfo::launch_default_for_uri(&gio::File::for_path(p).uri(), None::<&gio::AppLaunchContext>); } } });
                d.append(&ob);
            }
        }
    }
}

// ------------------------------------------------------------------ merge
fn act_nl(o: &Value) -> String {
    let p = o["path"].as_str().unwrap_or("");
    match o["act"].as_str().unwrap_or("") {
        "mkdir" => format!("Map maken: {p}"), "chmod" => format!("Rechten wijzigen: {p}"), "delete" => format!("Verwijderen: {p}"),
        "rmdir" => format!("Map verwijderen: {p}"), "write" => if o["pre"]["t"] == "Absent" { format!("Toevoegen: {p}") } else { format!("Vervangen: {p}") }, x => format!("{x}: {p}") }
}
fn sel_args(a: &A) -> Vec<String> {
    let x = a.borrow(); let mut v = vec![];
    for p in &x.selected { if x.force.contains(p) { v.push("--force".into()); } v.push(p.clone()); }
    v
}
fn reviewed_merge_args(id: &str, chosen: &[String], preview: &Value) -> Result<Vec<String>, String> {
    let token = preview["review_token"].as_str().filter(|s| !s.is_empty())
        .ok_or_else(|| tr("This preview cannot be verified. Refresh and review the changes again.").to_string())?;
    let mut args = vec!["merge".into(), id.into(), "--review-token".into(), token.into()];
    args.extend_from_slice(chosen);
    Ok(args)
}
fn dry_run(a: &A, id: &str) {
    if a.borrow().selected.is_empty() { toast(a, tr("Select one or more changes first")); return; }
    let chosen = sel_args(a);
    let mut args = vec!["plan".into(), id.into()]; args.extend(chosen.clone());
    let id2 = id.to_string();
    bg(a, args, move |a, v| {
        if a.borrow().cur.as_deref() != Some(&id2) { return; }
        if let Some(e) = err_of(&v) { toast(a, &e); return; }
        let merge_args = match reviewed_merge_args(&id2, &chosen, &v) {
            Ok(args) => args,
            Err(e) => { toast(a, &e); reload(a, None); return; }
        };
        let ops = v["ops"].as_array().cloned().unwrap_or_default();
        let body = gtk::Box::new(gtk::Orientation::Vertical, 8);
        body.append(&lbl(tr("Dry run: this is how your original folder will change. Nothing has been changed yet."), "sub"));
        let lb = gtk::Box::new(gtk::Orientation::Vertical, 2);
        for o in &ops { lb.append(&lbl(&format!("• {}", act_nl(o)), "")); }
        if ops.is_empty() { lb.append(&lbl(tr("There is nothing to merge."), "")); }
        let sc = gtk::ScrolledWindow::builder().child(&lb).min_content_height(80).max_content_height(200).propagate_natural_height(true).hscrollbar_policy(gtk::PolicyType::Never).build();
        body.append(&sc);
        body.append(&lbl(tr("Sluis checks every file right before it replaces it and keeps changes made by other programs in the meantime. A program that still has a file open can, after the merge, keep writing to the old version; that cannot be prevented. Close programs that are editing these files first."), "sub"));
        let warns: Vec<String> = v["warnings"].as_array().cloned().unwrap_or_default().iter().filter_map(|w| w.as_str().map(String::from)).filter(|w| !w.ends_with(": symlink")).collect();
        if !warns.is_empty() { let w = lbl(&format!("{}\n{}", tr("Note:"), warns.iter().map(|w| format!("• {w}")).collect::<Vec<_>>().join("\n")), "banner warn"); body.append(&w); }
        let sk = v["skipped"].as_array().cloned().unwrap_or_default();
        if !sk.is_empty() { body.append(&lbl(&format!("{}\n{}", tr("Skipped:"), sk.iter().map(|s| format!("• {}: {}", s[0].as_str().unwrap_or(""), s[1].as_str().unwrap_or(""))).collect::<Vec<_>>().join("\n")), "sub")); }
        if ops.is_empty() { dialog(a, tr("Nothing to merge"), body.upcast_ref(), tr("Close"), false, || {}); return; }
        let (a2, i2) = (a.clone(), id2.clone());
        dialog(a, &tf!("Merge {} change(s)?", ops.len()), body.upcast_ref(), tr("Merge"), false, move || {
            let i3 = i2.clone();
            bg(&a2, merge_args.clone(), move |a, v| {
                if let Some(e) = err_of(&v) { toast(a, &format!("{} {}", tf!("Merge failed: {e}" ; e), tr("Refresh and review the changes again."))); reload(a, None); return; }
                let r = &v["report"]; let nf = r["failed"].as_array().map(|x| x.len()).unwrap_or(0);
                let msg = if nf == 0 { tf!("{} change(s) merged to the mainland", r["done"].as_array().map(|x| x.len()).unwrap_or(0)) }
                          else { tf!("{} merged, {nf} not: {}", r["done"].as_array().map(|x| x.len()).unwrap_or(0), r["failed"][0][1].as_str().unwrap_or("") ; nf) };
                toast(a, &msg);
                { let mut x = a.borrow_mut(); if x.cur.as_deref() == Some(&i3) { x.selected.clear(); x.force.clear(); } }
                reload(a, None);
            });
        });
    });
}

// ------------------------------------------------------------------ new polder
fn new_dialog(a: &A, folder: Option<String>) {
    let parent = a.borrow().win.clone();
    let d = gtk::Window::builder().transient_for(&parent).modal(true).resizable(false).default_width(480).title(tr("New test polder")).build();
    d.add_css_class("sl");
    let v = gtk::Box::new(gtk::Orientation::Vertical, 10); v.set_margin_top(20); v.set_margin_bottom(16); v.set_margin_start(22); v.set_margin_end(22);
    v.append(&lbl(tr("New test polder"), "h1"));
    v.append(&lbl(tr("Sluis pumps a new polder dry next to your folder: you experiment freely in it, your original folder stays untouched."), "sub"));
    let name = gtk::Entry::builder().placeholder_text(tr("Name, for example New design")).build();
    let desc = gtk::Entry::builder().placeholder_text(tr("Description (optional)")).build();
    let fl = lbl(&folder.as_deref().map(tilde).unwrap_or(tr("No folder chosen yet").into()), "sub"); let fsel = Rc::new(RefCell::new(folder.clone()));
    let fb = btn(tr("Choose folder…"), "flat2");
    let frow = gtk::Box::new(gtk::Orientation::Horizontal, 8); frow.append(&fb); fl.set_hexpand(true); frow.append(&fl);
    v.append(&lbl(tr("Name"), "difftitle")); v.append(&name); v.append(&lbl(tr("Folder (the mainland)"), "difftitle")); v.append(&frow); v.append(&desc);
    if let Some(f) = &folder { if let Some(n) = std::path::Path::new(f).file_name() { name.set_text(&tf!("{} – experiment", n.to_string_lossy())); } }
    let (fs2, fl2, d2) = (fsel.clone(), fl.clone(), d.clone());
    fb.connect_clicked(move |_| {
        #[allow(deprecated)]
        let fc = gtk::FileChooserNative::new(Some(tr("Choose a project folder")), Some(&d2), gtk::FileChooserAction::SelectFolder, Some(tr("Choose")), Some(tr("Cancel")));
        let (fs3, fl3) = (fs2.clone(), fl2.clone());
        #[allow(deprecated)]
        fc.connect_response(move |fc, r| { if r == gtk::ResponseType::Accept { if let Some(p) = fc.file().and_then(|f| f.path()) { let s = p.to_string_lossy().to_string(); fl3.set_label(&tilde(&s)); *fs3.borrow_mut() = Some(s); } } });
        #[allow(deprecated)] fc.show();
    });
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 8); row.set_halign(gtk::Align::End); row.set_margin_top(6);
    let c = btn(tr("Cancel"), "flat2"); let o = btn(tr("Create polder"), "pill");
    row.append(&c); row.append(&o); v.append(&row); d.set_child(Some(&v));
    let d1 = d.clone(); c.connect_clicked(move |_| d1.close());
    let (a2, d3) = (a.clone(), d.clone());
    o.connect_clicked(move |o| {
        let Some(f) = fsel.borrow().clone() else { toast(&a2, tr("Choose a folder first")); return; };
        let n = name.text().to_string(); let n = if n.trim().is_empty() { tr("Test polder").to_string() } else { n };
        o.set_sensitive(false); o.set_label(tr("Pumping dry…"));
        let d4 = d3.clone();
        bg(&a2, vec!["create".into(), n, f, desc.text().to_string()], move |a, v| {
            d4.close();
            if let Some(e) = err_of(&v) { toast(a, &e); return; }
            let id = v["meta"]["id"].as_str().unwrap_or("").to_string();
            toast(a, tr("Test polder ready. Open a terminal to get started."));
            reload(a, Some(id));
        });
    });
    d.present();
}

fn build(app: &gtk::Application, new_folder: Option<String>) -> A {
    let prov = gtk::CssProvider::new();
    #[allow(deprecated)] prov.load_from_data(&css(&theme::palette()));
    gtk::style_context_add_provider_for_display(&gtk::gdk::Display::default().unwrap(), &prov, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
    let win = gtk::ApplicationWindow::builder().application(app).title(tr("Sluis")).default_width(1010).default_height(560).build();
    win.add_css_class("sl");
    let ov = gtk::Overlay::new();
    let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);
    let side = gtk::Box::new(gtk::Orientation::Vertical, 10); side.add_css_class("side"); side.set_size_request(210, -1);
    let hb = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let ic = gtk::Image::from_icon_name("view-dual-symbolic"); ic.set_pixel_size(24); hb.append(&ic);
    let tv = gtk::Box::new(gtk::Orientation::Vertical, 0); tv.append(&lbl(tr("Sluis"), "h1")); tv.append(&lbl(tr("Test polders"), "sub")); hb.append(&tv);
    side.append(&hb);
    let nb = btn(tr("New test polder"), "pill"); side.append(&nb);
    let refresh = btn(tr("Refresh"), "flat2"); side.append(&refresh);
    let session_status = lbl("", "sub"); side.append(&session_status);
    let plist = gtk::ListBox::new(); plist.add_css_class("polders");
    side.append(&gtk::ScrolledWindow::builder().child(&plist).vexpand(true).hscrollbar_policy(gtk::PolicyType::Never).build());
    root.append(&side);
    let detail = gtk::Box::new(gtk::Orientation::Vertical, 10); detail.set_hexpand(true);
    detail.set_margin_top(16); detail.set_margin_bottom(14); detail.set_margin_start(20); detail.set_margin_end(20);
    root.append(&detail);
    ov.set_child(Some(&root));
    let toast_l = lbl("", "toast");
    let toast = gtk::Revealer::builder().child(&toast_l).halign(gtk::Align::Center).valign(gtk::Align::End).margin_bottom(60).build();
    ov.add_overlay(&toast); win.set_child(Some(&ov));
    let a = Rc::new(RefCell::new(App { win: win.clone(), plist: plist.clone(), detail, toast, toast_l, polders: vec![], cur: None, changes: Value::Null,
        selected: Default::default(), force: Default::default(), diff: gtk::Box::new(gtk::Orientation::Vertical, 0), busy: false,
        generation: 0, sessions: vec![], session_status, allow_close: false, close_prompt: false }));
    let a2 = a.clone(); nb.connect_clicked(move |_| new_dialog(&a2, None));
    let a2 = a.clone(); refresh.connect_clicked(move |_| reload(&a2, None));
    let a2 = a.clone();
    plist.connect_row_activated(move |_, r| { if let Some(id) = unsafe { r.data::<String>("id").map(|d| d.as_ref().clone()) } { reload(&a2, Some(id)); } });
    let a2 = a.clone();
    win.connect_close_request(move |_| {
        poll_sessions(&a2);
        let (count, allow, prompt) = { let x = a2.borrow(); (x.sessions.len(), x.allow_close, x.close_prompt) };
        if allow || count == 0 { return glib::Propagation::Proceed; }
        if prompt { return glib::Propagation::Stop; }
        a2.borrow_mut().close_prompt = true;
        let body = lbl(&tf!("Closing Sluis stops all {} running terminals and their programs. Unsaved work may be lost. Keep Sluis open until they finish, or close and stop them now.", count), "sub");
        body.set_max_width_chars(56);
        let a3 = a2.clone();
        let d = dialog(&a2, tr("Stop running programs and close Sluis?"), body.upcast_ref(), tr("Close and stop programs"), true, move || {
            a3.borrow_mut().allow_close = true;
            let win = a3.borrow().win.clone(); win.close();
        });
        let a3 = a2.clone(); d.connect_destroy(move |_| a3.borrow_mut().close_prompt = false);
        glib::Propagation::Stop
    });
    let a2 = a.clone(); win.connect_is_active_notify(move |w| { if w.is_active() { reload(&a2, None); } });
    let weak = Rc::downgrade(&a);
    glib::timeout_add_seconds_local(1, move || {
        let Some(a) = weak.upgrade() else { return glib::ControlFlow::Break; };
        poll_sessions(&a); glib::ControlFlow::Continue
    });
    update_session_status(&a);
    win.present();
    reload(&a, None);
    if let Some(f) = new_folder { let a2 = a.clone(); glib::timeout_add_local_once(std::time::Duration::from_millis(300), move || new_dialog(&a2, Some(f))); }
    a
}

fn main() -> glib::ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let new_folder = args.iter().position(|a| a == "--new").and_then(|i| args.get(i + 1)).cloned();
    let app = gtk::Application::new(Some("nl.polderos.Sluis"), gio::ApplicationFlags::NON_UNIQUE);
    let keep: Rc<RefCell<Option<A>>> = Rc::new(RefCell::new(None)); let k = keep.clone();
    app.connect_activate(move |ap| { if k.borrow().is_none() { *k.borrow_mut() = Some(build(ap, new_folder.clone())); } });
    app.run_with_args::<&str>(&[])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirmation_uses_the_reviewed_selection_and_token() {
        let mut chosen = vec!["--force".into(), "a file".into(), "nested/b".into()];
        let args = reviewed_merge_args("project", &chosen, &json!({"review_token": "reviewed-content"})).unwrap();
        chosen.clear(); // A subsequent refresh or selection edit cannot change the reviewed request.
        assert_eq!(args, ["merge", "project", "--review-token", "reviewed-content", "--force", "a file", "nested/b"]);
    }

    #[test]
    fn confirmation_refuses_a_missing_or_empty_review_token() {
        for preview in [json!({"ops": []}), json!({"review_token": ""}), json!({"review_token": null})] {
            assert!(reviewed_merge_args("project", &["f".into()], &preview).is_err());
        }
    }

    #[test]
    fn failed_terminal_launch_reports_cli_and_bubblewrap_errors() {
        assert_eq!(session_failure(r#"{"ok":false,"error":"This test polder is busy","busy":true}"#), "This test polder is busy");
        assert_eq!(session_failure("bwrap: Creating new namespace failed\n"), "bwrap: Creating new namespace failed");
        assert!(!session_failure("").is_empty());
    }
}
