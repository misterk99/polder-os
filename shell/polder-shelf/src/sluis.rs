//! Polder Sluis engine: proefpolders (copy-on-write branches) of a user-selected folder ("vasteland"),
//! change detection (baseline vs vasteland vs polder), dry-run merge plans and a journaled, crash-safe merge.
//!
//! Storage: $XDG_DATA_HOME/polder-sluis/polders/<id>/
//!   meta.json  baseline.json  upper/ work/ (overlay of the project)  hupper/ hwork/ (overlay of $HOME, never merged)
//!   journal/<merge-id>/{plan.json,state,log,backup/,report.json,baseline.before.json,rollback.json}   runs.log
//! The overlay is mounted only inside the bubblewrap runner (unprivileged user-namespace overlayfs), so the upper dir
//! holds exactly the polder's changes: regular files/symlinks/dirs, whiteouts (char 0:0) for deletions, and
//! "opaque" dirs (xattr user.overlay.opaque=y) that hide everything below them in the lower dir.
//!
//! Safety rules (see docs/sluis.md):
//! * polder ids are strict slugs and must name a real directory directly inside the canonical `polders` dir;
//!   symlinked entries are never followed, deletion is fd-relative and no-follow (`rm_rf`).
//! * every mainland mutation is done relative to an O_NOFOLLOW directory fd walked component by component from the
//!   project root, after re-checking the exact precondition (type, mode, content) on that fd.
//! * a merge is one recoverable state machine: applying -> applied -> reconciled -> committed; a rollback is
//!   rolling-back -> rolled-back, or rollback-partial (still pending, retryable, failures kept in rollback.json).
#![allow(dead_code)]
#[allow(unused_imports)] use crate::i18n::tr;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{CStr, CString};
use std::fs;
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{MetadataExt, PermissionsExt, FileTypeExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;

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
    /// Same type and content. Files ignore the mode (a mode-only difference is a "rechten" change);
    /// directories have no content, so they are only the same when type AND mode are equal.
    /// Never used as a merge precondition: preconditions are exact (`==`).
    fn same_content(&self, o: &St) -> bool {
        match (self, o) {
            (St::File { hash: a, size: x, .. }, St::File { hash: b, size: y, .. }) => a == b && x == y,
            _ => self == o,
        }
    }
    fn mode(&self) -> Option<u32> { match self { St::File { mode, .. } | St::Dir { mode } => Some(*mode), _ => None } }
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

// ---------------------------------------------------------------- ids and containment
/// A polder id is a strict slug: 1..=64 of [a-z0-9-], starting with [a-z0-9]. This rejects separators, ".", "..",
/// absolute paths, NUL, whitespace and anything non-ASCII.
pub fn valid_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty() && b.len() <= 64 && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
}
/// Merge ids are generated as <nanos>-<pid>-<seq>.
pub fn valid_merge_id(m: &str) -> bool { !m.is_empty() && m.len() <= 64 && m.bytes().all(|c| c.is_ascii_digit() || c == b'-') && !m.starts_with('-') }
fn polders_root() -> Res<PathBuf> {
    let r = data_dir().join("polders");
    fs::canonicalize(&r).map_err(|x| format!("{}: {x}", r.display()))
}
/// The inventory: ids of the real (non-symlink) directories directly inside the polders dir.
pub fn ids() -> Vec<String> {
    let Ok(root) = polders_root() else { return vec![] };
    let mut v: Vec<String> = fs::read_dir(&root).map(|r| r.flatten()
        .filter(|d| d.file_type().map(|t| t.is_dir()).unwrap_or(false))      // DirEntry::file_type does not follow symlinks
        .filter_map(|d| d.file_name().to_str().map(String::from)).filter(|n| valid_id(n)).collect()).unwrap_or_default();
    v.sort(); v
}
/// Resolve a polder's directory. Only ids from the inventory are accepted, and the canonical result must be a
/// direct child of the canonical polders dir; this is checked before any read, write or delete.
pub fn polder_dir(id: &str) -> Res<PathBuf> {
    if !valid_id(id) { return Err(tf!("invalid test polder id: {}", id.escape_debug())); }
    let root = polders_root()?;
    if !ids().iter().any(|x| x == id) { return Err(tf!("unknown test polder: {}", id)); }
    let p = root.join(id);
    let m = fs::symlink_metadata(&p).map_err(|_| tf!("unknown test polder: {}", id))?;
    if !m.file_type().is_dir() { return Err(tf!("unknown test polder: {}", id)); }
    let c = fs::canonicalize(&p).map_err(|x| format!("{}: {x}", p.display()))?;
    if c != p || c.parent() != Some(root.as_path()) { return Err(tf!("test polder {} is outside the Sluis storage", id)); }
    Ok(p)
}
fn pdir_new(id: &str) -> PathBuf { data_dir().join("polders").join(id) }

// ---------------------------------------------------------------- fd-relative, no-follow primitives
mod nf {
    use super::*;
    pub type IoRes<T> = std::io::Result<T>;
    fn last() -> std::io::Error { std::io::Error::last_os_error() }
    fn chk(r: libc::c_int) -> IoRes<()> { if r < 0 { Err(last()) } else { Ok(()) } }
    pub const DIRF: libc::c_int = libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC;
    pub fn cs(s: &str) -> Res<CString> { CString::new(s).map_err(|_| tr("path contains a NUL byte").to_string()) }
    pub fn cp(p: &Path) -> Res<CString> { CString::new(p.as_os_str().as_bytes()).map_err(|_| tr("path contains a NUL byte").to_string()) }
    /// open a directory by path; the last component must not be a symlink
    pub fn open_dir(p: &Path) -> Res<OwnedFd> {
        let c = cp(p)?; let fd = unsafe { libc::open(c.as_ptr(), DIRF) };
        if fd < 0 { return Err(format!("{}: {}", p.display(), last())); }
        Ok(unsafe { OwnedFd::from_raw_fd(fd) })
    }
    pub fn openat(d: &OwnedFd, n: &CStr, flags: libc::c_int, mode: u32) -> IoRes<OwnedFd> {
        let fd = unsafe { libc::openat(d.as_raw_fd(), n.as_ptr(), flags | libc::O_CLOEXEC, mode as libc::c_uint) };
        if fd < 0 { Err(last()) } else { Ok(unsafe { OwnedFd::from_raw_fd(fd) }) }
    }
    pub fn lstatat(d: &OwnedFd, n: &CStr) -> IoRes<Option<libc::stat>> {
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstatat(d.as_raw_fd(), n.as_ptr(), &mut st, libc::AT_SYMLINK_NOFOLLOW) } < 0 {
            let x = last(); return if x.raw_os_error() == Some(libc::ENOENT) { Ok(None) } else { Err(x) };
        }
        Ok(Some(st))
    }
    pub fn fstat(fd: &OwnedFd) -> IoRes<libc::stat> {
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        chk(unsafe { libc::fstat(fd.as_raw_fd(), &mut st) })?; Ok(st)
    }
    pub fn is(st: &libc::stat, t: libc::mode_t) -> bool { st.st_mode & libc::S_IFMT == t }
    pub fn readlinkat(d: &OwnedFd, n: &CStr) -> IoRes<String> {
        let mut b = vec![0u8; 4096];
        let r = unsafe { libc::readlinkat(d.as_raw_fd(), n.as_ptr(), b.as_mut_ptr() as *mut libc::c_char, b.len()) };
        if r < 0 { return Err(last()); } b.truncate(r as usize); Ok(String::from_utf8_lossy(&b).into())
    }
    pub fn unlinkat(d: &OwnedFd, n: &CStr, dir: bool) -> IoRes<()> { chk(unsafe { libc::unlinkat(d.as_raw_fd(), n.as_ptr(), if dir { libc::AT_REMOVEDIR } else { 0 }) }) }
    pub fn mkdirat(d: &OwnedFd, n: &CStr, mode: u32) -> IoRes<()> { chk(unsafe { libc::mkdirat(d.as_raw_fd(), n.as_ptr(), mode as libc::mode_t) }) }
    pub fn symlinkat(target: &str, d: &OwnedFd, n: &CStr) -> Res<()> {
        let t = cs(target)?; chk(unsafe { libc::symlinkat(t.as_ptr(), d.as_raw_fd(), n.as_ptr()) }).map_err(e("symlink"))
    }
    pub fn renameat(fd1: libc::c_int, n1: &CStr, d2: &OwnedFd, n2: &CStr) -> IoRes<()> { chk(unsafe { libc::renameat(fd1, n1.as_ptr(), d2.as_raw_fd(), n2.as_ptr()) }) }
    pub fn linkat(d: &OwnedFd, n: &CStr, to: &CStr) -> IoRes<()> { chk(unsafe { libc::linkat(d.as_raw_fd(), n.as_ptr(), libc::AT_FDCWD, to.as_ptr(), 0) }) }
    /// renameat2(2) within one directory: flags RENAME_NOREPLACE (1) or RENAME_EXCHANGE (2)
    pub fn rename2(d: &OwnedFd, a: &CStr, b: &CStr, flags: libc::c_uint) -> IoRes<()> {
        chk(unsafe { libc::syscall(libc::SYS_renameat2, d.as_raw_fd() as libc::c_long, a.as_ptr(), d.as_raw_fd() as libc::c_long, b.as_ptr(), flags as libc::c_long) } as libc::c_int)
    }
    pub const NOREPLACE: libc::c_uint = 1;
    pub const EXCHANGE: libc::c_uint = 2;
    pub fn link_in(from: &CStr, d: &OwnedFd, n: &CStr) -> IoRes<()> { chk(unsafe { libc::linkat(libc::AT_FDCWD, from.as_ptr(), d.as_raw_fd(), n.as_ptr(), 0) }) }
    pub fn fsync(d: &OwnedFd) { unsafe { libc::fsync(d.as_raw_fd()); } }
    /// chmod an fd, also an O_PATH one (via its /proc/self/fd magic link, which resolves to exactly that inode)
    pub fn chmod_fd(fd: &OwnedFd, mode: u32) -> IoRes<()> {
        if unsafe { libc::fchmod(fd.as_raw_fd(), mode as libc::mode_t) } == 0 { return Ok(()); }
        let x = last(); if x.raw_os_error() != Some(libc::EBADF) { return Err(x); }
        fs::set_permissions(format!("/proc/self/fd/{}", fd.as_raw_fd()), fs::Permissions::from_mode(mode))
    }
    /// names in a directory fd (without . and ..)
    pub fn ls(d: &OwnedFd) -> IoRes<Vec<CString>> {
        let fd = unsafe { libc::dup(d.as_raw_fd()) }; if fd < 0 { return Err(last()); }
        let dir = unsafe { libc::fdopendir(fd) }; if dir.is_null() { let x = last(); unsafe { libc::close(fd); } return Err(x); }
        unsafe { libc::rewinddir(dir); }
        let mut v = vec![];
        loop {
            let ent = unsafe { libc::readdir(dir) }; if ent.is_null() { break; }
            let n = unsafe { CStr::from_ptr((*ent).d_name.as_ptr()) };
            if n.to_bytes() != b"." && n.to_bytes() != b".." { v.push(n.to_owned()); }
        }
        unsafe { libc::closedir(dir); }
        Ok(v)
    }
}

/// Remove a tree without ever following a symlink: everything is done with unlinkat/openat(O_NOFOLLOW) relative to
/// directory fds, and each directory fd is checked to be the inode that was lstat'ed. A symlink inside the tree
/// (or as `p` itself) is removed as a link; its target is never touched.
pub fn rm_rf(p: &Path) -> Res<()> {
    let (Some(parent), Some(name)) = (p.parent(), p.file_name()) else { return Err(tf!("refusing to delete {}", p.display())) };
    if name == "." || name == ".." { return Err(tf!("refusing to delete {}", p.display())); }
    let parent = if parent.as_os_str().is_empty() { Path::new(".") } else { parent };
    let pfd = match nf::open_dir(parent) { Ok(f) => f, Err(_) if fs::symlink_metadata(p).is_err() => return Ok(()), Err(x) => return Err(x) };
    rm_at(&pfd, &nf::cp(Path::new(name))?).map_err(|x| format!("{}: {x}", p.display()))
}
fn rm_at(d: &OwnedFd, n: &CStr) -> std::io::Result<()> {
    let Some(st) = nf::lstatat(d, n)? else { return Ok(()) };
    if !nf::is(&st, libc::S_IFDIR) { return nf::unlinkat(d, n, false); }
    let same = |x: &libc::stat| x.st_ino == st.st_ino && x.st_dev == st.st_dev && nf::is(x, libc::S_IFDIR);
    let swapped = || std::io::Error::new(std::io::ErrorKind::Other, "directory changed during removal");
    if st.st_mode & 0o700 != 0o700 {                       // overlay work dirs can contain mode-000 dirs
        let pf = nf::openat(d, n, libc::O_PATH | libc::O_NOFOLLOW | libc::O_DIRECTORY, 0)?;
        if !same(&nf::fstat(&pf)?) { return Err(swapped()); }
        nf::chmod_fd(&pf, 0o700)?;
    }
    let fd = nf::openat(d, n, nf::DIRF, 0)?;
    if !same(&nf::fstat(&fd)?) { return Err(swapped()); }
    for c in nf::ls(&fd)? { rm_at(&fd, &c)?; }
    nf::unlinkat(d, n, true)
}

// ---------------------------------------------------------------- relative paths (always resolved no-follow)
/// A mainland path is relative, non-empty, without empty, "." or ".." components and without NUL.
pub fn valid_rel(p: &str) -> bool { !p.is_empty() && !p.starts_with('/') && !p.contains('\0') && p.split('/').all(|c| !c.is_empty() && c != "." && c != "..") }
pub struct Loc { pub dir: OwnedFd, pub name: CString }
/// Walk `rel` from `root` with O_NOFOLLOW directory fds. Ok(None): a parent does not exist (yet).
/// A parent that is a symlink or not a directory is an error: nothing below it is ever touched.
pub fn locate(root: &OwnedFd, rel: &str) -> Res<Option<Loc>> {
    if !valid_rel(rel) { return Err(tf!("invalid path: {}", rel.escape_debug())); }
    let parts: Vec<&str> = rel.split('/').collect();
    let mut d = root.try_clone().map_err(e("dup"))?;
    for p in &parts[..parts.len() - 1] {
        match nf::openat(&d, &nf::cs(p)?, nf::DIRF, 0) {
            Ok(x) => d = x,
            Err(x) if x.raw_os_error() == Some(libc::ENOENT) => return Ok(None),
            Err(x) => return Err(tf!("{}: a parent folder is a symlink or not a folder; not touched ({})", rel, x)),
        }
    }
    Ok(Some(Loc { dir: d, name: nf::cs(parts[parts.len() - 1])? }))
}
fn hash_reader(f: &mut impl Read) -> Res<String> {
    let mut c = glib::Checksum::new(glib::ChecksumType::Sha256).ok_or(tr("no sha256"))?;
    let mut buf = vec![0u8; 1 << 16];
    loop { let n = f.read(&mut buf).map_err(e(tr("read")))?; if n == 0 { break; } c.update(&buf[..n]); }
    Ok(c.string().map(|s| s.to_string()).unwrap_or_default())
}
fn state_stat(l: &Loc) -> Res<(St, Option<libc::stat>)> {
    let Some(st) = nf::lstatat(&l.dir, &l.name).map_err(e("stat"))? else { return Ok((St::Absent, None)) };
    let s = if nf::is(&st, libc::S_IFLNK) { St::Link { target: nf::readlinkat(&l.dir, &l.name).map_err(e("readlink"))? } }
        else if nf::is(&st, libc::S_IFDIR) { St::Dir { mode: st.st_mode as u32 & 0o7777 } }
        else if nf::is(&st, libc::S_IFREG) {
            let fd = nf::openat(&l.dir, &l.name, libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK, 0).map_err(e(tr("open")))?;
            let fs2 = nf::fstat(&fd).map_err(e("stat"))?;
            if fs2.st_ino != st.st_ino || !nf::is(&fs2, libc::S_IFREG) { return Err(tr("the mainland has changed meanwhile; not touched").into()); }
            let mut f = fs::File::from(fd);
            St::File { mode: fs2.st_mode as u32 & 0o7777, size: fs2.st_size as u64, hash: hash_reader(&mut f)? }
        } else { return Err(tf!("{}: unsupported file type (device/fifo/socket)", l.name.to_string_lossy())) };
    Ok((s, Some(st)))
}
fn state_at(l: &Loc) -> Res<St> { state_stat(l).map(|x| x.0) }
/// State of a mainland path, resolved without following symlinks in any component.
pub fn state_rel(root: &OwnedFd, rel: &str) -> Res<St> { match locate(root, rel)? { None => Ok(St::Absent), Some(l) => state_at(&l) } }

// ---------------------------------------------------------------- hashing / state (read-only scans)
pub fn hash_file(p: &Path) -> Res<String> { hash_reader(&mut fs::File::open(p).map_err(e(tr("open")))?) }
pub fn state_of(p: &Path) -> Res<St> {
    // ENOTDIR: a parent is not a directory (e.g. the mainland still has a file where the polder made a folder)
    let m = match fs::symlink_metadata(p) { Ok(m) => m, Err(x) if x.kind() == std::io::ErrorKind::NotFound || x.raw_os_error() == Some(libc::ENOTDIR) => return Ok(St::Absent), Err(x) => return Err(format!("{}: {x}", p.display())) };
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

/// Walk a tree: relative path -> Entry (the root itself is not included). Symlinks are recorded, never followed.
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
    let s: String = s.chars().take(40).collect(); let s = s.trim_end_matches('-').to_string();
    if s.is_empty() { "polder".into() } else { s }
}
pub fn write_json<T: Serialize>(p: &Path, v: &T) -> Res<()> {
    let tmp = p.with_extension("tmp");
    let mut f = fs::File::create(&tmp).map_err(e(tr("write")))?;
    f.write_all(serde_json::to_string_pretty(v).unwrap().as_bytes()).map_err(e(tr("write")))?;
    f.sync_all().map_err(e(tr("write")))?; fs::rename(&tmp, p).map_err(e(tr("rename")))?;
    if let Some(d) = p.parent() { fsync_dir(d); }
    Ok(())
}
pub fn read_json<T: for<'a> Deserialize<'a>>(p: &Path) -> Res<T> {
    serde_json::from_str(&fs::read_to_string(p).map_err(|x| format!("{}: {x}", p.display()))?).map_err(|x| format!("{}: {x}", p.display()))
}
pub fn meta(id: &str) -> Res<Meta> {
    let m: Meta = read_json(&polder_dir(id)?.join("meta.json"))?;
    if m.id != id { return Err(tf!("test polder {} has inconsistent metadata", id)); }
    Ok(m)
}
pub fn save_meta(m: &Meta) -> Res<()> { write_json(&polder_dir(&m.id)?.join("meta.json"), m) }
pub fn baseline(id: &str) -> Res<BTreeMap<String, Entry>> { read_json(&polder_dir(id)?.join("baseline.json")) }

pub fn list() -> Vec<Meta> {
    let mut v: Vec<Meta> = ids().iter().filter_map(|i| meta(i).ok()).collect();
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
    while fs::symlink_metadata(pdir_new(&id)).is_ok() { id = format!("{}-{i}", slug(name)); i += 1; }
    if !valid_id(&id) { return Err(tf!("invalid test polder id: {}", id.escape_debug())); }
    fs::create_dir(pdir_new(&id)).map_err(e(tr("create folder")))?;
    let d = polder_dir(&id)?;
    for s in ["upper", "work", "hupper", "hwork", "journal"] { fs::create_dir(d.join(s)).map_err(e(tr("create folder")))?; }
    let base = scan(&origin)?;
    write_json(&d.join("baseline.json"), &base)?;
    let m = Meta { id, name: name.into(), description: description.into(), origin: origin.to_string_lossy().into(), created: now(), ..Default::default() };
    save_meta(&m)?;
    Ok(m)
}

pub fn discard(id: &str) -> Res<()> {
    let d = polder_dir(id)?;
    let _lock = lock_workspace(&d.join("journal"))?;  // no merge/resume/rollback may run while the polder is removed
    if pending_in(&d.join("journal")).is_some() { return Err(tr("There is an interrupted merge; finish or undo it first.").into()); }
    let d = polder_dir(id)?;                      // re-check right before the destructive step
    rm_rf(&d)
}
pub fn archive(id: &str, on: bool) -> Res<Meta> { let mut m = meta(id)?; m.archived = on; save_meta(&m)?; Ok(m) }
/// disk usage without following symlinks
pub fn disk_usage(p: &Path) -> u64 {
    let mut n = 0;
    if let Ok(m) = fs::symlink_metadata(p) { n += m.blocks() * 512; if m.is_dir() { if let Ok(rd) = fs::read_dir(p) { for d in rd.flatten() { n += disk_usage(&d.path()); } } } }
    n
}
pub fn polder_usage(id: &str) -> u64 { polder_dir(id).map(|d| disk_usage(&d)).unwrap_or(0) }

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
            (St::Dir { .. }, St::Dir { .. }) => "rechten",           // dirs differ only in mode
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
    let m = meta(id)?; changes_for(Path::new(&m.origin), &polder_dir(id)?.join("upper"), &baseline(id)?)
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
        if !valid_rel(&c.path) { plan.skipped.push((c.path.clone(), tr("invalid path").into())); continue; }
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
    // a write that replaces a directory runs after the deletions (which empty that directory first)
    let (mut del, mut rest): (Vec<Op>, Vec<Op>) = plan.ops.drain(..).partition(|o| o.act == "delete" || o.act == "rmdir" || (o.act == "write" && matches!(o.pre, St::Dir { .. })));
    rest.sort_by(|a, b| (a.path.matches('/').count(), a.act != "mkdir", a.path.clone()).cmp(&(b.path.matches('/').count(), b.act != "mkdir", b.path.clone())));
    del.sort_by(|a, b| b.path.matches('/').count().cmp(&a.path.matches('/').count()).then((a.act == "write").cmp(&(b.act == "write"))).then(b.path.cmp(&a.path)));
    plan.ops = rest; plan.ops.extend(del);
    plan
}
pub fn plan(id: &str, selected: &[String], force: &[String]) -> Res<Plan> {
    let m = meta(id)?; let ch = changes(id)?;
    Ok(plan_for(Path::new(&m.origin), &polder_dir(id)?.join("upper"), &ch, selected, force))
}

// ---------------------------------------------------------------- journaled apply: one recoverable state machine
#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct Report { pub merge_id: String, pub done: Vec<String>, pub failed: Vec<(String, String)>, pub skipped: Vec<(String, String)>, pub rolled_back: bool }

/// Journal phases. Forward: Applying -> Applied (all ops attempted, report.json written) -> Reconciled (baseline.json
/// rebuilt from baseline.before.json + the applied paths) -> Committed. Rollback: RollingBack -> RolledBack only when
/// every op was restored (and the baseline put back); otherwise RollbackPartial, which stays pending and retryable.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Phase { Applying, Applied, Reconciled, Committed, RollingBack, RollbackPartial, RolledBack }
impl Phase { pub fn is_final(self) -> bool { matches!(self, Phase::Committed | Phase::RolledBack) } }

/// Test/fault injection. `crash_at` names a crash point: "op:N" (before op N), "ops-done" (after the last file op,
/// before the Applied marker), "applied", "baseline" (after baseline.json is written, before Reconciled),
/// "reconciled", "rollback-op:N" (fail restoring op N) and "rollback-baseline". `hook` runs at race windows:
/// "pre-op:<path>", "chmod:<path>", "delete:<path>", "replace:<path>".
#[derive(Clone, Default)]
pub struct Faults { pub crash_at: Option<String>, pub hook: Option<Arc<dyn Fn(&str) + Send + Sync>> }
impl Faults {
    pub fn none() -> Self { Self::default() }
    pub fn crash(p: &str) -> Self { Faults { crash_at: Some(p.into()), hook: None } }
    pub fn hook(f: impl Fn(&str) + Send + Sync + 'static) -> Self { Faults { crash_at: None, hook: Some(Arc::new(f)) } }
    /// POLDER_SLUIS_CRASH=<point> or POLDER_SLUIS_CRASH_AFTER=<n> (CLI crash tests)
    pub fn from_env() -> Self {
        let c = std::env::var("POLDER_SLUIS_CRASH").ok().or_else(|| std::env::var("POLDER_SLUIS_CRASH_AFTER").ok().map(|n| format!("op:{n}")));
        Faults { crash_at: c, hook: None }
    }
    fn check(&self, point: &str) -> Res<()> { if self.crash_at.as_deref() == Some(point) { Err(format!("CRASH (test) at {point}")) } else { Ok(()) } }
    fn call(&self, p: &str) { if let Some(h) = &self.hook { h(p) } }
}
/// legacy name kept for the CLI
pub fn crash_after() -> Option<usize> { std::env::var("POLDER_SLUIS_CRASH_AFTER").ok().and_then(|s| s.parse().ok()) }

fn fsync_dir(p: &Path) { if let Ok(f) = fs::File::open(p) { let _ = f.sync_all(); } }
fn log_line(j: &Path, s: &str) -> Res<()> {
    let mut f = fs::OpenOptions::new().create(true).append(true).open(j.join("log")).map_err(e("journal"))?;
    writeln!(f, "{s}").map_err(e("journal"))?; f.sync_all().map_err(e("journal"))
}
pub fn phase(j: &Path) -> Phase {
    if let Ok(p) = read_json::<Phase>(&j.join("state")) { return p; }
    if j.join("rolledback").exists() { Phase::RolledBack } else if j.join("committed").exists() { Phase::Committed } else { Phase::Applying }
}
fn set_phase(j: &Path, p: Phase) -> Res<()> { write_json(&j.join("state"), &p) }

fn tmp_cname(l: &Loc) -> Res<CString> { nf::cs(&format!(".{}.sluis-tmp", l.name.to_string_lossy())) }

/// Keep the current mainland object of op n (files by hard link or copy, symlinks re-created; dirs need no backup).
fn backup(j: &Path, n: usize, l: &Loc, cur: &St) -> Res<()> {
    let bd = j.join("backup"); let b = bd.join(n.to_string());
    if b.symlink_metadata().is_ok() { return Ok(()); }                            // already taken (resume)
    let tmp = bd.join(format!("{n}.tmp")); let _ = fs::remove_file(&tmp);
    match cur {
        St::Absent | St::Dir { .. } => return Ok(()),
        St::Link { target } => std::os::unix::fs::symlink(target, &tmp).map_err(e(tr("backup")))?,
        St::File { .. } => if nf::linkat(&l.dir, &l.name, &nf::cp(&tmp)?).is_err() {
            let fd = nf::openat(&l.dir, &l.name, libc::O_RDONLY | libc::O_NOFOLLOW, 0).map_err(e(tr("backup")))?;
            let mut src = fs::File::from(fd); let mut dst = fs::File::create(&tmp).map_err(e(tr("backup")))?;
            std::io::copy(&mut src, &mut dst).map_err(e(tr("backup")))?; dst.sync_all().map_err(e(tr("backup")))?;
        },
    }
    fs::rename(&tmp, &b).map_err(e(tr("backup")))?; fsync_dir(&bd);
    Ok(())
}
fn changed() -> String { tr("the mainland has changed meanwhile; not touched").into() }
/// Exact precondition check + chmod on the very inode: opened O_PATH|O_NOFOLLOW, so a symlink swapped in is refused.
fn chmod_exact(l: &Loc, expect: &St, mode: u32) -> Res<()> {
    let pf = nf::openat(&l.dir, &l.name, libc::O_PATH | libc::O_NOFOLLOW, 0).map_err(|_| changed())?;
    let st = nf::fstat(&pf).map_err(e("stat"))?;
    let ok = match expect { St::Dir { mode: m } => nf::is(&st, libc::S_IFDIR) && st.st_mode as u32 & 0o7777 == *m,
                            St::File { mode: m, .. } => nf::is(&st, libc::S_IFREG) && st.st_mode as u32 & 0o7777 == *m, _ => false };
    if !ok { return Err(changed()); }
    nf::chmod_fd(&pf, mode).map_err(e(tr("permissions")))
}
/// Structural validation of a journal op (plans are read back from disk on resume).
fn check_op(o: &Op) -> Res<()> {
    if !valid_rel(&o.path) { return Err(tf!("invalid path: {}", o.path.escape_debug())); }
    let ok = match o.act.as_str() {
        "mkdir" => matches!(o.post, St::Dir { .. }) && !matches!(o.pre, St::Dir { .. }),
        "chmod" => match (&o.pre, &o.post) { (St::Dir { .. }, St::Dir { .. }) => true, (St::File { .. }, St::File { .. }) => o.pre.same_content(&o.post), _ => false },
        "delete" => o.post.is_absent() && matches!(o.pre, St::File { .. } | St::Link { .. }),
        "rmdir" => o.post.is_absent() && matches!(o.pre, St::Dir { .. }),
        "write" => matches!(o.post, St::File { .. } | St::Link { .. }) && (!matches!(o.post, St::File { .. }) || o.src.is_some()),
        _ => false,
    };
    if ok { Ok(()) } else { Err(tf!("unknown operation {}", o.act)) }
}
/// Open the polder-side source of a write: the src path must be <upper>/<path>, walked no-follow from <upper>.
fn open_src(o: &Op) -> Res<fs::File> {
    let src = o.src.as_deref().ok_or(tr("no source"))?;
    let upper = src.strip_suffix(&o.path).and_then(|u| u.strip_suffix('/')).ok_or(tr("no source"))?;
    let root = nf::open_dir(Path::new(upper))?;
    let l = locate(&root, &o.path)?.ok_or(tr("no source"))?;
    let fd = nf::openat(&l.dir, &l.name, libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK, 0).map_err(e(tr("copy")))?;
    if !nf::is(&nf::fstat(&fd).map_err(e("stat"))?, libc::S_IFREG) { return Err(tr("the file in the polder has changed meanwhile; review the changes again").into()); }
    Ok(fs::File::from(fd))
}
/// Remove a stale staging object `.name.sluis-tmp` left by a crash (a file, symlink or EMPTY directory).
fn clean_tmp(l: &Loc) -> Res<()> {
    let tmp = tmp_cname(l)?;
    match nf::lstatat(&l.dir, &tmp).map_err(e("stat"))? {
        None => Ok(()),
        Some(s) if nf::is(&s, libc::S_IFDIR) => nf::unlinkat(&l.dir, &tmp, true).map_err(|x| tf!("leftover temporary folder {} is not empty; not touched ({})", tmp.to_string_lossy(), x)),
        Some(_) => nf::unlinkat(&l.dir, &tmp, false).map_err(e(tr("delete"))),
    }
}
fn dir_is_empty(l: &Loc, n: &CStr) -> Res<bool> {
    let d = nf::openat(&l.dir, n, nf::DIRF, 0).map_err(|_| changed())?;
    Ok(nf::ls(&d).map_err(e("readdir"))?.is_empty())
}
/// Put the staged object `.name.sluis-tmp` in place of `name`, so that at EVERY instant `name` is either the old
/// object (`old`) or the new one: absent target -> renameat2(NOREPLACE); file/link replaced by file/link -> renameat
/// (atomic); any replacement involving a directory -> renameat2(EXCHANGE), after which the old object sits at the
/// temp name and is removed (a directory only when empty; otherwise the exchange is undone).
/// Crash points: "<pfx>staged:<path>" (staged, nothing swapped) and "<pfx>exchanged:<path>" (swapped, old not removed).
fn install_staged(l: &Loc, staged_dir: bool, old: &St, f: &Faults, pfx: &str, path: &str) -> Res<()> {
    let tmp = tmp_cname(l)?;
    let undo = |x: String| { let _ = nf::unlinkat(&l.dir, &tmp, staged_dir); x };
    f.check(&format!("{pfx}staged:{path}"))?;
    match old {
        St::Absent => nf::rename2(&l.dir, &tmp, &l.name, nf::NOREPLACE).map_err(|_| undo(changed()))?,
        St::File { .. } | St::Link { .. } if !staged_dir => nf::renameat(l.dir.as_raw_fd(), &tmp, &l.dir, &l.name).map_err(|x| undo(tf!("replace: {}", x)))?,
        _ => {
            let old_dir = matches!(old, St::Dir { .. });
            if old_dir && !dir_is_empty(l, &l.name)? { return Err(undo(tr("folder is not empty on the mainland (it contains files the polder does not know)").into())); }
            nf::rename2(&l.dir, &tmp, &l.name, nf::EXCHANGE).map_err(|x| undo(tf!("replace: {}", x)))?;
            nf::fsync(&l.dir);
            f.check(&format!("{pfx}exchanged:{path}"))?;
            if let Err(x) = nf::unlinkat(&l.dir, &tmp, old_dir) {
                // a file appeared in the old directory meanwhile: swap back, keep everything
                let _ = nf::rename2(&l.dir, &tmp, &l.name, nf::EXCHANGE); let _ = nf::unlinkat(&l.dir, &tmp, staged_dir);
                return Err(tf!("folder is not empty on the mainland (it contains files the polder does not know): {x}" ; x));
            }
        }
    }
    Ok(())
}
/// Stage the backup of op n (the original file or symlink) as `.name.sluis-tmp` next to the target (hard link, or a
/// copy when the journal is on another filesystem). The journal backup itself stays intact, so this is re-runnable.
fn stage_backup(j: &Path, n: usize, l: &Loc, pre: &St) -> Res<()> {
    let b = j.join("backup").join(n.to_string());
    let tmp = tmp_cname(l)?;
    match pre {
        St::Link { target } => nf::symlinkat(target, &l.dir, &tmp),
        St::File { mode, .. } => {
            if nf::link_in(&nf::cp(&b)?, &l.dir, &tmp).is_ok() { return Ok(()); }
            let mut src = fs::File::open(&b).map_err(|x| tf!("restoring backup: {x}" ; x))?;
            let fd = nf::openat(&l.dir, &tmp, libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW, 0o600).map_err(e(tr("copy")))?;
            let mut out = fs::File::from(fd);
            let r = std::io::copy(&mut src, &mut out).and_then(|_| out.set_permissions(fs::Permissions::from_mode(*mode))).and_then(|_| out.sync_all());
            if let Err(x) = r { let _ = nf::unlinkat(&l.dir, &tmp, false); return Err(tf!("restoring backup: {x}" ; x)); }
            Ok(())
        }
        _ => Err(tr("unknown operation").into()),
    }
}
fn stage_dir(l: &Loc, mode: u32) -> Res<()> {
    let tmp = tmp_cname(l)?;
    nf::mkdirat(&l.dir, &tmp, 0o700).map_err(e(tr("create folder")))?;
    let d = nf::openat(&l.dir, &tmp, nf::DIRF, 0).map_err(e(tr("create folder")))?;
    nf::chmod_fd(&d, mode).map_err(e(tr("permissions")))
}
fn apply_op(j: &Path, n: usize, root: &OwnedFd, o: &Op, f: &Faults) -> Res<()> {
    let l = locate(root, &o.path)?.ok_or_else(changed)?;
    if state_at(&l)? != o.pre { return Err(changed()); }                          // revalidate on the fd we will use
    backup(j, n, &l, &o.pre)?;
    log_line(j, &format!("start {n}"))?;
    match o.act.as_str() {
        "mkdir" => {
            let St::Dir { mode } = o.post else { return Err(tr("unknown operation").into()) };
            clean_tmp(&l)?; stage_dir(&l, mode)?;
            f.call(&format!("replace:{}", o.path));
            if state_at(&l)? != o.pre { let _ = nf::unlinkat(&l.dir, &tmp_cname(&l)?, true); return Err(changed()); }
            install_staged(&l, true, &o.pre, f, "", &o.path)?;
        }
        "chmod" => { f.call(&format!("chmod:{}", o.path)); chmod_exact(&l, &o.pre, o.post.mode().unwrap_or(0o644))?; }
        "delete" => {
            f.call(&format!("delete:{}", o.path));
            if state_at(&l)? != o.pre { return Err(changed()); }
            nf::unlinkat(&l.dir, &l.name, false).map_err(e(tr("delete")))?;
        }
        "rmdir" => {
            if !matches!(nf::lstatat(&l.dir, &l.name), Ok(Some(ref s)) if nf::is(s, libc::S_IFDIR)) { return Err(changed()); }
            nf::unlinkat(&l.dir, &l.name, true).map_err(|x| tf!("folder is not empty on the mainland (it contains files the polder does not know): {x}" ; x))?;
        }
        "write" => {
            clean_tmp(&l)?; let tmp = tmp_cname(&l)?;
            match &o.post {
                St::Link { target } => nf::symlinkat(target, &l.dir, &tmp)?,
                St::File { mode, hash, .. } => {
                    let mut src = open_src(o)?;
                    let fd = nf::openat(&l.dir, &tmp, libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW, 0o600).map_err(e(tr("copy")))?;
                    let mut out = fs::File::from(fd);
                    let mut c = glib::Checksum::new(glib::ChecksumType::Sha256).ok_or(tr("no sha256"))?;
                    let mut buf = vec![0u8; 1 << 16];
                    let r: Res<()> = (|| { loop { let k = src.read(&mut buf).map_err(e(tr("copy")))?; if k == 0 { break; } c.update(&buf[..k]); out.write_all(&buf[..k]).map_err(e(tr("copy")))?; }
                        out.sync_all().map_err(e(tr("copy")))?; out.set_permissions(fs::Permissions::from_mode(*mode)).map_err(e(tr("permissions"))) })();
                    if let Err(x) = r { let _ = nf::unlinkat(&l.dir, &tmp, false); return Err(x); }
                    if c.string().map(|s| s.to_string()).unwrap_or_default() != *hash { let _ = nf::unlinkat(&l.dir, &tmp, false); return Err(tr("the file in the polder has changed meanwhile; review the changes again").into()); }
                }
                _ => return Err(tr("unknown operation").into()),
            }
            f.call(&format!("replace:{}", o.path));
            if state_at(&l)? != o.pre { let _ = nf::unlinkat(&l.dir, &tmp, false); return Err(changed()); }
            install_staged(&l, false, &o.pre, f, "", &o.path)?;
        }
        x => return Err(tf!("unknown operation {}", x)),
    }
    nf::fsync(&l.dir);
    Ok(())
}

// ---------------------------------------------------------------- per-workspace lock
/// Exclusive per-workspace lock: flock(2) on `journal/.lock`, held for the whole merge (pending check, ops,
/// reconciliation), resume, rollback and discard. The kernel releases it when the process exits or crashes.
pub struct WsLock(fs::File);
// explicit unlock: a fork()ed child (between fork and exec in another thread) shares the open file description,
// so merely closing our fd would keep the lock until that child execs
impl Drop for WsLock { fn drop(&mut self) { unsafe { libc::flock(self.0.as_raw_fd(), libc::LOCK_UN); } } }
pub fn busy_msg() -> &'static str { tr("This test polder is busy with another operation (merge, finish or roll back). Try again in a moment.") }
pub fn lock_workspace(jroot: &Path) -> Res<WsLock> {
    use std::os::unix::fs::OpenOptionsExt;
    fs::create_dir_all(jroot).map_err(e("journal"))?;
    let f = fs::OpenOptions::new().create(true).read(true).write(true).custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).mode(0o600)
        .open(jroot.join(".lock")).map_err(e("lock"))?;
    if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        let x = std::io::Error::last_os_error();
        return Err(if x.raw_os_error() == Some(libc::EWOULDBLOCK) { busy_msg().to_string() } else { format!("lock: {x}") });
    }
    Ok(WsLock(f))
}

pub fn apply_plan(jroot: &Path, origin: &Path, plan: &Plan, baseline: Option<&Path>, f: &Faults) -> Res<Report> {
    let _lock = lock_workspace(jroot)?;
    if let Some(p) = pending_in(jroot) { return Err(tf!("interrupted merge {p} must be finished or rolled back first" ; p)); }
    static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let ns = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let mid = format!("{ns}-{}-{}", std::process::id(), SEQ.fetch_add(1, std::sync::atomic::Ordering::SeqCst));
    let j = jroot.join(&mid);
    if j.exists() { return Err(tr("journal already exists").into()); }
    fs::create_dir_all(j.join("backup")).map_err(e("journal"))?;
    // the pre-merge baseline is saved BEFORE any mainland change, so reconciliation and rollback are always possible
    if let Some(b) = baseline { let s = fs::read(b).map_err(e("baseline"))?; let t = j.join("baseline.before.tmp"); fs::write(&t, s).map_err(e("journal"))?;
        fs::File::open(&t).and_then(|x| x.sync_all()).map_err(e("journal"))?; fs::rename(&t, j.join("baseline.before.json")).map_err(e("journal"))?; }
    write_json(&j.join("plan.json"), &(origin.to_string_lossy().to_string(), plan))?;
    set_phase(&j, Phase::Applying)?;
    fsync_dir(&j); fsync_dir(jroot);
    drive(&j, f)
}
/// Advance a journal to Committed from whatever phase it is in. Every step is idempotent.
fn drive(j: &Path, f: &Faults) -> Res<Report> {
    let (origin, plan): (String, Plan) = read_json(&j.join("plan.json"))?;
    let mid = j.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    loop {
        match phase(j) {
            Phase::Applying => { let r = run_ops(j, Path::new(&origin), &plan, f, mid.clone())?; write_json(&j.join("report.json"), &r)?;
                                 f.check("ops-done")?; set_phase(j, Phase::Applied)?; f.check("applied")?; }
            Phase::Applied => { reconcile(j, Path::new(&origin))?; f.check("baseline")?; set_phase(j, Phase::Reconciled)?; f.check("reconciled")?; }
            Phase::Reconciled => { set_phase(j, Phase::Committed)?; }
            Phase::Committed => return read_json(&j.join("report.json")),
            Phase::RollingBack | Phase::RollbackPartial => return Err(tr("a rollback of this merge is unfinished; roll back again").into()),
            Phase::RolledBack => return Err(tr("this merge was rolled back").into()),
        }
    }
}
fn baseline_target(j: &Path) -> Option<PathBuf> {
    if !j.join("baseline.before.json").exists() { return None; }
    j.parent().and_then(|r| r.parent()).map(|p| p.join("baseline.json"))
}
/// baseline.json := baseline.before.json + the current state of every applied path (deterministic, so re-runnable)
fn reconcile(j: &Path, origin: &Path) -> Res<()> {
    let Some(target) = baseline_target(j) else { return Ok(()) };
    let mut b: BTreeMap<String, Entry> = read_json(&j.join("baseline.before.json"))?;
    let r: Report = read_json(&j.join("report.json"))?;
    rebase(&mut b, origin, &r.done);
    write_json(&target, &b)
}
fn run_ops(j: &Path, origin: &Path, plan: &Plan, f: &Faults, mid: String) -> Res<Report> {
    let root = nf::open_dir(origin)?;
    let mut r = Report { merge_id: mid, skipped: plan.skipped.clone(), ..Default::default() };
    let done_before = done_set(j);
    for (n, o) in plan.ops.iter().enumerate() {
        f.check(&format!("op:{n}"))?;
        if done_before.contains(&n) { r.done.push(o.path.clone()); continue; }
        let res = (|| -> Res<bool> {
            check_op(o)?;
            if let Some(l) = locate(&root, &o.path)? { clean_tmp(&l)?; }      // stale staging of a crashed attempt
            let cur = state_rel(&root, &o.path)?;
            if cur == o.post { return Ok(false); }                       // already applied (resume)
            if cur != o.pre { return Err(changed()); }                   // exact: type, content AND mode
            f.call(&format!("pre-op:{}", o.path));
            apply_op(j, n, &root, o, f)?; Ok(true)
        })();
        match res {
            Ok(_) => { log_line(j, &format!("done {n}"))?; r.done.push(o.path.clone()); }
            Err(x) if x.starts_with("CRASH (test)") => return Err(x),          // injected crash: stop like a dead process
            Err(x) => { log_line(j, &format!("fail {n}"))?; r.failed.push((o.path.clone(), x)); }
        }
    }
    Ok(r)
}
fn done_set(j: &Path) -> BTreeSet<usize> {
    fs::read_to_string(j.join("log")).unwrap_or_default().lines().filter_map(|l| l.strip_prefix("done ").and_then(|n| n.parse().ok())).collect()
}
fn merge_key(m: &str) -> (u128, String) { (m.split('-').next().and_then(|x| x.parse().ok()).unwrap_or(0), m.to_string()) }
/// All journals of a workspace (merge id, phase), oldest first.
pub fn journals(jroot: &Path) -> Vec<(String, Phase)> {
    let mut v: Vec<(String, Phase)> = fs::read_dir(jroot).map(|r| r.flatten()
        .filter(|d| d.file_type().map(|t| t.is_dir()).unwrap_or(false) && d.path().join("plan.json").exists())
        .filter_map(|d| { let n = d.file_name().to_string_lossy().to_string(); valid_merge_id(&n).then(|| (n, phase(&d.path()))) }).collect()).unwrap_or_default();
    v.sort_by_key(|x| merge_key(&x.0)); v
}
/// The newest journal that is not in a final phase.
pub fn pending_state_in(jroot: &Path) -> Option<(String, Phase)> { journals(jroot).into_iter().filter(|x| !x.1.is_final()).last() }
pub fn pending_in(jroot: &Path) -> Option<String> { pending_state_in(jroot).map(|x| x.0) }
fn journal(jroot: &Path, mid: &str) -> Res<PathBuf> {
    if !valid_merge_id(mid) { return Err(tf!("invalid merge id: {}", mid.escape_debug())); }
    let j = jroot.join(mid);
    if !fs::symlink_metadata(&j).map(|m| m.is_dir()).unwrap_or(false) || !j.join("plan.json").exists() { return Err(tf!("unknown merge: {}", mid)); }
    Ok(j)
}

/// Continue an interrupted merge where it stopped (ops are idempotent: already-applied ones are recognised).
pub fn resume_in(jroot: &Path, f: &Faults) -> Res<Report> {
    let _lock = lock_workspace(jroot)?;
    let (mid, _) = pending_state_in(jroot).ok_or(tr("no interrupted merge"))?;
    drive(&jroot.join(&mid), f)
}
/// Undo an interrupted, partially rolled back or finished merge from the journal backups. The merge is only marked
/// rolled back when every op is restored and the baseline is put back; otherwise it stays pending as rollback-partial
/// with the failures in rollback.json, and rolling back again retries the remaining ops.
pub fn rollback_in(jroot: &Path, mid: Option<&str>, f: &Faults) -> Res<Report> {
    let _lock = lock_workspace(jroot)?;
    let mid = match mid { Some(m) => m.to_string(), None => pending_in(jroot).ok_or(tr("no interrupted merge"))? };
    let j = journal(jroot, &mid)?;
    if phase(&j) == Phase::RolledBack { return Err(tr("this merge was rolled back").into()); }
    // only the newest merge that is not rolled back can be undone: an older one's baseline snapshot and backups
    // predate the later merges, so undoing it first would erase their accepted baseline state
    let newer: Vec<String> = journals(jroot).into_iter().filter(|(k, p)| merge_key(k) > merge_key(&mid) && *p != Phase::RolledBack).map(|x| x.0).collect();
    if !newer.is_empty() { return Err(tf!("Roll back the newer merge(s) first: {}", newer.join(", "))); }
    let (origin, plan): (String, Plan) = read_json(&j.join("plan.json"))?;
    let root = nf::open_dir(Path::new(&origin))?;
    set_phase(&j, Phase::RollingBack)?;
    let mut r = Report { merge_id: mid, ..Default::default() };
    for (n, o) in plan.ops.iter().enumerate().rev() {
        let res = (|| -> Res<bool> {
            check_op(o)?;
            // a path that did not exist before (pre Absent) and whose parent is missing or not a folder holds nothing to undo
            let l = match locate(&root, &o.path) { Ok(Some(l)) => l, Ok(None) | Err(_) if o.pre.is_absent() => return Ok(false), Ok(None) => return Err(changed()), Err(x) => return Err(x) };
            clean_tmp(&l)?;
            let cur = state_at(&l)?;
            if cur == o.pre { return Ok(false); }                                 // never applied, or already restored
            if cur != o.post { return Err(tr("changed after the merge; not restored").into()); }
            f.check(&format!("rollback-op:{n}"))?;
            match (&o.pre, o.act.as_str()) {
                (St::Absent, _) => nf::unlinkat(&l.dir, &l.name, matches!(o.post, St::Dir { .. })).map_err(e(tr("delete")))?,
                (St::Dir { mode }, "chmod") | (St::File { mode, .. }, "chmod") => chmod_exact(&l, &o.post, *mode)?,
                (St::Dir { mode }, _) => { stage_dir(&l, *mode)?; install_staged(&l, true, &cur, f, "rollback-", &o.path)?; }
                _ => { stage_backup(&j, n, &l, &o.pre)?; install_staged(&l, false, &cur, f, "rollback-", &o.path)?; }
            }
            nf::fsync(&l.dir); Ok(true)
        })();
        match res { Ok(true) => r.done.push(o.path.clone()), Ok(false) => {}, Err(x) => r.failed.push((o.path.clone(), x)) }
    }
    if r.failed.is_empty() {
        let br = (|| -> Res<()> {
            f.check("rollback-baseline")?;
            if let Some(t) = baseline_target(&j) { let b: BTreeMap<String, Entry> = read_json(&j.join("baseline.before.json"))?; write_json(&t, &b)?; }
            Ok(())
        })();
        if let Err(x) = br { r.failed.push(("baseline.json".into(), x)); }
    }
    r.rolled_back = r.failed.is_empty();
    write_json(&j.join("rollback.json"), &r)?;
    set_phase(&j, if r.rolled_back { Phase::RolledBack } else { Phase::RollbackPartial })?;
    Ok(r)
}
/// Failure details of the last (partial) rollback of a journal, if any.
pub fn rollback_report(jroot: &Path, mid: &str) -> Option<Report> { read_json(&journal(jroot, mid).ok()?.join("rollback.json")).ok() }

/// After a merge the merged paths are the new common ancestor: later polder edits to them are not conflicts.
pub fn rebase(base: &mut BTreeMap<String, Entry>, origin: &Path, paths: &[String]) {
    let Ok(root) = nf::open_dir(origin) else { return };
    for p in paths {
        let r = (|| -> Res<Option<Entry>> {
            let Some(l) = locate(&root, p)? else { return Ok(None) };
            let (st, s) = state_stat(&l)?;
            Ok(s.filter(|_| !st.is_absent()).map(|s| Entry { st, mtime: s.st_mtime * 1_000_000_000 + s.st_mtime_nsec, ino: s.st_ino }))
        })();
        match r { Ok(Some(en)) => { base.insert(p.clone(), en); } _ => { base.remove(p); } }
    }
}
fn jroot_of(id: &str) -> Res<PathBuf> { Ok(polder_dir(id)?.join("journal")) }
pub fn pending_merge(id: &str) -> Option<String> { pending_in(&jroot_of(id).ok()?) }
pub fn pending_state(id: &str) -> Option<(String, Phase)> { pending_state_in(&jroot_of(id).ok()?) }
pub fn merge(id: &str, selected: &[String], force: &[String]) -> Res<Report> {
    let m = meta(id)?; if m.archived { return Err(tr("This test polder is archived.").into()); }
    let p = plan(id, selected, force)?;
    let d = polder_dir(id)?;
    apply_plan(&d.join("journal"), Path::new(&m.origin), &p, Some(&d.join("baseline.json")), &Faults::from_env())
}
/// Undo a merge for a polder, including its baseline update.
pub fn rollback(id: &str, mid: Option<&str>) -> Res<Report> { rollback_in(&jroot_of(id)?, mid, &Faults::from_env()) }
pub fn resume(id: &str) -> Res<Report> { resume_in(&jroot_of(id)?, &Faults::from_env()) }

// ---------------------------------------------------------------- runner (bubblewrap)
pub fn runner_argv(m: &Meta, net: bool, cmd: &[String]) -> Res<Vec<String>> {
    let d = polder_dir(&m.id)?;
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
    Ok(a)
}
