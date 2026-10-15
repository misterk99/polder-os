//! polder-sluisd: Polder Sluis service + command line. All output is JSON (the GUI uses it), messages are Dutch.
//!   list | create <naam> <map> [omschrijving] | info <id> | changes <id> | plan <id> [--force P]... P...
//!   merge <id> [--force P]... P... | pending <id> | resume <id> | rollback <id> [merge-id]
//!   discard <id> | archive <id> | unarchive <id> | network <id> on|off | du
//!   run <id> [--net] [--terminal] [-- cmd...]     start a terminal/app inside the proefpolder (bubblewrap)
//!   daemon                                        resident: reports interrupted merges and storage use (notifications)
#[path = "../i18n.rs"] #[macro_use] mod i18n;
#[allow(unused_imports)] use i18n::tr;
#[path = "../sluis.rs"] mod sluis;
use serde_json::json;
use sluis::*;
use std::path::Path;

fn notify(title: &str, body: &str, icon: &str) {
    let _ = std::process::Command::new("notify-send").args(["-a", tr("Polder Sluis"), "-i", icon, title, body]).status();
}
fn out(v: serde_json::Value) { println!("{}", serde_json::to_string(&v).unwrap()); }
fn fail(m: String) -> ! { out(json!({"ok": false, "error": m})); std::process::exit(1) }

fn info(m: &Meta) -> serde_json::Value {
    let ch = changes(&m.id).unwrap_or_default();
    let real: Vec<&Change> = ch.iter().filter(|c| c.home != c.branch).collect();
    json!({"meta": m, "status": status_of(&ch, m), "changes": real.len(), "conflicts": ch.iter().filter(|c| c.conflict).count(),
           "usage": disk_usage(&pdir(&m.id)), "pending_merge": pending_merge(&m.id), "upper": pdir(&m.id).join("upper")})
}
fn paths(args: &[String]) -> (Vec<String>, Vec<String>) {
    let (mut sel, mut force) = (vec![], vec![]); let mut i = 0;
    while i < args.len() {
        if args[i] == "--force" && i + 1 < args.len() { force.push(args[i + 1].clone()); sel.push(args[i + 1].clone()); i += 2; }
        else if args[i] == "--from" && i + 1 < args.len() { for l in std::fs::read_to_string(&args[i + 1]).unwrap_or_default().lines() {
            if let Some(f) = l.strip_prefix("!") { force.push(f.into()); sel.push(f.into()); } else if !l.is_empty() { sel.push(l.into()); } } i += 2; }
        else { sel.push(args[i].clone()); i += 1; }
    }
    (sel, force)
}

fn run(id: &str, args: &[String]) -> ! {
    let mut m = meta(id).unwrap_or_else(|x| fail(x));
    if m.archived { fail(tr("This test polder is archived; unarchive it first.").into()); }
    let net = args.iter().any(|a| a == "--net") || m.network;
    let mut cmd: Vec<String> = args.iter().skip_while(|a| *a != "--").skip(1).cloned().collect();
    if cmd.is_empty() || args.iter().any(|a| a == "--terminal") {
        let title = tf!("[Test polder: {}] Terminal", m.name);
        let app_id = format!("nl.polderos.sluis.{}", m.id);
        cmd = if which("foot") { vec!["foot".into(), format!("--app-id={app_id}"), format!("--title={title}"), "bash".into()] }
              else if which("xfce4-terminal") { vec!["xfce4-terminal".into(), format!("--title={title}"), "--disable-server".into()] }
              else { vec!["bash".into()] };
    }
    m.runs.push(format!("{} {}", now(), cmd.join(" "))); let _ = save_meta(&m);
    let a = runner_argv(&m, net, &cmd);
    use std::os::unix::process::CommandExt;
    let err = std::process::Command::new(&a[0]).args(&a[1..]).exec();
    fail(format!("bubblewrap starten mislukt: {err}"))
}
fn which(b: &str) -> bool { std::env::var("PATH").unwrap_or_default().split(':').any(|d| Path::new(d).join(b).exists()) }

fn daemon() -> ! {
    let mut warned = std::collections::BTreeSet::new();
    loop {
        for m in list() {
            if let Some(p) = pending_merge(&m.id) {
                if warned.insert(format!("p{}{p}", m.id)) { notify(tr("Merge interrupted"), &tf!("Test polder ‘{}’: open Sluis to finish or roll back.", m.name), "dialog-warning-symbolic"); }
            }
            let u = disk_usage(&pdir(&m.id));
            if u > 2 << 30 && warned.insert(format!("u{}", m.id)) {
                notify(tr("Test polder takes up a lot of space"), &tf!("‘{}’ uses {:.1} GB. Discard or archive?", m.name, u as f64 / (1u64 << 30) as f64), "drive-harddisk-symbolic");
            }
        }
        let st = unsafe { let mut s: libc::statvfs = std::mem::zeroed(); let c = std::ffi::CString::new(data_dir().to_string_lossy().as_bytes()).unwrap(); libc::statvfs(c.as_ptr(), &mut s); s };
        if st.f_blocks > 0 && (st.f_bavail as f64) < st.f_blocks as f64 * 0.05 && warned.insert("disk".into()) {
            notify(tr("Disk almost full"), tr("Test polders use space on your disk. Clean up old polders in Sluis."), "drive-harddisk-symbolic");
        }
        std::thread::sleep(std::time::Duration::from_secs(300));
    }
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let c = a.first().map(|s| s.as_str()).unwrap_or("");
    let id = a.get(1).cloned().unwrap_or_default();
    match c {
        "list" => out(json!(list().iter().map(info).collect::<Vec<_>>())),
        "create" => {
            if a.len() < 3 { fail(tr("usage: create <name> <folder> [description]").into()); }
            let m = create(&a[1], Path::new(&a[2]), a.get(3).map(|s| s.as_str()).unwrap_or("")).unwrap_or_else(|x| fail(x));
            out(info(&m))
        }
        "info" => out(info(&meta(&id).unwrap_or_else(|x| fail(x)))),
        "changes" => { let m = meta(&id).unwrap_or_else(|x| fail(x));
            let ch = changes(&id).unwrap_or_else(|x| fail(x));
            out(json!({"origin": m.origin, "upper": pdir(&id).join("upper"), "status": status_of(&ch, &m), "changes": ch})) }
        "plan" => { let (s, f) = paths(&a[2..]); out(json!(plan(&id, &s, &f).unwrap_or_else(|x| fail(x)))) }
        "merge" => {
            let (s, f) = paths(&a[2..]);
            let name = meta(&id).map(|m| m.name).unwrap_or_default();
            if s.is_empty() && f.is_empty() { fail(tr("no paths chosen: give the paths you want to merge (see `changes`)").into()) }
            match merge(&id, &s, &f) {
                Ok(r) => {
                    if r.failed.is_empty() { notify(tr("Changes merged"), &tf!("{} change(s) from ‘{name}’ are now on the mainland.", r.done.len() ; name), "emblem-ok-symbolic"); }
                    else { notify(tr("Merge partly succeeded"), &tf!("{} succeeded, {} did not (see Sluis).", r.done.len(), r.failed.len()), "dialog-warning-symbolic"); }
                    out(json!({"ok": true, "report": r}))
                }
                Err(x) => { if x.starts_with("CRASH") { std::process::abort(); } fail(x) }
            }
        }
        "pending" => out(json!({"pending": pending_merge(&id)})),
        "resume" => match resume(&id) { Ok(r) => out(json!({"ok": true, "report": r})), Err(x) => fail(x) },
        "rollback" => match rollback(&id, a.get(2).map(|s| s.as_str())) {
            Ok(r) => { notify(tr("Merge rolled back"), &tf!("{} file(s) restored on the mainland.", r.done.len()), "edit-undo-symbolic"); out(json!({"ok": true, "report": r})) }
            Err(x) => fail(x) },
        "discard" => { discard(&id).unwrap_or_else(|x| fail(x)); out(json!({"ok": true})) }
        "archive" | "unarchive" => out(info(&archive(&id, c == "archive").unwrap_or_else(|x| fail(x)))),
        "network" => { let mut m = meta(&id).unwrap_or_else(|x| fail(x)); m.network = a.get(2).map(|s| s == "on").unwrap_or(false); save_meta(&m).unwrap_or_else(|x| fail(x)); out(info(&m)) }
        "du" => out(json!({"total": disk_usage(&data_dir()), "polders": list().iter().map(|m| json!({"id": m.id, "usage": disk_usage(&pdir(&m.id))})).collect::<Vec<_>>()})),
        "run" => run(&id, &a[2..]),
        "daemon" => daemon(),
        _ => { eprintln!("{}", include_str!("polder-sluisd.rs").lines().skip(1).take(6).map(|l| l.trim_start_matches("//!")).collect::<Vec<_>>().join("\n")); std::process::exit(2) }
    }
}

#[cfg(test)]
#[path = "../sluis_tests.rs"]
mod tests;
