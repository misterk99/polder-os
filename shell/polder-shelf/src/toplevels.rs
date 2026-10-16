//! Running windows via wlr-foreign-toplevel-management, spoken by the existing C helper polder-toplevels
//! (JSON lines out, '<cmd> <id>' in) exactly like shelf.py WlTasks.
use gtk::glib;
use std::{cell::RefCell, collections::BTreeMap, io::{Read, Write}, os::fd::AsRawFd, process::{Child, ChildStdin, Command, Stdio}, rc::Rc};

#[derive(Clone, Debug)]
pub struct Toplevel { pub title: String, pub app_id: String, pub activated: bool, pub minimized: bool }

pub struct Tasks { pub tl: BTreeMap<i64, Toplevel>, stdin: Option<ChildStdin>, _child: Option<Child> }
impl Tasks {
    pub fn send(&mut self, cmd: &str, id: i64) {
        if let Some(i) = self.stdin.as_mut() { if let Err(e) = writeln!(i, "{cmd} {id}").and_then(|_| i.flush()) { eprintln!("toplevels {e}"); } }
    }
    pub fn active(&self) -> i64 { self.tl.iter().find(|(_, t)| t.activated).map(|(i, _)| *i).unwrap_or(0) }
}

pub fn helper() -> String {
    if let Ok(h) = std::env::var("POLDER_TOPLEVELS") { return h; }
    for d in std::env::var("PATH").unwrap_or_default().split(':') {
        let p = std::path::Path::new(d).join("polder-toplevels"); if p.exists() { return p.to_string_lossy().into(); }
    }
    crate::theme::config_dir().join("../compositor/polder-comp/tools/polder-toplevels").to_string_lossy().into()
}

pub fn start(on_change: impl Fn() + 'static) -> Rc<RefCell<Tasks>> {
    let mut child = Command::new(helper()).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().map_err(|e| eprintln!("polder-toplevels: {e}")).ok();
    let stdin = child.as_mut().and_then(|c| c.stdin.take());
    let stdout = child.as_mut().and_then(|c| c.stdout.take());
    let t = Rc::new(RefCell::new(Tasks { tl: BTreeMap::new(), stdin, _child: child }));
    if let Some(mut out) = stdout {
        let fd = out.as_raw_fd(); let t2 = t.clone(); let mut buf: Vec<u8> = Vec::new();
        glib::source::unix_fd_add_local(fd, glib::IOCondition::IN | glib::IOCondition::HUP, move |_, _| {
            let mut chunk = [0u8; 65536];
            let n = out.read(&mut chunk).unwrap_or(0);
            if n == 0 { return glib::ControlFlow::Break; }
            buf.extend_from_slice(&chunk[..n]);
            while let Some(pos) = buf.iter().position(|&b| b == b'\n') {
                let line: Vec<u8> = buf.drain(..=pos).collect();
                let Ok(ev) = serde_json::from_slice::<serde_json::Value>(&line) else { continue };
                let id = ev["id"].as_i64().unwrap_or(-1);
                match ev["ev"].as_str() {
                    Some("state") => { t2.borrow_mut().tl.insert(id, Toplevel {
                        title: ev["title"].as_str().unwrap_or("").into(), app_id: ev["app_id"].as_str().unwrap_or("").into(),
                        activated: ev["activated"].as_bool().unwrap_or(false), minimized: ev["minimized"].as_bool().unwrap_or(false) }); }
                    Some("closed") => { t2.borrow_mut().tl.remove(&id); }
                    _ => {}
                }
            }
            on_change(); glib::ControlFlow::Continue
        });
    }
    t
}
