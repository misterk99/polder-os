//! polder-sluisd: Polder Sluis service + command line. All output is JSON (the GUI uses it), messages are Dutch.
//!   list | create <naam> <map> [omschrijving] | info <id> | changes <id> | plan <id> [--force P]... P...
//!   merge <id> [--review-token TOKEN] [--force P]... P... | pending <id> | resume <id> | rollback <id> [merge-id]
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
fn fail(m: String) -> ! { let busy = m == busy_msg(); out(json!({"ok": false, "error": m, "busy": busy})); std::process::exit(if busy { 75 } else { 1 }) }

fn info(m: &Meta) -> serde_json::Value {
    let ch = changes(&m.id).unwrap_or_default();
    let real: Vec<&Change> = ch.iter().filter(|c| c.home != c.branch).collect();
    json!({"meta": m, "status": status_of(&ch, m), "changes": real.len(), "conflicts": ch.iter().filter(|c| c.conflict).count(),
           "usage": polder_usage(&m.id), "pending_merge": pending_merge(&m.id), "upper": polder_dir(&m.id).map(|d| d.join("upper")).ok(),
           "pending_phase": pending_state(&m.id).map(|x| x.1),
           "rollback_failures": pending_state(&m.id).filter(|x| x.1 == Phase::RollbackPartial).and_then(|(mid, _)| polder_dir(&m.id).ok().and_then(|d| rollback_report(&d.join("journal"), &mid))).map(|r| r.failed)})
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

/// Runner switches end at `--`; arguments belonging to the child are never Sluis options.
fn run_options(args: &[String]) -> Res<(bool, bool, Vec<String>)> {
    let split = args.iter().position(|a| a == "--").unwrap_or(args.len());
    let (mut net, mut terminal) = (false, false);
    for a in &args[..split] {
        match a.as_str() {
            "--net" => net = true,
            "--terminal" => terminal = true,
            _ => return Err(tf!("Unknown runner option: {}. Put the command after --.", a)),
        }
    }
    let command = args.get(split + 1..).unwrap_or_default().to_vec();
    Ok((net, terminal, command))
}

fn merge_options(args: &[String]) -> Res<(Vec<String>, Vec<String>, Option<String>)> {
    let (rest, token) = if args.first().map(String::as_str) == Some("--review-token") {
        let token = args.get(1).filter(|t| t.len() == 64 && t.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or_else(|| tr("A valid preview token is required. Review the changes again.").to_string())?;
        (&args[2..], Some(token.clone()))
    } else { (args, None) };
    let (selected, force) = paths(rest);
    Ok((selected, force, token))
}

fn run(id: &str, args: &[String]) -> ! {
    let mut m = meta(id).unwrap_or_else(|x| fail(x));
    if m.archived { fail(tr("This test polder is archived; unarchive it first.").into()); }
    let (net, terminal, mut cmd) = run_options(args).unwrap_or_else(|x| fail(x));
    let net = net || m.network;
    if cmd.is_empty() || terminal {
        let title = tf!("[Test polder: {}] Terminal", m.name);
        let app_id = format!("nl.polderos.sluis.{}", m.id);
        cmd = if which("foot") { vec!["foot".into(), format!("--app-id={app_id}"), format!("--title={title}"), "bash".into()] }
              else if which("xfce4-terminal") { vec!["xfce4-terminal".into(), format!("--title={title}"), "--disable-server".into()] }
              else { vec!["bash".into()] };
    }
    let entry = format!("{} {}", now(), cmd.join(" "));
    m = update_meta(id, |x| x.runs.push(entry)).unwrap_or_else(|x| fail(x));
    let a = runner_argv(&m, net, &cmd).unwrap_or_else(|x| fail(x));
    use std::os::unix::process::CommandExt;
    let err = std::process::Command::new(&a[0]).args(&a[1..]).exec();
    fail(format!("bubblewrap starten mislukt: {err}"))
}
fn which(b: &str) -> bool { std::env::var("PATH").unwrap_or_default().split(':').any(|d| Path::new(d).join(b).exists()) }

fn daemon() -> ! {
    // single instance: started by the Wayland session supervisor and/or XDG autostart
    let rt = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| std::env::temp_dir().to_string_lossy().into());
    let lock = std::fs::OpenOptions::new().create(true).write(true).open(Path::new(&rt).join("polder-sluisd.lock"));
    if let Ok(f) = &lock { use std::os::fd::AsRawFd; if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 { std::process::exit(0); } }
    let mut warned = std::collections::BTreeSet::new();
    loop {
        for m in list() {
            if let Some(p) = pending_merge(&m.id) {
                if warned.insert(format!("p{}{p}", m.id)) { notify(tr("Merge interrupted"), &tf!("Test polder ‘{}’: open Sluis to finish or roll back.", m.name), "dialog-warning-symbolic"); }
            }
            let u = polder_usage(&m.id);
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

fn usage() -> String { include_str!("polder-sluisd.rs").lines().skip(1).take(6).map(|l| l.trim_start_matches("//!")).collect::<Vec<_>>().join("\n") }

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let c = a.first().map(|s| s.as_str()).unwrap_or("");
    let id = a.get(1).cloned().unwrap_or_default();
    if !matches!(c, "list" | "create" | "du" | "daemon" | "--help" | "-h" | "help" | "") && !valid_id(&id) { fail(tf!("invalid test polder id: {}", id.escape_debug())) }
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
            out(json!({"origin": m.origin, "upper": polder_dir(&id).map(|d| d.join("upper")).ok(), "status": status_of(&ch, &m), "changes": ch})) }
        "plan" => {
            let (s, f) = paths(&a[2..]);
            let p = plan(&id, &s, &f).unwrap_or_else(|x| fail(x));
            let mut v = json!(&p);
            v["review_token"] = json!(review_token(&p));
            out(v)
        }
        "merge" => {
            let (s, f, token) = merge_options(&a[2..]).unwrap_or_else(|x| fail(x));
            let name = meta(&id).map(|m| m.name).unwrap_or_default();
            if s.is_empty() && f.is_empty() { fail(tr("no paths chosen: give the paths you want to merge (see `changes`)").into()) }
            let result = match token { Some(t) => merge_reviewed(&id, &s, &f, &t), None => merge(&id, &s, &f) };
            match result {
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
        "network" => { let on = a.get(2).map(|s| s == "on").unwrap_or(false); out(info(&update_meta(&id, |m| m.network = on).unwrap_or_else(|x| fail(x)))) }
        "du" => out(json!({"total": disk_usage(&data_dir()), "polders": list().iter().map(|m| json!({"id": m.id, "usage": polder_usage(&m.id)})).collect::<Vec<_>>()})),
        "run" => run(&id, &a[2..]),
        "--help" | "-h" | "help" => { println!("{}", usage()); }
        "daemon" => daemon(),
        _ => { eprintln!("{}", usage()); std::process::exit(2) }
    }
}

#[cfg(test)]
#[path = "../sluis_tests.rs"]
mod tests;

#[cfg(test)]
mod cli_tests {
    use super::*;
    fn args(a: &[&str]) -> Vec<String> { a.iter().map(|s| (*s).to_string()).collect() }

    #[test]
    fn child_flags_never_change_runner_permissions_or_command() {
        let command = args(&["printf", "%s", "--net", "--terminal", "--"]);
        let mut a = vec!["--".into()]; a.extend(command.clone());
        assert_eq!(run_options(&a).unwrap(), (false, false, command));
        assert_eq!(run_options(&args(&["--net", "--", "program", "--terminal"])).unwrap(),
                   (true, false, args(&["program", "--terminal"])));
        assert_eq!(run_options(&args(&["--terminal"])).unwrap(), (false, true, vec![]));
        assert!(run_options(&args(&["program", "--net"])).is_err());
    }

    #[test]
    fn preview_token_is_required_when_option_is_present_and_not_a_path() {
        let token = "ab".repeat(32);
        let (selected, forced, reviewed) = merge_options(&args(&["--review-token", &token, "--force", "a", "b"])).unwrap();
        assert_eq!(selected, args(&["a", "b"]));
        assert_eq!(forced, args(&["a"]));
        assert_eq!(reviewed.as_deref(), Some(token.as_str()));
        assert!(merge_options(&args(&["--review-token"])).is_err());
        assert!(merge_options(&args(&["--review-token", "bad", "a"])).is_err());
        assert!(merge_options(&args(&["--force", "--review-token"])).unwrap().2.is_none());
    }
}
