//! Merge-engine tests. The polder side is produced by the real runner mechanism: an unprivileged user-namespace
//! overlayfs mounted by bubblewrap, so whiteouts/opaque dirs/copy-ups are exactly what users get.
use super::sluis::*;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

struct T { root: PathBuf, home: PathBuf, upper: PathBuf, work: PathBuf, j: PathBuf, base: std::collections::BTreeMap<String, Entry> }
impl Drop for T { fn drop(&mut self) { let _ = rm_rf(&self.root); } }
fn setup(name: &str, init: &str) -> T {
    let root = std::env::temp_dir().join(format!("sluis-test-{name}-{}", std::process::id()));
    let _ = rm_rf(&root);
    let (home, upper, work, j) = (root.join("vasteland"), root.join("upper"), root.join("work"), root.join("journal"));
    for d in [&home, &upper, &work, &j] { fs::create_dir_all(d).unwrap(); }
    sh(&home, init);
    let base = scan(&home).unwrap();
    T { root, home, upper, work, j, base }
}
fn sh(dir: &Path, script: &str) {
    let ok = std::process::Command::new("sh").arg("-ec").arg(script).current_dir(dir).status().unwrap().success();
    assert!(ok, "script failed: {script}");
}
/// run a shell script inside the polder (overlay mounted by bubblewrap, like `polder-sluisd run`)
fn inpolder(t: &T, script: &str) {
    let h = t.home.to_string_lossy().to_string();
    let ok = std::process::Command::new("bwrap").args(["--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--overlay-src", &h, "--overlay", &t.upper.to_string_lossy(), &t.work.to_string_lossy(), &h, "--chdir", &h, "sh", "-ec", script]).status().unwrap().success();
    assert!(ok, "polder script failed: {script}");
}

/// The polder side needs bubblewrap with unprivileged user namespaces + overlayfs. When that is unavailable the test is
/// skipped and the skip is recorded (stderr + $POLDER_SLUIS_SKIP_LOG); with POLDER_SLUIS_REQUIRE_OVERLAY=1 (CI) a missing
/// capability is a failure instead.
fn overlay_or_skip(test: &str) -> bool {
    static OK: std::sync::OnceLock<Result<(), String>> = std::sync::OnceLock::new();
    let r = OK.get_or_init(|| {
        let d = std::env::temp_dir().join(format!("sluis-probe-{}", std::process::id())); let _ = rm_rf(&d);
        for x in ["lower", "upper", "work"] { fs::create_dir_all(d.join(x)).unwrap(); }
        let s = |x: &str| d.join(x).to_string_lossy().to_string();
        let out = std::process::Command::new("bwrap").args(["--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--overlay-src", &s("lower"), "--overlay", &s("upper"), &s("work"), &s("lower"), "sh", "-c", "echo x > f"])
            .current_dir(d.join("lower")).output();
        let ok = match out { Ok(o) if o.status.success() && d.join("upper/f").exists() => Ok(()), Ok(o) => Err(String::from_utf8_lossy(&o.stderr).trim().to_string()), Err(x) => Err(format!("bwrap: {x}")) };
        let _ = rm_rf(&d); ok
    });
    match r {
        Ok(()) => true,
        Err(why) => {
            if std::env::var("POLDER_SLUIS_REQUIRE_OVERLAY").as_deref() == Ok("1") { panic!("{test}: user-namespace overlayfs required but unavailable: {why}"); }
            eprintln!("SKIP {test}: bubblewrap user-namespace overlayfs unavailable: {why}");
            if let Ok(l) = std::env::var("POLDER_SLUIS_SKIP_LOG") { use std::io::Write; if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(l) { let _ = writeln!(f, "{test}\t{why}"); } }
            false
        }
    }
}
fn ch(t: &T) -> Vec<Change> { changes_for(&t.home, &t.upper, &t.base).unwrap() }
fn get<'a>(c: &'a [Change], p: &str) -> &'a Change { c.iter().find(|x| x.path == p).unwrap_or_else(|| panic!("no change for {p}: {:?}", c.iter().map(|x| &x.path).collect::<Vec<_>>())) }
fn rd(p: PathBuf) -> String { fs::read_to_string(p).unwrap() }
fn merge_sel(t: &T, sel: &[&str], force: &[&str]) -> Report {
    let c = ch(t); let s: Vec<String> = sel.iter().map(|x| x.to_string()).collect(); let f: Vec<String> = force.iter().map(|x| x.to_string()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &s, &f);
    apply_plan(&t.j, &t.home, &p, None, &Faults::none()).unwrap()
}

#[test]
fn isolation_and_selective_merge() {
    if !overlay_or_skip("isolation_and_selective_merge") { return; }
    let t = setup("basic", "echo een > a.txt; echo twee > b.txt; echo drie > c.txt; mkdir src; echo x > src/main.rs");
    inpolder(&t, "echo EEN > a.txt; rm b.txt; echo nieuw > d.txt; chmod 600 c.txt; echo y >> src/main.rs");
    assert_eq!(rd(t.home.join("a.txt")), "een\n");                    // vasteland untouched
    assert!(t.home.join("b.txt").exists() && !t.home.join("d.txt").exists());
    let c = ch(&t);
    assert_eq!(get(&c, "a.txt").kind, "gewijzigd");
    assert_eq!(get(&c, "b.txt").kind, "verwijderd");
    assert_eq!(get(&c, "d.txt").kind, "toegevoegd");
    assert_eq!(get(&c, "c.txt").kind, "rechten");
    assert_eq!(get(&c, "src/main.rs").kind, "gewijzigd");
    assert!(c.iter().all(|x| !x.conflict));
    // merge ONE change, keep the rest in the polder
    let r = merge_sel(&t, &["a.txt"], &[]);
    assert_eq!(r.done, vec!["a.txt"]); assert!(r.failed.is_empty());
    assert_eq!(rd(t.home.join("a.txt")), "EEN\n");
    assert!(t.home.join("b.txt").exists() && !t.home.join("d.txt").exists());
    assert_eq!(fs::metadata(t.home.join("c.txt")).unwrap().permissions().mode() & 0o777, 0o644);
    // after merging, a.txt is equal on both sides
    let c2 = ch(&t); let a = get(&c2, "a.txt"); assert_eq!(a.home, a.branch);
    // dry run warnings for deletion and permission change
    let p = plan_for(&t.home, &t.upper, &c2, &["b.txt".into(), "c.txt".into()], &[]);
    assert!(p.warnings.iter().any(|w| w.contains(crate::i18n::tr("deletes a file on the mainland"))) && p.warnings.iter().any(|w| w.contains(crate::i18n::tr("changes permissions"))));
    let r = merge_sel(&t, &["b.txt", "c.txt", "d.txt"], &[]);
    assert_eq!(r.failed.len(), 0);
    assert!(!t.home.join("b.txt").exists()); assert_eq!(rd(t.home.join("d.txt")), "nieuw\n");
    assert_eq!(fs::metadata(t.home.join("c.txt")).unwrap().permissions().mode() & 0o777, 0o600);
}

#[test]
fn symlinks() {
    if !overlay_or_skip("symlinks") { return; }
    let t = setup("links", "echo a > a; echo b > b; ln -s a link; ln -s b keep");
    inpolder(&t, "ln -sfn b link; ln -s /etc/passwd buiten; ln -s ../x omhoog; rm keep; echo c > keep");
    let c = ch(&t);
    assert_eq!(get(&c, "link").kind, "gewijzigd");
    assert!(get(&c, "buiten").warnings.iter().any(|w| w.starts_with(crate::i18n::tr("symlink points outside the folder: {target}").split('{').next().unwrap())));
    assert!(get(&c, "omhoog").warnings.iter().any(|w| w.starts_with(crate::i18n::tr("symlink points outside the folder: {target}").split('{').next().unwrap())));
    assert_eq!(get(&c, "keep").kind, "type");
    merge_sel(&t, &["link", "buiten", "keep"], &[]);
    assert_eq!(fs::read_link(t.home.join("link")).unwrap(), PathBuf::from("b"));
    assert_eq!(fs::read_link(t.home.join("buiten")).unwrap(), PathBuf::from("/etc/passwd"));
    assert!(fs::symlink_metadata(t.home.join("keep")).unwrap().is_file());
    assert!(!t.home.join("omhoog").exists() && fs::symlink_metadata(t.home.join("omhoog")).is_err());
}

#[test]
fn renames() {
    if !overlay_or_skip("renames") { return; }
    let t = setup("rename", "echo inhoud > oud.txt; mkdir map; echo 1 > map/een; echo 2 > map/twee");
    inpolder(&t, "mv oud.txt nieuw.txt; mv map hernoemd");
    let c = ch(&t);
    let n = get(&c, "nieuw.txt"); assert_eq!(n.kind, "hernoemd"); assert_eq!(n.renamed_from.as_deref(), Some("oud.txt"));
    assert_eq!(get(&c, "hernoemd/een").kind, "hernoemd");
    // selecting the rename takes the deletion of the old name with it
    let r = merge_sel(&t, &["nieuw.txt", "hernoemd/een", "hernoemd/twee", "map"], &[]);
    assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert!(!t.home.join("oud.txt").exists()); assert_eq!(rd(t.home.join("nieuw.txt")), "inhoud\n");
    assert!(!t.home.join("map").exists()); assert_eq!(rd(t.home.join("hernoemd/twee")), "2\n");
}

#[test]
fn deletions_and_opaque_dirs() {
    if !overlay_or_skip("deletions_and_opaque_dirs") { return; }
    let t = setup("delete", "mkdir -p weg/diep; echo 1 > weg/diep/f; echo 2 > weg/g; mkdir opnieuw; echo oud > opnieuw/oud; echo blijft > opnieuw/ook");
    inpolder(&t, "rm -r weg; rm -r opnieuw; mkdir opnieuw; echo nieuw > opnieuw/nieuw");
    let c = ch(&t);
    for p in ["weg", "weg/diep", "weg/diep/f", "weg/g", "opnieuw/oud", "opnieuw/ook"] { assert_eq!(get(&c, p).kind, "verwijderd", "{p}"); }
    assert_eq!(get(&c, "opnieuw/nieuw").kind, "toegevoegd");
    // a file appeared on the vasteland inside the dir the polder deleted: rmdir must refuse, nothing else lost
    sh(&t.home, "echo van-vasteland > weg/extra");
    let r = merge_sel(&t, &["weg", "weg/diep", "weg/diep/f", "weg/g"], &[]);
    assert!(r.failed.iter().any(|(p, _)| p == "weg"), "{:?}", r);
    assert_eq!(rd(t.home.join("weg/extra")), "van-vasteland\n");
    assert!(!t.home.join("weg/g").exists());
    let r = merge_sel(&t, &["opnieuw/oud", "opnieuw/ook", "opnieuw/nieuw"], &[]);
    assert!(r.failed.is_empty());
    assert!(!t.home.join("opnieuw/oud").exists() && t.home.join("opnieuw/nieuw").exists());
}

#[test]
fn large_file() {
    if !overlay_or_skip("large_file") { return; }
    let t = setup("large", "head -c 67108864 /dev/urandom > groot.bin");
    let before = hash_file(&t.home.join("groot.bin")).unwrap();
    inpolder(&t, "printf X | dd of=groot.bin bs=1 seek=33554432 conv=notrunc 2>/dev/null; head -c 1048576 /dev/zero >> groot.bin");
    assert_eq!(hash_file(&t.home.join("groot.bin")).unwrap(), before);
    let c = ch(&t); let g = get(&c, "groot.bin");
    assert_eq!(g.kind, "gewijzigd");
    if let St::File { size, .. } = g.branch { assert_eq!(size, 67108864 + 1048576); } else { panic!() }
    merge_sel(&t, &["groot.bin"], &[]);
    assert_eq!(hash_file(&t.home.join("groot.bin")).unwrap(), hash_file(&t.upper.join("groot.bin")).unwrap());
}

#[test]
fn concurrent_edits() {
    if !overlay_or_skip("concurrent_edits") { return; }
    let t = setup("conflict", "echo basis > samen.txt; echo basis > alleen-polder.txt; echo basis > alleen-vasteland.txt; echo basis > gelijk.txt");
    inpolder(&t, "echo polder > samen.txt; echo polder > alleen-polder.txt; echo zelfde > gelijk.txt; echo polder > beide-nieuw.txt");
    sh(&t.home, "echo vasteland > samen.txt; echo vasteland > alleen-vasteland.txt; echo zelfde > gelijk.txt; echo vasteland > beide-nieuw.txt");
    let c = ch(&t);
    assert!(get(&c, "samen.txt").conflict);
    assert!(get(&c, "beide-nieuw.txt").conflict);
    assert!(!get(&c, "alleen-polder.txt").conflict);
    assert!(c.iter().all(|x| x.path != "alleen-vasteland.txt"));   // vasteland-only changes are not polder changes
    let g = get(&c, "gelijk.txt"); assert!(!g.conflict && g.home == g.branch);
    // conflicts are skipped unless explicitly forced
    let r = merge_sel(&t, &["samen.txt", "alleen-polder.txt"], &[]);
    assert_eq!(r.done, vec!["alleen-polder.txt"]); assert!(r.skipped.iter().any(|(p, _)| p == "samen.txt"));
    assert_eq!(rd(t.home.join("samen.txt")), "vasteland\n");
    let r = merge_sel(&t, &["samen.txt"], &["samen.txt"]);
    assert_eq!(r.done, vec!["samen.txt"]); assert_eq!(rd(t.home.join("samen.txt")), "polder\n");
    // vasteland changes between dry run and apply: the op is refused, the newer vasteland file is kept
    // after a merge the merged file is the new baseline: a further polder edit is not a conflict
    let mut base = t.base.clone(); rebase(&mut base, &t.home, &["alleen-polder.txt".into()]);
    inpolder(&t, "echo polder2 > alleen-polder.txt");
    let c = changes_for(&t.home, &t.upper, &base).unwrap(); assert!(!get(&c, "alleen-polder.txt").conflict);
    let p = plan_for(&t.home, &t.upper, &c, &["alleen-polder.txt".into()], &[]);
    sh(&t.home, "echo tussendoor > alleen-polder.txt");
    let r = apply_plan(&t.j, &t.home, &p, None, &Faults::none()).unwrap();
    assert_eq!(r.failed.len(), 1); assert_eq!(rd(t.home.join("alleen-polder.txt")), "tussendoor\n");
}

fn snapshot(home: &Path) -> Vec<(String, St)> { scan(home).unwrap().into_iter().map(|(k, v)| (k, v.st)).collect() }

#[test]
fn interrupted_merge_rollback_and_resume() {
    if !overlay_or_skip("interrupted_merge_rollback_and_resume") { return; }
    let t = setup("crash", "echo 1 > a; echo 2 > b; echo 3 > c; echo 4 > weg; ln -s a l");
    inpolder(&t, "echo A > a; echo B > b; echo C > c; rm weg; mkdir -p nieuw/sub; echo n > nieuw/sub/n; ln -sfn b l; chmod 700 c");
    let before = snapshot(&t.home);
    let c = ch(&t);
    let all: Vec<String> = c.iter().map(|x| x.path.clone()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &all, &[]);
    assert!(p.ops.len() >= 7, "{:?}", p.ops);
    // "crash" after 3 operations
    assert!(apply_plan(&t.j, &t.home, &p, None, &Faults::crash("op:3")).unwrap_err().starts_with("CRASH"));
    assert!(pending_in(&t.j).is_some());
    assert_ne!(snapshot(&t.home), before);
    // a new merge is refused while one is pending
    assert!(apply_plan(&t.j, &t.home, &p, None, &Faults::none()).is_err());
    // rollback restores the vasteland exactly
    let r = rollback_in(&t.j, None, &Faults::none()).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(snapshot(&t.home), before);
    assert!(pending_in(&t.j).is_none());
    // crash again, this time resume
    assert!(apply_plan(&t.j, &t.home, &p, None, &Faults::crash("op:4")).is_err());
    let r = resume_in(&t.j, &Faults::none()).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(rd(t.home.join("a")), "A\n"); assert_eq!(rd(t.home.join("nieuw/sub/n")), "n\n");
    assert!(!t.home.join("weg").exists()); assert_eq!(fs::read_link(t.home.join("l")).unwrap(), PathBuf::from("b"));
    assert_eq!(fs::metadata(t.home.join("c")).unwrap().permissions().mode() & 0o777, 0o700);
    // and a finished merge can be undone too
    let mid = r.merge_id.clone();
    let r = rollback_in(&t.j, Some(&mid), &Faults::none()).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(snapshot(&t.home), before);
}

#[test]
fn crash_mid_write_leaves_no_partial_file() {
    if !overlay_or_skip("crash_mid_write_leaves_no_partial_file") { return; }
    // a crash between writing the temp file and the rename: the target is intact and the temp file is cleaned up
    let t = setup("tmpfile", "echo origineel > f");
    inpolder(&t, "echo nieuw > f");
    let c = ch(&t); let p = plan_for(&t.home, &t.upper, &c, &["f".into()], &[]);
    assert!(apply_plan(&t.j, &t.home, &p, None, &Faults::crash("op:0")).is_err());
    fs::write(t.home.join(".f.sluis-tmp"), "half").unwrap();
    assert_eq!(rd(t.home.join("f")), "origineel\n");
    rollback_in(&t.j, None, &Faults::none()).unwrap();
    assert_eq!(fs::read_dir(&t.home).unwrap().count(), 1);
    assert_eq!(rd(t.home.join("f")), "origineel\n");
}

// ======================================================================== review fixes: ids, crash points, races
/// a file tree outside every Sluis root that must survive everything
fn outside(name: &str) -> PathBuf {
    let o = std::env::temp_dir().join(format!("sluis-outside-{name}-{}", std::process::id()));
    let _ = rm_rf(&o); fs::create_dir_all(o.join("deep")).unwrap();
    fs::write(o.join("precious.txt"), "keep me\n").unwrap(); fs::write(o.join("deep/also.txt"), "keep\n").unwrap();
    fs::set_permissions(&o, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(o.join("meta.json"), r#"{"id":"evil","name":"evil","description":"","origin":"/","created":0,"archived":false,"network":false}"#).unwrap();
    o
}
fn intact(o: &Path) {
    assert_eq!(rd(o.join("precious.txt")), "keep me\n"); assert_eq!(rd(o.join("deep/also.txt")), "keep\n");
    assert_eq!(fs::metadata(o).unwrap().permissions().mode() & 0o777, 0o755);
}

#[test]
fn id_validation_and_containment() {
    // the only test that sets POLDER_SLUIS_DIR (process-wide), so it is self-contained
    let root = std::env::temp_dir().join(format!("sluis-ids-{}", std::process::id())); let _ = rm_rf(&root);
    let dd = root.join("data"); fs::create_dir_all(dd.join("polders")).unwrap();
    std::env::set_var("POLDER_SLUIS_DIR", &dd);
    let o = outside("ids");
    for bad in ["", ".", "..", "../x", "../../outside", "a/b", "/etc", "/tmp/x", "A", "a b", "-x", "a\0b", "a/../b", "polder\n", "ü", &"x".repeat(65)] {
        assert!(!valid_id(bad), "{bad:?}");
        assert!(polder_dir(bad).is_err() && meta(bad).is_err() && discard(bad).is_err() && changes(bad).is_err() && rollback(bad, None).is_err(), "{bad:?}");
    }
    // an id that escapes via .. relative to the polders dir (the pre-fix pdir() would have resolved this)
    let rel = format!("../../{}", o.file_name().unwrap().to_string_lossy());
    assert!(discard(&rel).is_err() && archive(&rel, true).is_err());
    // a symlinked inventory entry pointing outside: never listed, read, written or deleted
    std::os::unix::fs::symlink(&o, dd.join("polders/evil")).unwrap();
    assert!(polder_dir("evil").is_err() && meta("evil").is_err() && discard("evil").is_err() && archive("evil", true).is_err());
    assert!(list().iter().all(|m| m.id != "evil") && !ids().contains(&"evil".to_string()));
    // a real polder with a symlinked child (e.g. upper -> outside) is removed without touching the target
    let proj = root.join("project"); fs::create_dir_all(&proj).unwrap(); fs::write(proj.join("f"), "x").unwrap();
    let m = create("Mijn proef", &proj, "").unwrap(); assert!(valid_id(&m.id));
    let d = polder_dir(&m.id).unwrap();
    std::os::unix::fs::symlink(&o, d.join("link-out")).unwrap();
    std::os::unix::fs::symlink(o.join("precious.txt"), d.join("upper/file-link")).unwrap();
    fs::create_dir_all(d.join("work/work/locked")).unwrap(); fs::set_permissions(d.join("work/work"), fs::Permissions::from_mode(0o000)).unwrap();
    // meta.json naming another id is refused
    let mut wrong = meta(&m.id).unwrap(); wrong.id = "evil".into(); assert!(save_meta(&wrong).is_err());
    discard(&m.id).unwrap();
    assert!(fs::symlink_metadata(&d).is_err());
    intact(&o); assert!(dd.join("polders/evil").symlink_metadata().is_ok());
    // rm_rf on a symlink removes the link only
    rm_rf(&dd.join("polders/evil")).unwrap(); intact(&o);
    std::env::remove_var("POLDER_SLUIS_DIR");
    let _ = rm_rf(&root); let _ = rm_rf(&o);
}

#[test]
fn rm_rf_never_follows_symlinks() {
    let o = outside("rmrf");
    let t = std::env::temp_dir().join(format!("sluis-rmrf-{}", std::process::id())); let _ = rm_rf(&t);
    fs::create_dir_all(t.join("a/b")).unwrap();
    std::os::unix::fs::symlink(&o, t.join("a/dirlink")).unwrap();
    std::os::unix::fs::symlink(o.join("precious.txt"), t.join("a/b/filelink")).unwrap();
    fs::create_dir(t.join("a/zero")).unwrap(); fs::set_permissions(t.join("a/zero"), fs::Permissions::from_mode(0)).unwrap();
    rm_rf(&t).unwrap();
    assert!(fs::symlink_metadata(&t).is_err()); intact(&o);
    let _ = rm_rf(&o);
}

/// merge with a real polder baseline file next to the journal (like polder_dir/{baseline.json,journal})
fn merge_setup(name: &str) -> (T, Plan, PathBuf) {
    let t = setup(name, "echo 1 > a; echo 2 > b; mkdir d; echo 3 > d/c");
    inpolder(&t, "echo A > a; rm b; echo N > nieuw; echo C > d/c");
    let bl = t.root.join("baseline.json"); write_json(&bl, &t.base).unwrap();
    let c = ch(&t); let all: Vec<String> = c.iter().map(|x| x.path.clone()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &all, &[]);
    (t, p, bl)
}
fn bl_has(bl: &Path, k: &str, content: &str) -> bool {
    let b: std::collections::BTreeMap<String, Entry> = read_json(bl).unwrap();
    match b.get(k).map(|e| &e.st) { Some(St::File { hash, .. }) => *hash == hash_str(content), None => content.is_empty(), _ => false }
}
fn hash_str(s: &str) -> String { let p = std::env::temp_dir().join(format!("sluis-h-{}-{}", std::process::id(), s.len())); fs::write(&p, s).unwrap(); let h = hash_file(&p).unwrap(); let _ = fs::remove_file(p); h }

#[test]
fn crash_points_are_recoverable() {
    if !overlay_or_skip("crash_points_are_recoverable") { return; }
    for point in ["op:0", "op:2", "ops-done", "applied", "baseline", "reconciled"] {
        let (t, p, bl) = merge_setup(&format!("cp-{}", point.replace(':', "")));
        let err = apply_plan(&t.j, &t.home, &p, Some(&bl), &Faults::crash(point)).unwrap_err();
        assert!(err.starts_with("CRASH"), "{point}: {err}");
        let (mid, ph) = pending_state_in(&t.j).unwrap_or_else(|| panic!("{point}: crash must leave the merge pending"));
        match point { "op:0" | "op:2" | "ops-done" => assert_eq!(ph, Phase::Applying), "applied" => assert_eq!(ph, Phase::Applied),
                      "baseline" => assert_eq!(ph, Phase::Applied), _ => assert_eq!(ph, Phase::Reconciled) }
        // a new merge is refused while one is pending
        assert!(apply_plan(&t.j, &t.home, &p, Some(&bl), &Faults::none()).is_err(), "{point}");
        // resume finishes it and the baseline is reconciled exactly once, from the saved pre-merge baseline
        let r = resume_in(&t.j, &Faults::none()).unwrap(); assert!(r.failed.is_empty(), "{point}: {:?}", r.failed);
        assert_eq!(r.merge_id, mid); assert!(pending_in(&t.j).is_none(), "{point}");
        assert_eq!(rd(t.home.join("a")), "A\n"); assert!(!t.home.join("b").exists()); assert_eq!(rd(t.home.join("d/c")), "C\n");
        assert!(bl_has(&bl, "a", "A\n") && bl_has(&bl, "nieuw", "N\n") && bl_has(&bl, "b", ""), "{point}: baseline not reconciled");
        // and the same crash, then a rollback: mainland and baseline exactly as before
        let (t2, p2, bl2) = merge_setup(&format!("cr-{}", point.replace(':', "")));
        let before = snapshot(&t2.home); let bbefore = fs::read(&bl2).unwrap();
        let _ = apply_plan(&t2.j, &t2.home, &p2, Some(&bl2), &Faults::crash(point));
        let r = rollback_in(&t2.j, None, &Faults::none()).unwrap(); assert!(r.rolled_back && r.failed.is_empty(), "{point}: {:?}", r.failed);
        assert_eq!(snapshot(&t2.home), before, "{point}"); assert_eq!(fs::read(&bl2).unwrap(), bbefore, "{point}");
        assert!(pending_in(&t2.j).is_none());
    }
}

#[test]
fn partial_rollback_stays_pending_and_is_retryable() {
    if !overlay_or_skip("partial_rollback_stays_pending_and_is_retryable") { return; }
    let (t, p, bl) = merge_setup("partial");
    let before = snapshot(&t.home); let bbefore = fs::read(&bl).unwrap();
    let r = apply_plan(&t.j, &t.home, &p, Some(&bl), &Faults::none()).unwrap(); assert!(r.failed.is_empty());
    let mid = r.merge_id.clone();
    // injected failure restoring one op + a real one: a file changed after the merge
    let n = p.ops.iter().position(|o| o.path == "nieuw").unwrap();
    fs::write(t.home.join("a"), "na de merge\n").unwrap();
    let r = rollback_in(&t.j, Some(&mid), &Faults::crash(&format!("rollback-op:{n}"))).unwrap();
    assert!(!r.rolled_back); assert!(r.failed.iter().any(|(p, _)| p == "a") && r.failed.iter().any(|(p, x)| p == "nieuw" && x.starts_with("CRASH")), "{:?}", r.failed);
    assert_eq!(pending_state_in(&t.j), Some((mid.clone(), Phase::RollbackPartial)));
    let saved = rollback_report(&t.j, &mid).unwrap(); assert_eq!(saved.failed, r.failed);       // failure details kept
    assert_ne!(fs::read(&bl).unwrap(), bbefore, "baseline must not be restored by a partial rollback");
    assert!(resume_in(&t.j, &Faults::none()).is_err());                                       // cannot "finish" a half rollback
    // fix the conflicting file the way the user would (put the merged version back) and retry
    fs::write(t.home.join("a"), "A\n").unwrap();
    let r = rollback_in(&t.j, None, &Faults::none()).unwrap(); assert!(r.rolled_back, "{:?}", r.failed);
    assert_eq!(snapshot(&t.home), before); assert_eq!(fs::read(&bl).unwrap(), bbefore);
    assert!(pending_in(&t.j).is_none()); assert!(rollback_in(&t.j, Some(&mid), &Faults::none()).is_err());
    // a failing baseline restore also keeps the rollback pending
    let (t2, p2, bl2) = merge_setup("partial-bl");
    apply_plan(&t2.j, &t2.home, &p2, Some(&bl2), &Faults::none()).unwrap();
    let mid2 = fs::read_dir(&t2.j).unwrap().next().unwrap().unwrap().file_name().to_string_lossy().to_string();
    let r = rollback_in(&t2.j, Some(&mid2), &Faults::crash("rollback-baseline")).unwrap(); assert!(!r.rolled_back);
    assert_eq!(pending_state_in(&t2.j).unwrap().1, Phase::RollbackPartial);
    assert!(rollback_in(&t2.j, None, &Faults::none()).unwrap().rolled_back);
}

#[test]
fn chmod_needs_exact_precondition() {
    if !overlay_or_skip("chmod_needs_exact_precondition") { return; }
    let t = setup("chmodrace", "echo x > f; mkdir d; chmod 755 d");
    inpolder(&t, "chmod 600 f; chmod 700 d");
    let c = ch(&t); assert_eq!(get(&c, "d").kind, "rechten"); assert_eq!(get(&c, "f").kind, "rechten");
    let p = plan_for(&t.home, &t.upper, &c, &["f".into(), "d".into()], &[]);
    // the mainland changes the permissions after the dry run: both chmods are refused, the mainland mode is kept
    sh(&t.home, "chmod 640 f; chmod 750 d");
    let r = apply_plan(&t.j, &t.home, &p, None, &Faults::none()).unwrap();
    assert_eq!(r.failed.len(), 2, "{:?}", r);
    assert_eq!(fs::metadata(t.home.join("f")).unwrap().permissions().mode() & 0o777, 0o640);
    assert_eq!(fs::metadata(t.home.join("d")).unwrap().permissions().mode() & 0o777, 0o750);
    // and a change inside the race window (after the check, right before chmod) is refused as well
    sh(&t.home, "chmod 644 f; chmod 755 d");
    let h = t.home.clone();
    let f = Faults::hook(move |pt| if pt.starts_with("chmod:") { let p = h.join(&pt[6..]); fs::set_permissions(&p, fs::Permissions::from_mode(0o711)).unwrap(); });
    let r = apply_plan(&t.j, &t.home, &p, None, &f).unwrap();
    assert_eq!(r.failed.len(), 2, "{:?}", r);
    assert_eq!(fs::metadata(t.home.join("f")).unwrap().permissions().mode() & 0o777, 0o711);
    assert_eq!(fs::metadata(t.home.join("d")).unwrap().permissions().mode() & 0o777, 0o711);
}

#[test]
fn swapped_parent_symlink_is_never_followed() {
    if !overlay_or_skip("swapped_parent_symlink_is_never_followed") { return; }
    let o = outside("parent");
    let t = setup("parentswap", "mkdir sub; echo oud > sub/precious.txt; mkdir sub2; echo oud > sub2/precious.txt");
    inpolder(&t, "echo nieuw > sub/precious.txt; echo nieuw > sub2/precious.txt");
    let c = ch(&t); let p = plan_for(&t.home, &t.upper, &c, &["sub/precious.txt".into(), "sub2/precious.txt".into()], &[]);
    // (1) before the merge: sub is replaced by a symlink to a folder outside the project
    sh(&t.home, &format!("mv sub sub.moved; ln -s {} sub", o.display()));
    // (2) during the merge: sub2 is swapped for a symlink after the temp file is written, right before the rename
    let (h, o2) = (t.home.clone(), o.clone());
    let f = Faults::hook(move |pt| if pt == "replace:sub2/precious.txt" { fs::rename(h.join("sub2"), h.join("sub2.moved")).unwrap(); std::os::unix::fs::symlink(&o2, h.join("sub2")).unwrap(); });
    let r = apply_plan(&t.j, &t.home, &p, None, &f).unwrap();
    assert!(r.failed.iter().any(|(p, _)| p == "sub/precious.txt"), "{:?}", r);
    intact(&o);                                                       // nothing was written through either symlink
    assert_eq!(fs::read_dir(&o).unwrap().count(), 3);                 // and no temp file was left there
    // the op that held the directory fd finished in the real (moved) directory, never in the symlink target
    assert_eq!(rd(t.home.join("sub2.moved/precious.txt")), "nieuw\n");
    let _ = rm_rf(&o);
}

#[test]
fn dir_to_symlink_race_is_refused() {
    if !overlay_or_skip("dir_to_symlink_race_is_refused") { return; }
    let o = outside("dirlink");
    let t = setup("dirswap", "mkdir d; chmod 755 d; mkdir weg; mkdir w; echo x > w/f");
    inpolder(&t, "chmod 700 d; rmdir weg; rm -r w; echo nu-een-bestand > w");
    let c = ch(&t); let all: Vec<String> = c.iter().map(|x| x.path.clone()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &all, &[]);
    let (h, o2) = (t.home.clone(), o.clone());
    let swap = move |name: &str| { let p = h.join(name); let _ = fs::rename(&p, h.join(format!("{name}.moved"))); std::os::unix::fs::symlink(&o2, &p).unwrap(); };
    let f = Faults::hook(move |pt| match pt { "chmod:d" => swap("d"), "pre-op:weg" => swap("weg"), "replace:w" => swap("w"), _ => {} });
    let r = apply_plan(&t.j, &t.home, &p, None, &f).unwrap();
    for x in ["d", "weg", "w"] { assert!(r.failed.iter().any(|(p, _)| p == x), "{x} not refused: {:?}", r); }
    intact(&o);
    assert!(fs::symlink_metadata(t.home.join("d")).unwrap().file_type().is_symlink());
    let _ = rm_rf(&o);
}

#[test]
fn journal_paths_are_validated() {
    let t = setup("badops", "echo x > f");
    let o = outside("ops");
    for bad in ["../escape", "/etc/passwd", "a/../../b", "./f", "a//b", ""] {
        let plan = Plan { ops: vec![Op { path: bad.into(), act: "delete".into(), pre: St::File { mode: 0o644, size: 0, hash: String::new() }, post: St::Absent, src: None }], ..Default::default() };
        let r = apply_plan(&t.j, &t.home, &plan, None, &Faults::none()).unwrap();
        assert_eq!(r.failed.len(), 1, "{bad}");
    }
    // a write whose source escapes the polder upper dir
    let plan = Plan { ops: vec![Op { path: "f".into(), act: "write".into(), pre: state_of(&t.home.join("f")).unwrap(),
        post: state_of(&o.join("precious.txt")).unwrap(), src: Some(o.join("precious.txt").to_string_lossy().into()) }], ..Default::default() };
    let r = apply_plan(&t.j, &t.home, &plan, None, &Faults::none()).unwrap(); assert_eq!(r.failed.len(), 1, "{:?}", r);
    assert_eq!(rd(t.home.join("f")), "x\n"); assert!(!valid_merge_id("../x") && rollback_in(&t.j, Some("../x"), &Faults::none()).is_err());
    let _ = rm_rf(&o);
}
