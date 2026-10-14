//! Desktop-entry database: maps a Wayland app_id / X11 class to a desktop id (port of shelf.py AppDB).
use gtk::{gio, prelude::*};
use std::collections::HashMap;

pub struct AppDb { pub apps: HashMap<String, gio::DesktopAppInfo>, keys: HashMap<String, String> }
impl AppDb {
    pub fn new() -> Self { let mut d = AppDb { apps: HashMap::new(), keys: HashMap::new() }; d.reload(); d }
    pub fn reload(&mut self) {
        self.apps.clear(); self.keys.clear();
        for a in gio::AppInfo::all() {
            let Ok(a) = a.downcast::<gio::DesktopAppInfo>() else { continue };
            let Some(id) = a.id().map(|s| s.to_string()) else { continue };
            let base = id.strip_suffix(".desktop").unwrap_or(&id).to_lowercase();
            let wm = a.startup_wm_class().map(|s| s.to_lowercase()).unwrap_or_default();
            let mut ks = vec![base.rsplit('.').next().unwrap_or("").to_string(), wm.clone()];
            // entries with StartupWMClass (webapps running 'chromium --app=') match on that only, never steal 'chromium'
            if wm.is_empty() {
                if let Some(cl) = a.commandline() {
                    if let Ok(argv) = gtk::glib::shell_parse_argv(cl.to_string_lossy().as_ref()) {
                        for t in argv { let t = t.to_string_lossy().to_string();
                            if !t.starts_with('-') && !t.contains('%') {
                                ks.push(std::path::Path::new(&t).file_name().map(|f| f.to_string_lossy().to_lowercase()).unwrap_or_default());
                            } }
                    }
                }
            }
            for k in ks {
                if !k.is_empty() && !["python3", "sh", "env", "bash"].contains(&k.as_str()) && (!self.keys.contains_key(&k) || a.should_show()) {
                    self.keys.insert(k, id.clone());
                }
            }
            self.apps.insert(id, a);
        }
    }
    pub fn for_class(&self, aid: &str) -> Option<String> {
        let first = aid.split('.').next().unwrap_or("");
        [aid, first].iter().find_map(|k| self.keys.get(&k.to_lowercase()).cloned())
    }
    pub fn resolve(&self, aid: &str) -> String {
        for d in [format!("{aid}.desktop"), format!("{}.desktop", aid.to_lowercase())] { if self.apps.contains_key(&d) { return d; } }
        self.for_class(aid).unwrap_or_else(|| format!("cls:{aid}"))
    }
}
