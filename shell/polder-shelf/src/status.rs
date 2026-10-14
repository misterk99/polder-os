//! Real system state for the status pills (same probes as shelf.py Status.slow_probe), MPRIS and screen recording.
use gtk::{gio, glib, prelude::*};
use std::{fs, path::Path, process::Command};

fn sh(cmd: &str, args: &[&str]) -> String {
    Command::new("timeout").arg("3").arg(cmd).args(args).output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}
pub fn which(c: &str) -> bool { std::env::var("PATH").unwrap_or_default().split(':').any(|d| Path::new(d).join(c).exists()) }

#[derive(Clone, Default, PartialEq, Debug)]
pub struct Probe { pub wifi: Option<String>, pub vol: Option<String>, pub bat: Option<String>, pub upd: bool }

pub fn slow_probe() -> Probe {
    let mut st = Probe::default();
    if which("nmcli") {
        let q = sh("nmcli", &["-t", "-f", "IN-USE,SIGNAL", "dev", "wifi"]);
        let sig = q.lines().find(|l| l.starts_with('*')).and_then(|l| l.split(':').nth(1)).and_then(|s| s.parse::<i32>().ok());
        if let Some(n) = sig {
            st.wifi = Some(format!("network-wireless-signal-{}", if n >= 80 { "excellent" } else if n >= 60 { "good" } else if n >= 30 { "ok" } else { "weak" }));
        } else if sh("nmcli", &["-t", "-f", "TYPE,STATE", "dev"]).contains("ethernet:connected") { st.wifi = Some("network-wired".into()); }
    }
    if which("pactl") {
        let v = sh("pactl", &["get-sink-volume", "@DEFAULT_SINK@"]); let m = sh("pactl", &["get-sink-mute", "@DEFAULT_SINK@"]);
        let pc = v.split('%').next().and_then(|s| s.rsplit(|c: char| !c.is_ascii_digit()).next()).and_then(|s| s.parse::<i32>().ok());
        if let Some(n) = pc {
            st.vol = Some(format!("audio-volume-{}", if m.contains("yes") || n == 0 { "muted" } else if n > 66 { "high" } else if n > 33 { "medium" } else { "low" }));
        }
    }
    let mut bats: Vec<_> = fs::read_dir("/sys/class/power_supply").map(|d| d.flatten().map(|e| e.path())
        .filter(|p| p.file_name().map(|f| f.to_string_lossy().starts_with("BAT")).unwrap_or(false)).collect()).unwrap_or_default();
    bats.sort();
    if let Some(b) = bats.first() {
        if let Some(c) = fs::read_to_string(b.join("capacity")).ok().and_then(|s| s.trim().parse::<i32>().ok()) {
            st.bat = Some(format!("battery-level-{}", (c + 5) / 10 * 10));
        }
    }
    st.upd = Path::new("/tmp/osb-update.json").exists();
    st
}

pub fn weather_pill() -> String {
    let w = crate::theme::config_dir().join("weather/weather.py");
    Command::new("timeout").arg("6").arg("python3").arg(w).arg("pill").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

/// Notification daemon state (osb-notifyd.py): (unread, dnd)
pub fn notify_state() -> (i64, bool) {
    let v: serde_json::Value = fs::read_to_string("/tmp/osb-notify/state.json").ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    (v["unread"].as_i64().unwrap_or(0), v["dnd"].as_bool().unwrap_or(false))
}

/// capture_backend.recording_state(): the state file is only trusted while its PID still has the same lifetime identity.
pub fn recording_start() -> Option<f64> {
    let st: serde_json::Value = serde_json::from_str(&fs::read_to_string(crate::theme::rundir().join("osb-rec.json")).ok()?).ok()?;
    let pid = st["pid"].as_i64()?;
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let f: Vec<&str> = stat.rsplit_once(')')?.1.split_whitespace().collect();
    use std::os::unix::fs::MetadataExt;
    if f.first() == Some(&"Z") || fs::metadata(format!("/proc/{pid}")).ok()?.uid() != unsafe { libc::getuid() } { return None; }
    let boot = fs::read_to_string("/proc/sys/kernel/random/boot_id").ok()?;
    let same = |k: &str, v: &str| st[k].as_str().map(|s| s == v).unwrap_or(false) || st[k].as_i64().map(|n| n.to_string() == v).unwrap_or(false);
    if !same("start_ticks", f.get(19)?) || !same("boot_id", boot.trim()) { return None; }
    st["start"].as_f64()
}
/// Stopping goes through the Python backend (pidfd pinning + SIGINT), the single implementation of that race-free logic.
pub fn stop_recording() {
    let c = crate::theme::config_dir().join("capture");
    let _ = Command::new("python3").arg("-c").arg("import sys; sys.path.insert(0, sys.argv[1]); import capture_backend; capture_backend.stop_recording()")
        .arg(c).spawn();
}

#[derive(Clone, Debug)]
pub struct Media { pub name: String, pub status: String, pub title: String, pub artist: String }
fn call(bus: &gio::DBusConnection, name: &str, path: &str, iface: &str, method: &str, args: Option<&glib::Variant>) -> Option<glib::Variant> {
    bus.call_sync(Some(name), path, iface, method, args, None, gio::DBusCallFlags::NONE, 800, gio::Cancellable::NONE).ok()
}
fn mstate(bus: &gio::DBusConnection, name: &str) -> Option<Media> {
    let r = call(bus, name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll", Some(&("org.mpris.MediaPlayer2.Player",).to_variant()))?;
    let d = glib::VariantDict::new(Some(&r.child_value(0)));
    let status = d.lookup::<String>("PlaybackStatus").ok().flatten().unwrap_or_else(|| "Stopped".into());
    let md = d.lookup_value("Metadata", None).map(|m| glib::VariantDict::new(Some(&m)));
    let title = md.as_ref().and_then(|m| m.lookup::<String>("xesam:title").ok().flatten()).unwrap_or_default();
    let artist = md.as_ref().and_then(|m| m.lookup::<Vec<String>>("xesam:artist").ok().flatten()).unwrap_or_default().join(", ");
    Some(Media { name: name.into(), status, title, artist })
}
/// Playing first, then Paused; None when nothing is loaded (no fake pill).
pub fn media_active() -> Option<Media> {
    let bus = gio::bus_get_sync(gio::BusType::Session, gio::Cancellable::NONE).ok()?;
    let names = call(&bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None)?.child_value(0).get::<Vec<String>>()?;
    let mut best = None;
    for n in names.iter().filter(|n| n.starts_with("org.mpris.MediaPlayer2.")) {
        let Some(s) = mstate(&bus, n) else { continue };
        if !(s.status == "Playing" || s.status == "Paused") || (s.title.is_empty() && s.artist.is_empty()) { continue; }
        if s.status == "Playing" { return Some(s); }
        best = best.or(Some(s));
    }
    best
}
pub fn media_toggle(name: &str) {
    if let Ok(bus) = gio::bus_get_sync(gio::BusType::Session, gio::Cancellable::NONE) {
        call(&bus, name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "PlayPause", None);
    }
}
