//! Polder Sluis engine: proefpolders (copy-on-write branches) of a user-selected folder ("vasteland"),
//! change detection (baseline vs vasteland vs polder), dry-run merge plans and a journaled, crash-safe merge.
//!
//! Storage: $XDG_DATA_HOME/polder-sluis/polders/<id>/
//!   meta.json  baseline.json  upper/ work/ (overlay of the project)  hupper/ hwork/ (overlay of $HOME, never merged)
//!   journal/<merge-id>/{plan.json,log,backup/,committed}   runs.log
//! The overlay is mounted only inside the bubblewrap runner (unprivileged user-namespace overlayfs), so the upper dir
//! holds exactly the polder's changes: regular files/symlinks/dirs, whiteouts (char 0:0) for deletions, and
//! "opaque" dirs (xattr user.overlay.opaque=y) that hide everything below them in the lower dir.
#![allow(dead_code)]
#[allow(unused_imports)] use crate::i18n::tr;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{Read, Write};
use std::os::unix::fs::{MetadataExt, PermissionsExt, FileTypeExt};
use std::path::{Path, PathBuf};

pub type Res<T> = Result<T, String>;
fn e<E: std::fmt::Display>(ctx: &str) -> impl Fn(E) -> String + '_ { move |x| format!("{ctx}: {x}") }

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "t")]
pub enum St {
    Absent,
    File { mode: u32, size: u64, hash: String },
    Link { target: String },
    Dir { mode: u32 },
}
impl St {
    pub fn is_absent(&self) -> bool { matches!(self, St::Absent) }
    pub fn kind(&self) -> &'static str { match self { St::Absent => "-", St::File { .. } => "bestand", St::Link { .. } => "symlink", St::Dir { .. } => "map" } }
    /// same content/type, ignoring mode
    fn same_content(&self, o: &St) -> bool {
        match (self, o) {
            (St::File { hash: a, .. }, St::File { hash: b, .. }) => a == b,
            (St::Dir { .. }, St::Dir { .. }) => true,
            _ => self == o,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Entry { pub st: St, pub mtime: i64, pub ino: u64 }

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct Meta {
    pub id: String, pub name: String, pub description: String, pub origin: String,
    pub created: i64, pub archived: bool, pub network: bool, #[serde(default)] pub runs: Vec<String>,
}

pub fn now() -> i64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0) }
pub fn data_dir() -> PathBuf {
    if let Ok(d) = std::env::var("POLDER_SLUIS_DIR") { return PathBuf::from(d); }
    let base = std::env::var("XDG_DATA_HOME").map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local/share"));
    base.join("polder-sluis")
}
pub fn pdir(id: &str) -> PathBuf { data_dir().join("polders").join(id) }

// ---------------------------------------------------------------- hashing / state
pub fn hash_file(p: &Path) -> Res<String> {
    let mut f = fs::File::open(p).map_err(e(tr("open")))?;
    let mut c = glib::Checksum::new(glib::ChecksumType::Sha256).ok_or(tr("no sha256"))?;
    let mut buf = vec![0u8; 1 << 16];
    loop { let n = f.read(&mut buf).map_err(e("lezen"))?; if n == 0 { break; } c.update(&buf[..n]); }
    Ok(c.string().map(|s| s.to_string()).unwrap_or_default())
}
pub fn state_of(p: &Path) -> Res<St> {
    let m = match fs::symlink_metadata(p) { Ok(m) => m, Err(x) if x.kind() == std::io::ErrorKind::NotFound => return Ok(St::Absent), Err(x) => return Err(format!("{}: {x}", p.display())) };
    let ft = m.file_type();
    Ok(if ft.is_symlink() { St::Link { target: fs::read_link(p).map_err(e("readlink"))?.to_string_lossy().into() } }
       else if ft.is_dir() { St::Dir { mode: m.mode() & 0o7777 } }
       else if ft.is_file() { St::File { mode: m.mode() & 0o7777, size: m.len(), hash: hash_file(p)? } }
       else { return Err(tf!("{}: unsupported file type (device/fifo/socket)", p.display())) })
}
/// state using the baseline as a cache: same size+mtime+inode => same hash (like git's stat cache)
fn state_cached(p: &Path, base: Option<&Entry>) -> Res<St> {
    if let (Some(b), Ok(m)) = (base, fs::symlink_metadata(p)) {
        if let St::File { mode: _, size, hash } = &b.st {
            if m.file_type().is_file() && m.len() == *size && m.mtime() * 1_000_000_000 + m.mtime_nsec() == b.mtime && m.ino() == b.ino {
                return Ok(St::File { mode: m.mode() & 0o7777, size: *size, hash: hash.clone() });
            }
        }
    }
    state_of(p)
}

/// Walk a tree: relative path -> Entry (the root itself is not included)
pub fn scan(root: &Path) -> Res<BTreeMap<String, Entry>> {
    let mut out = BTreeMap::new();
    fn walk(root: &Path, rel: &str, out: &mut BTreeMap<String, Entry>) -> Res<()> {
        let dir = if rel.is_empty() { root.to_path_buf() } else { root.join(rel) };
        let mut names: Vec<_> = fs::read_dir(&dir).map_err(|x| format!("{}: {x}", dir.display()))?.filter_map(|d| d.ok()).collect();
        names.sort_by_key(|d| d.file_name());
        for d in names {
            let name = d.file_name().to_string_lossy().to_string();
            let r = if rel.is_empty() { name } else { format!("{rel}/{name}") };
            let p = root.join(&r);
            let m = fs::symlink_metadata(&p).map_err(e("stat"))?;
            let st = match state_of(&p) { Ok(s) => s, Err(_) => continue };   // skip sockets/fifos
            out.insert(r.clone(), Entry { st: st.clone(), mtime: m.mtime() * 1_000_000_000 + m.mtime_nsec(), ino: m.ino() });
            if matches!(st, St::Dir { .. }) { walk(root, &r, out)?; }
        }
        Ok(())
    }
    walk(root, "", &mut out)?;
    Ok(out)
}

// ---------------------------------------------------------------- polder lifecycle
fn slug(name: &str) -> String {
    let s: String = name.to_lowercase().chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect();
    let s = s.split('-').filter(|x| !x.is_empty()).collect::<Vec<_>>().join("-");
    if s.is_empty() { "polder".into() } else { s.chars().take(40).collect() }
}
pub fn write_json<T: Serialize>(p: &Path, v: &T) -> Res<()> {
    let tmp = p.with_extension("tmp");
    let mut f = fs::File::create(&tmp).map_err(e("schrijven"))?;
    f.write_all(serde_json::to_string_pretty(v).unwrap().as_bytes()).map_err(e("schrijven"))?;
    f.sync_all().ok(); fs::rename(&tmp, p).map_err(e("hernoemen"))
}
pub fn read_json<T: for<'a> Deserialize<'a>>(p: &Path) -> Res<T> {
    serde_json::from_str(&fs::read_to_string(p).map_err(|x| format!("{}: {x}", p.display()))?).map_err(|x| format!("{}: {x}", p.display()))
}
pub fn meta(id: &str) -> Res<Meta> { read_json(&pdir(id).join("meta.json")) }
pub fn save_meta(m: &Meta) -> Res<()> { write_json(&pdir(&m.id).join("meta.json"), m) }
pub fn baseline(id: &str) -> Res<BTreeMap<String, Entry>> { read_json(&pdir(id).join("baseline.json")) }

pub fn list() -> Vec<Meta> {
    let mut v: Vec<Meta> = fs::read_dir(data_dir().join("polders")).map(|r| r.filter_map(|d| d.ok()).filter_map(|d| meta(&d.file_name().to_string_lossy()).ok()).collect()).unwrap_or_default();
    v.sort_by_key(|m| -m.created); v
}

pub fn create(name: &str, origin: &Path, description: &str) -> Res<Meta> {
    let origin = fs::canonicalize(origin).map_err(|x| format!("{}: {x}", origin.display()))?;
    if !origin.is_dir() { return Err(tr("Choose a folder.").into()); }
    let home = fs::canonicalize(std::env::var("HOME").unwrap_or_default()).unwrap_or_default();
    let dd = data_dir(); fs::create_dir_all(dd.join("polders")).map_err(e(tr("create folder")))?;
    let ddc = fs::canonicalize(&dd).unwrap_or(dd.clone());
    if origin == Path::new("/") || origin == home { return Err(tr("A test polder of your whole home folder or the whole system is not possible; choose a project folder.").into()); }
    if ddc.starts_with(&origin) || origin.starts_with(&ddc) { return Err(tr("This folder contains Sluis's own storage.").into()); }
    let mut id = slug(name); let mut i = 2;
    while pdir(&id).exists() { id = format!("{}-{i}", slug(name)); i += 1; }
    let d = pdir(&id);
    for s in ["upper", "work", "hupper", "hwork", "journal"] { fs::create_dir_all(d.join(s)).map_err(e(tr("create folder")))?; }
    let base = scan(&origin)?;
    write_json(&d.join("baseline.json"), &base)?;
    let m = Meta { id, name: name.into(), description: description.into(), origin: origin.to_string_lossy().into(), created: now(), ..Default::default() };
    save_meta(&m)?;
    Ok(m)
}

pub fn rm_rf(p: &Path) -> Res<()> {
    // overlay work dirs can contain mode-000 dirs: make writable first
    fn fix(p: &Path) { if let Ok(rd) = fs::read_dir(p) { for d in rd.flatten() {
        let q = d.path(); if let Ok(m) = fs::symlink_metadata(&q) { if m.is_dir() { let _ = fs::set_permissions(&q, fs::Permissions::from_mode(0o700)); fix(&q); } } } } }
    if !p.exists() { return Ok(()); }
    let _ = fs::set_permissions(p, fs::Permissions::from_mode(0o700)); fix(p);
    fs::remove_dir_all(p).map_err(|x| format!("{}: {x}", p.display()))
}
pub fn discard(id: &str) -> Res<()> {
    if pending_merge(id).is_some() { return Err(tr("There is an interrupted merge; finish or undo it first.").into()); }
    rm_rf(&pdir(id))
}
pub fn archive(id: &str, on: bool) -> Res<Meta> { let mut m = meta(id)?; m.archived = on; save_meta(&m)?; Ok(m) }
pub fn disk_usage(p: &Path) -> u64 {
    let mut n = 0;
    if let Ok(m) = fs::symlink_metadata(p) { n += m.blocks() * 512; if m.is_dir() { if let Ok(rd) = fs::read_dir(p) { for d in rd.flatten() { n += disk_usage(&d.path()); } } } }
    n
}

// ---------------------------------------------------------------- polder (upper) state
fn is_whiteout(m: &fs::Metadata) -> bool { m.file_type().is_char_device() && m.rdev() == 0 }
fn is_opaque(p: &Path) -> bool {
    use std::ffi::CString;
    let c = CString::new(p.as_os_str().to_string_lossy().as_bytes()).unwrap();
    for name in ["user.overlay.opaque", "trusted.overlay.opaque"] {
        let n = CString::new(name).unwrap(); let mut b = [0u8; 4];
        let r = unsafe { libc::lgetxattr(c.as_ptr(), n.as_ptr(), b.as_mut_ptr() as *mut libc::c_void, b.len()) };
        if r > 0 && b[0] == b'y' { return true; }
    }
    false
}

/// What the polder says about each path it touched: path -> polder state (Absent = deleted in the polder)
pub fn branch_states(upper: &Path, base: &BTreeMap<String, Entry>) -> Res<BTreeMap<String, St>> {
    let mut out = BTreeMap::new();
    fn walk(upper: &Path, rel: &str, base: &BTreeMap<String, Entry>, out: &mut BTreeMap<String, St>) -> Res<()> {
        let dir = if rel.is_empty() { upper.to_path_buf() } else { upper.join(rel) };
        let rd = match fs::read_dir(&dir) { Ok(r) => r, Err(_) => return Ok(()) };
        for d in rd.flatten() {
            let name = d.file_name().to_string_lossy().to_string();
            let r = if rel.is_empty() { name } else { format!("{rel}/{name}") };
            let p = upper.join(&r);
            let m = fs::symlink_metadata(&p).map_err(e("stat"))?;
            let prefix = format!("{r}/");
            if is_whiteout(&m) {
                out.insert(r.clone(), St::Absent);
                for k in base.range(prefix.clone()..).map(|(k, _)| k).take_while(|k| k.starts_with(&prefix)) { out.insert(k.clone(), St::Absent); }
                continue;
            }
            let st = state_of(&p)?;
            let isdir = matches!(st, St::Dir { .. });
            out.insert(r.clone(), st);
            if isdir {
                if is_opaque(&p) {   // dir was removed and recreated: everything below from the lower dir is gone
                    for k in base.range(prefix.clone()..).map(|(k, _)| k).take_while(|k| k.starts_with(&prefix)) { out.insert(k.clone(), St::Absent); }
                }
                walk(upper, &r, base, out)?;
            } else {
                // a file/link replaced a lower dir: the lower children are gone
                for k in base.range(prefix.clone()..).map(|(k, _)| k).take_while(|k| k.starts_with(&prefix)) { out.insert(k.clone(), St::Absent); }
            }
        }
        Ok(())
    }
    walk(upper, "", base, &mut out)?;
    Ok(out)
}

// ---------------------------------------------------------------- three-way change list
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Change {
    pub path: String,
    pub kind: String,          // toegevoegd | gewijzigd | verwijderd | rechten | type | hernoemd
    pub base: St, pub home: St, pub branch: St,
    pub conflict: bool,        // changed in both vasteland and polder, differently
    pub home_changed: bool,    // vasteland changed since the polder was made
    #[serde(default)] pub renamed_from: Option<String>,
    pub warnings: Vec<String>,
}

pub fn changes_for(origin: &Path, upper: &Path, base: &BTreeMap<String, Entry>) -> Res<Vec<Change>> {
    let br = branch_states(upper, base)?;
    let mut out = vec![];
    for (p, b) in &br {
        let be = base.get(p);
        let bs = be.map(|x| x.st.clone()).unwrap_or(St::Absent);
        if *b == bs { continue; }                                   // copied up but unchanged (e.g. only atime/mtime)
        if matches!((b, &bs), (St::Dir { .. }, St::Absent)) {
            // new dir: only report it when empty (otherwise its contents carry the change)
            let pre = format!("{p}/"); if br.range(pre.clone()..).next().map(|(k, _)| k.starts_with(&pre)).unwrap_or(false) { continue; }
        }
        let hs = state_cached(&origin.join(p), be)?;
        let kind = match (&bs, b) {
            (St::Absent, _) => "toegevoegd",
            (_, St::Absent) => "verwijderd",
            (x, y) if x.same_content(y) => "rechten",
            (x, y) if x.kind() != y.kind() => "type",
            _ => "gewijzigd",
        };
        let home_changed = hs != bs;
        let conflict = home_changed && hs != *b;
        let mut w = vec![];
        if matches!(b, St::Link { .. }) || matches!(bs, St::Link { .. }) {
            if let St::Link { target } = b { if target.starts_with('/') || target.split('/').any(|c| c == "..") { w.push(tf!("symlink points outside the folder: {target}" ; target)); } else { w.push("symlink".into()); } } else { w.push("symlink".into()); }
        }
        if kind == "verwijderd" { w.push(tr("deletes a file on the mainland").into()); }
        if kind == "rechten" || matches!((&bs, b), (St::File { mode: a, .. }, St::File { mode: c, .. }) if a != c) { w.push(tr("changes permissions").into()); }
        if let St::File { mode, .. } = b { if mode & 0o6000 != 0 { w.push("setuid/setgid-bit".into()); } }
        if !bs.is_absent() && !b.is_absent() && kind != "rechten" { w.push(tr("overwrites a file on the mainland").into()); }
        if conflict { w.push(tr("also changed on the mainland").into()); }
        out.push(Change { path: p.clone(), kind: kind.into(), base: bs, home: hs, branch: b.clone(), conflict, home_changed, renamed_from: None, warnings: w });
    }
    // rename detection: a deleted file and an added file with the same content
    let deleted: Vec<(usize, String)> = out.iter().enumerate().filter(|(_, c)| c.kind == "verwijderd").filter_map(|(i, c)| if let St::File { hash, .. } = &c.base { Some((i, hash.clone())) } else { None }).collect();
    let mut used = BTreeSet::new();
    for i in 0..out.len() {
        if out[i].kind != "toegevoegd" { continue; }
        if let St::File { hash, .. } = out[i].branch.clone() {
            if let Some((j, _)) = deleted.iter().find(|(j, h)| *h == hash && !used.contains(j)) {
                used.insert(*j); out[i].kind = "hernoemd".into(); out[i].renamed_from = Some(out[*j].path.clone());
            }
        }
    }
    Ok(out)
}
pub fn changes(id: &str) -> Res<Vec<Change>> {
    let m = meta(id)?; changes_for(Path::new(&m.origin), &pdir(id).join("upper"), &baseline(id)?)
}
pub fn status_of(ch: &[Change], m: &Meta) -> &'static str {
    if m.archived { "Gearchiveerd" } else if ch.iter().any(|c| c.conflict) { "Conflict" }
    else if ch.iter().any(|c| c.home != c.branch) { "Klaar om over te nemen" } else { "Actief" }
}

// ---------------------------------------------------------------- merge plan (dry run)
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Op { pub path: String, pub act: String, pub pre: St, pub post: St, pub src: Option<String> }
#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct Plan { pub ops: Vec<Op>, pub warnings: Vec<String>, pub skipped: Vec<(String, String)> }

/// Build the ops for the selected paths. A conflict is only taken when listed in `force` (explicit "polderversie kiezen").
pub fn plan_for(origin: &Path, upper: &Path, ch: &[Change], selected: &[String], force: &[String]) -> Plan {
    let mut plan = Plan::default();
    let mut sel: BTreeSet<String> = selected.iter().cloned().collect();
    for c in ch { if let Some(f) = &c.renamed_from { if sel.contains(&c.path) { sel.insert(f.clone()); } } }  // a rename = add + delete
    let mut want: Vec<&Change> = ch.iter().filter(|c| sel.contains(&c.path)).collect();
    want.sort_by(|a, b| a.path.cmp(&b.path));
    let mut dirs_needed = BTreeSet::new();
    for c in &want {
        if c.home == c.branch { plan.skipped.push((c.path.clone(), tr("already identical on the mainland").into())); continue; }
        if c.conflict && !force.contains(&c.path) { plan.skipped.push((c.path.clone(), tr("conflict: also changed on the mainland").into())); continue; }
        for w in &c.warnings { plan.warnings.push(format!("{}: {w}", c.path)); }
        // parents that do not exist on the vasteland yet
        let mut acc = String::new();
        let parts: Vec<&str> = c.path.split('/').collect();
        if !c.branch.is_absent() { for p in &parts[..parts.len() - 1] {
            acc = if acc.is_empty() { p.to_string() } else { format!("{acc}/{p}") };
            if fs::symlink_metadata(origin.join(&acc)).is_err() && dirs_needed.insert(acc.clone()) {
                let mode = match state_of(&upper.join(&acc)) { Ok(St::Dir { mode }) => mode, _ => 0o755 };
                plan.ops.push(Op { path: acc.clone(), act: "mkdir".into(), pre: St::Absent, post: St::Dir { mode }, src: None });
            }
        } }
        let act = match (&c.home, &c.branch) {
            (_, St::Absent) => if matches!(c.home, St::Dir { .. }) { "rmdir" } else { "delete" },
            (St::Dir { .. }, St::Dir { .. }) => "chmod",
            (St::File { hash: a, .. }, St::File { hash: b, .. }) if a == b => "chmod",
            (_, St::Dir { .. }) => "mkdir",
            _ => "write",
        };
        if c.home.is_absent() && c.branch.is_absent() { continue; }
        plan.ops.push(Op { path: c.path.clone(), act: act.into(), pre: c.home.clone(), post: c.branch.clone(),
                           src: if act == "write" { Some(upper.join(&c.path).to_string_lossy().into()) } else { None } });
    }
    // order: mkdir/write/chmod top-down, then deletions deepest first
    let (mut del, mut rest): (Vec<Op>, Vec<Op>) = plan.ops.drain(..).partition(|o| o.act == "delete" || o.act == "rmdir");
    rest.sort_by(|a, b| (a.path.matches('/').count(), a.act != "mkdir", a.path.clone()).cmp(&(b.path.matches('/').count(), b.act != "mkdir", b.path.clone())));
    del.sort_by(|a, b| b.path.matches('/').count().cmp(&a.path.matches('/').count()).then(b.path.cmp(&a.path)));
    plan.ops = rest; plan.ops.extend(del);
    plan
}
pub fn plan(id: &str, selected: &[String], force: &[String]) -> Res<Plan> {
    let m = meta(id)?; let ch = changes(id)?;
    Ok(plan_for(Path::new(&m.origin), &pdir(id).join("upper"), &ch, selected, force))
}

// ---------------------------------------------------------------- journaled apply
#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct Report { pub merge_id: String, pub done: Vec<String>, pub failed: Vec<(String, String)>, pub skipped: Vec<(String, String)>, pub rolled_back: bool }

fn fsync_dir(p: &Path) { if let Ok(f) = fs::File::open(p) { let _ = f.sync_all(); } }
fn log_line(j: &Path, s: &str) -> Res<()> {
    let mut f = fs::OpenOptions::new().create(true).append(true).open(j.join("log")).map_err(e("journal"))?;
    writeln!(f, "{s}").map_err(e("journal"))?; f.sync_all().map_err(e("journal"))
}
fn backup(j: &Path, n: usize, target: &Path) -> Res<()> {
    let b = j.join("backup").join(n.to_string());
    if b.symlink_metadata().is_ok() { return Ok(()); }                            // already taken (resume)
    let m = match fs::symlink_metadata(target) { Ok(m) => m, Err(_) => return Ok(()) };
    if m.is_dir() { return Ok(()); }
    let tmp = j.join("backup").join(format!("{n}.tmp"));
    let _ = fs::remove_file(&tmp);
    if m.file_type().is_symlink() { std::os::unix::fs::symlink(fs::read_link(target).map_err(e("readlink"))?, &tmp).map_err(e("backup"))?; }
    else if fs::hard_link(target, &tmp).is_err() { fs::copy(target, &tmp).map_err(e("backup"))?; fs::File::open(&tmp).and_then(|f| f.sync_all()).ok(); }
    fs::rename(&tmp, &b).map_err(e("backup"))?; fsync_dir(&j.join("backup"));
    Ok(())
}
fn tmp_name(target: &Path) -> PathBuf {
    let n = target.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    target.with_file_name(format!(".{n}.sluis-{}", std::process::id()))
}
fn apply_op(origin: &Path, o: &Op) -> Res<()> {
    let t = origin.join(&o.path);
    match o.act.as_str() {
        "mkdir" => { if let St::Dir { mode } = o.post { fs::create_dir(&t).map_err(e(tr("create folder")))?; fs::set_permissions(&t, fs::Permissions::from_mode(mode)).map_err(e(tr("permissions")))?; } }
        "chmod" => { let mode = match &o.post { St::Dir { mode } | St::File { mode, .. } => *mode, _ => 0o644 }; fs::set_permissions(&t, fs::Permissions::from_mode(mode)).map_err(e(tr("permissions")))?; }
        "delete" => { fs::remove_file(&t).map_err(e(tr("delete")))?; }
        "rmdir" => { fs::remove_dir(&t).map_err(|x| tf!("folder is not empty on the mainland (it contains files the polder does not know): {x}" ; x))?; }
        "write" => {
            let tmp = tmp_name(&t); let _ = fs::remove_file(&tmp);
            match &o.post {
                St::Link { target } => std::os::unix::fs::symlink(target, &tmp).map_err(e("symlink"))?,
                St::File { mode, hash, .. } => {
                    let src = PathBuf::from(o.src.as_ref().ok_or(tr("no source"))?);
                    fs::copy(&src, &tmp).map_err(e(tr("copy")))?;
                    let f = fs::File::open(&tmp).map_err(e(tr("copy")))?; f.sync_all().ok();
                    fs::set_permissions(&tmp, fs::Permissions::from_mode(*mode)).map_err(e(tr("permissions")))?;
                    if hash_file(&tmp)? != *hash { let _ = fs::remove_file(&tmp); return Err(tr("the file in the polder has changed meanwhile; review the changes again").into()); }
                }
                _ => return Err(tr("unknown operation").into()),
            }
            if let St::Dir { .. } = o.pre { fs::remove_dir(&t).map_err(e(tr("replace folder")))?; }
            fs::rename(&tmp, &t).map_err(e(tr("replace")))?;   // atomic replace
        }
        x => return Err(format!("onbekende bewerking {x}")),
    }
    if let Some(p) = t.parent() { fsync_dir(p); }
    Ok(())
}
fn now_state(origin: &Path, o: &Op) -> St { state_of(&origin.join(&o.path)).unwrap_or(St::Absent) }

/// Test hook: stop (like a crash) after n ops. Set by tests or by POLDER_SLUIS_CRASH_AFTER for the CLI crash test.
pub fn crash_after() -> Option<usize> { std::env::var("POLDER_SLUIS_CRASH_AFTER").ok().and_then(|s| s.parse().ok()) }

pub fn apply_plan(jroot: &Path, origin: &Path, plan: &Plan, crash: Option<usize>) -> Res<Report> {
    if let Some(p) = pending_in(jroot) { return Err(tf!("interrupted merge {p} must be finished or rolled back first" ; p)); }
    static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let ns = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let mid = format!("{ns}-{}-{}", std::process::id(), SEQ.fetch_add(1, std::sync::atomic::Ordering::SeqCst));
    let j = jroot.join(&mid);
    if j.exists() { return Err("journal bestaat al".into()); }
    fs::create_dir_all(j.join("backup")).map_err(e("journal"))?;
    write_json(&j.join("plan.json"), &(origin.to_string_lossy().to_string(), plan))?;
    fsync_dir(&j); fsync_dir(jroot);
    run_ops(&j, origin, plan, 0, crash, mid)
}
fn run_ops(j: &Path, origin: &Path, plan: &Plan, start: usize, crash: Option<usize>, mid: String) -> Res<Report> {
    let mut r = Report { merge_id: mid, skipped: plan.skipped.clone(), ..Default::default() };
    let done_before = done_set(j);
    for (n, o) in plan.ops.iter().enumerate().skip(start) {
        if let Some(c) = crash { if n >= c { return Err(format!("CRASH (test) na {c} bewerkingen")); } }
        if done_before.contains(&n) { r.done.push(o.path.clone()); continue; }
        let cur = now_state(origin, o);
        if cur == o.post { log_line(j, &format!("done {n}"))?; r.done.push(o.path.clone()); continue; }   // already applied (resume)
        if cur != o.pre && !(o.act == "chmod" && cur.same_content(&o.pre)) {
            log_line(j, &format!("fail {n}"))?; r.failed.push((o.path.clone(), tr("the mainland has changed meanwhile; not touched").into())); continue;
        }
        backup(j, n, &origin.join(&o.path))?;
        log_line(j, &format!("start {n}"))?;
        match apply_op(origin, o) {
            Ok(()) => { log_line(j, &format!("done {n}"))?; r.done.push(o.path.clone()); }
            Err(x) => { log_line(j, &format!("fail {n}"))?; r.failed.push((o.path.clone(), x)); }
        }
    }
    fs::write(j.join("committed"), b"").map_err(e("journal"))?; fsync_dir(j);
    write_json(&j.join("report.json"), &r)?;
    Ok(r)
}
fn done_set(j: &Path) -> BTreeSet<usize> {
    fs::read_to_string(j.join("log")).unwrap_or_default().lines().filter_map(|l| l.strip_prefix("done ").and_then(|n| n.parse().ok())).collect()
}
pub fn pending_in(jroot: &Path) -> Option<String> {
    let mut v: Vec<String> = fs::read_dir(jroot).ok()?.flatten().filter(|d| d.path().join("plan.json").exists() && !d.path().join("committed").exists() && !d.path().join("rolledback").exists())
        .map(|d| d.file_name().to_string_lossy().to_string()).collect();
    v.sort(); v.pop()
}
pub fn pending_merge(id: &str) -> Option<String> { pending_in(&pdir(id).join("journal")) }

/// Continue an interrupted merge where it stopped (ops are idempotent: already-applied ones are recognised).
pub fn resume_in(jroot: &Path) -> Res<Report> {
    let mid = pending_in(jroot).ok_or(tr("no interrupted merge"))?;
    let j = jroot.join(&mid);
    let (origin, plan): (String, Plan) = read_json(&j.join("plan.json"))?;
    run_ops(&j, Path::new(&origin), &plan, 0, None, mid)
}
/// Undo an interrupted (or finished) merge: every op whose result is present is reverted from the journal backups.
pub fn rollback_in(jroot: &Path, mid: Option<&str>) -> Res<Report> {
    let mid = match mid { Some(m) => m.to_string(), None => pending_in(jroot).ok_or(tr("no interrupted merge"))? };
    let j = jroot.join(&mid);
    let (origin, plan): (String, Plan) = read_json(&j.join("plan.json"))?;
    let origin = PathBuf::from(origin);
    let mut r = Report { merge_id: mid, rolled_back: true, ..Default::default() };
    for (n, o) in plan.ops.iter().enumerate().rev() {
        let t = origin.join(&o.path);
        let cur = now_state(&origin, o);
        let _ = fs::remove_file(tmp_name(&t));                       // half-written temp file of a crashed write
        if cur == o.pre { continue; }                                 // never applied
        if cur != o.post && !(o.act == "chmod" && cur.same_content(&o.post)) { r.failed.push((o.path.clone(), tr("changed after the merge; not restored").into())); continue; }
        let res: Res<()> = (|| {
            match (&o.pre, o.act.as_str()) {
                (St::Absent, _) => { if matches!(o.post, St::Dir { .. }) { fs::remove_dir(&t).map_err(e(tr("remove folder"))) } else { fs::remove_file(&t).map_err(e(tr("delete"))) } }
                (St::Dir { mode }, "chmod") | (St::Dir { mode }, "rmdir") => { if o.act == "rmdir" { fs::create_dir(&t).map_err(e("map"))?; } fs::set_permissions(&t, fs::Permissions::from_mode(*mode)).map_err(e(tr("permissions"))) }
                (St::File { mode, .. }, "chmod") => fs::set_permissions(&t, fs::Permissions::from_mode(*mode)).map_err(e(tr("permissions"))),
                (St::Dir { .. }, _) => { if cur.kind() != "map" { let _ = fs::remove_file(&t); } fs::create_dir_all(&t).map_err(e("map")) }
                _ => { let b = j.join("backup").join(n.to_string()); if matches!(cur, St::Dir { .. }) { fs::remove_dir(&t).map_err(e("map"))?; } fs::rename(&b, &t).map_err(|x| tf!("restoring backup: {x}" ; x)) }
            }
        })();
        match res { Ok(()) => r.done.push(o.path.clone()), Err(x) => r.failed.push((o.path.clone(), x)) }
        if let Some(p) = t.parent() { fsync_dir(p); }
    }
    fs::write(j.join("rolledback"), b"").map_err(e("journal"))?; fsync_dir(&j);
    Ok(r)
}
/// After a merge the merged paths are the new common ancestor: later polder edits to them are not conflicts.
pub fn rebase(base: &mut BTreeMap<String, Entry>, origin: &Path, paths: &[String]) {
    for p in paths {
        let f = origin.join(p);
        match (state_of(&f), fs::symlink_metadata(&f)) {
            (Ok(st), Ok(m)) if !st.is_absent() => { base.insert(p.clone(), Entry { st, mtime: m.mtime() * 1_000_000_000 + m.mtime_nsec(), ino: m.ino() }); }
            _ => { base.remove(p); }
        }
    }
}
pub fn merge(id: &str, selected: &[String], force: &[String]) -> Res<Report> {
    let m = meta(id)?; if m.archived { return Err(tr("This test polder is archived.").into()); }
    let p = plan(id, selected, force)?;
    let jroot = pdir(id).join("journal");
    let saved = fs::read(pdir(id).join("baseline.json")).map_err(e("baseline"))?;
    let r = apply_plan(&jroot, Path::new(&m.origin), &p, crash_after())?;
    fs::write(jroot.join(&r.merge_id).join("baseline.before.json"), saved).map_err(e("journal"))?;
    let mut b = baseline(id)?; rebase(&mut b, Path::new(&m.origin), &r.done);
    write_json(&pdir(id).join("baseline.json"), &b)?;
    Ok(r)
}
/// Undo a merge for a polder, including its baseline update.
pub fn rollback(id: &str, mid: Option<&str>) -> Res<Report> {
    let jroot = pdir(id).join("journal");
    let r = rollback_in(&jroot, mid)?;
    let saved = jroot.join(&r.merge_id).join("baseline.before.json");
    if saved.exists() { fs::copy(&saved, pdir(id).join("baseline.json")).map_err(e("baseline"))?; }
    Ok(r)
}
pub fn resume(id: &str) -> Res<Report> {
    let jroot = pdir(id).join("journal");
    let saved = fs::read(pdir(id).join("baseline.json")).map_err(e("baseline"))?;
    let r = resume_in(&jroot)?;
    fs::write(jroot.join(&r.merge_id).join("baseline.before.json"), saved).map_err(e("journal"))?;
    let m = meta(id)?; let mut b = baseline(id)?; rebase(&mut b, Path::new(&m.origin), &r.done);
    write_json(&pdir(id).join("baseline.json"), &b)?;
    Ok(r)
}

// ---------------------------------------------------------------- runner (bubblewrap)
pub fn runner_argv(m: &Meta, net: bool, cmd: &[String]) -> Vec<String> {
    let d = pdir(&m.id);
    let home = std::env::var("HOME").unwrap_or_default();
    let rt = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| format!("/run/user/{}", unsafe { libc::getuid() }));
    let s = |p: &Path| p.to_string_lossy().to_string();
    let mut a: Vec<String> = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"].iter().map(|x| x.to_string()).collect();
    if net { a.push("--share-net".into()); }
    // the rest of $HOME: copy-on-write too, kept in the polder but never merged; Sluis' own storage is hidden
    a.extend(["--overlay-src".into(), home.clone(), "--overlay".into(), s(&d.join("hupper")), s(&d.join("hwork")), home.clone()]);
    a.extend(["--tmpfs".into(), s(&data_dir())]);
    // the project folder: the overlay that Sluis tracks
    a.extend(["--overlay-src".into(), m.origin.clone(), "--overlay".into(), s(&d.join("upper")), s(&d.join("work")), m.origin.clone()]);
    // only the Wayland socket from the runtime dir (no session D-Bus, no host sockets)
    a.extend(["--tmpfs".into(), rt.clone(), "--chmod".into(), "0700".into(), rt.clone()]);
    if let Ok(w) = std::env::var("WAYLAND_DISPLAY") { let sock = if w.starts_with('/') { w.clone() } else { format!("{rt}/{w}") }; a.extend(["--ro-bind".into(), sock.clone(), sock]); }
    a.extend(["--setenv".into(), "POLDER_SLUIS".into(), m.name.clone(), "--setenv".into(), "POLDER_SLUIS_ID".into(), m.id.clone(),
              "--unsetenv".into(), "DBUS_SESSION_BUS_ADDRESS".into(), "--unsetenv".into(), "DISPLAY".into(),
              "--setenv".into(), "PS1".into(), format!("[polder {}] \\w \\$ ", m.name), "--chdir".into(), m.origin.clone()]);
    a.push("--".into()); a.extend(cmd.iter().cloned());
    a
}
