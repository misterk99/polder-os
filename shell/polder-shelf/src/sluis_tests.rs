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
fn ch(t: &T) -> Vec<Change> { changes_for(&t.home, &t.upper, &t.base).unwrap() }
fn get<'a>(c: &'a [Change], p: &str) -> &'a Change { c.iter().find(|x| x.path == p).unwrap_or_else(|| panic!("no change for {p}: {:?}", c.iter().map(|x| &x.path).collect::<Vec<_>>())) }
fn rd(p: PathBuf) -> String { fs::read_to_string(p).unwrap() }
fn merge_sel(t: &T, sel: &[&str], force: &[&str]) -> Report {
    let c = ch(t); let s: Vec<String> = sel.iter().map(|x| x.to_string()).collect(); let f: Vec<String> = force.iter().map(|x| x.to_string()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &s, &f);
    apply_plan(&t.j, &t.home, &p, None).unwrap()
}

#[test]
fn isolation_and_selective_merge() {
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
    let r = apply_plan(&t.j, &t.home, &p, None).unwrap();
    assert_eq!(r.failed.len(), 1); assert_eq!(rd(t.home.join("alleen-polder.txt")), "tussendoor\n");
}

fn snapshot(home: &Path) -> Vec<(String, St)> { scan(home).unwrap().into_iter().map(|(k, v)| (k, v.st)).collect() }

#[test]
fn interrupted_merge_rollback_and_resume() {
    let t = setup("crash", "echo 1 > a; echo 2 > b; echo 3 > c; echo 4 > weg; ln -s a l");
    inpolder(&t, "echo A > a; echo B > b; echo C > c; rm weg; mkdir -p nieuw/sub; echo n > nieuw/sub/n; ln -sfn b l; chmod 700 c");
    let before = snapshot(&t.home);
    let c = ch(&t);
    let all: Vec<String> = c.iter().map(|x| x.path.clone()).collect();
    let p = plan_for(&t.home, &t.upper, &c, &all, &[]);
    assert!(p.ops.len() >= 7, "{:?}", p.ops);
    // "crash" after 3 operations
    assert!(apply_plan(&t.j, &t.home, &p, Some(3)).unwrap_err().starts_with("CRASH"));
    assert!(pending_in(&t.j).is_some());
    assert_ne!(snapshot(&t.home), before);
    // a new merge is refused while one is pending
    assert!(apply_plan(&t.j, &t.home, &p, None).is_err());
    // rollback restores the vasteland exactly
    let r = rollback_in(&t.j, None).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(snapshot(&t.home), before);
    assert!(pending_in(&t.j).is_none());
    // crash again, this time resume
    assert!(apply_plan(&t.j, &t.home, &p, Some(4)).is_err());
    let r = resume_in(&t.j).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(rd(t.home.join("a")), "A\n"); assert_eq!(rd(t.home.join("nieuw/sub/n")), "n\n");
    assert!(!t.home.join("weg").exists()); assert_eq!(fs::read_link(t.home.join("l")).unwrap(), PathBuf::from("b"));
    assert_eq!(fs::metadata(t.home.join("c")).unwrap().permissions().mode() & 0o777, 0o700);
    // and a finished merge can be undone too
    let mid = r.merge_id.clone();
    let r = rollback_in(&t.j, Some(&mid)).unwrap(); assert!(r.failed.is_empty(), "{:?}", r.failed);
    assert_eq!(snapshot(&t.home), before);
}

#[test]
fn crash_mid_write_leaves_no_partial_file() {
    // a crash between writing the temp file and the rename: the target is intact and the temp file is cleaned up
    let t = setup("tmpfile", "echo origineel > f");
    inpolder(&t, "echo nieuw > f");
    let c = ch(&t); let p = plan_for(&t.home, &t.upper, &c, &["f".into()], &[]);
    assert!(apply_plan(&t.j, &t.home, &p, Some(0)).is_err());
    fs::write(t.home.join(format!(".f.sluis-{}", std::process::id())), "half").unwrap();
    assert_eq!(rd(t.home.join("f")), "origineel\n");
    rollback_in(&t.j, None).unwrap();
    assert_eq!(fs::read_dir(&t.home).unwrap().count(), 1);
    assert_eq!(rd(t.home.join("f")), "origineel\n");
}
