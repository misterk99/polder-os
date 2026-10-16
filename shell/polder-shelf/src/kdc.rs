//! KDE Connect (kdeconnectd) over the session D-Bus: the real org.kde.kdeconnect API (KDE Connect 24.x,
//! core/daemon.h, core/device.h, plugins/*). Nothing is invented: every value comes from the daemon.
#[allow(unused_imports)] use crate::i18n::tr;
use gtk::{gio, glib, prelude::*};

pub const BUS: &str = "org.kde.kdeconnect";
pub const ROOT: &str = "/modules/kdeconnect";
const DEVI: &str = "org.kde.kdeconnect.device";

fn bus() -> Option<gio::DBusConnection> { gio::bus_get_sync(gio::BusType::Session, gio::Cancellable::NONE).ok() }
pub fn call(path: &str, iface: &str, method: &str, args: Option<glib::Variant>) -> Result<glib::Variant, String> {
    let b = bus().ok_or("no session bus")?;
    b.call_sync(Some(BUS), path, iface, method, args.as_ref(), None, gio::DBusCallFlags::NONE, 4000, gio::Cancellable::NONE).map_err(|e| e.to_string())
}
fn dbus(method: &str, args: Option<glib::Variant>) -> Option<glib::Variant> {
    bus()?.call_sync(Some("org.freedesktop.DBus"), "/org/freedesktop/DBus", "org.freedesktop.DBus", method, args.as_ref(), None,
                     gio::DBusCallFlags::NONE, 1500, gio::Cancellable::NONE).ok()
}
pub fn prop(path: &str, iface: &str, name: &str) -> Option<glib::Variant> {
    call(path, "org.freedesktop.DBus.Properties", "Get", Some((iface, name).to_variant())).ok()?.child_value(0).as_variant()
}
fn ps(path: &str, iface: &str, n: &str) -> String { prop(path, iface, n).and_then(|v| v.get::<String>()).unwrap_or_default() }
fn pb(path: &str, iface: &str, n: &str) -> bool { prop(path, iface, n).and_then(|v| v.get::<bool>()).unwrap_or(false) }
fn pi(path: &str, iface: &str, n: &str) -> Option<i32> { prop(path, iface, n).and_then(|v| v.get::<i32>()) }

pub fn running() -> bool { dbus("NameHasOwner", Some((BUS,).to_variant())).and_then(|v| v.child_value(0).get::<bool>()).unwrap_or(false) }
fn daemon_bin() -> Option<String> {
    if let Ok(b) = std::env::var("POLDER_KDECONNECTD") { return Some(b); }
    for p in ["/usr/bin/kdeconnectd", "/usr/lib/x86_64-linux-gnu/libexec/kdeconnectd", "/usr/lib/aarch64-linux-gnu/libexec/kdeconnectd", "/usr/libexec/kdeconnectd"] {
        if std::path::Path::new(p).exists() { return Some(p.into()); }
    }
    None
}
fn activatable() -> bool {
    dbus("ListActivatableNames", None).and_then(|v| v.child_value(0).get::<Vec<String>>()).map(|n| n.iter().any(|x| x == BUS)).unwrap_or(false)
}
pub fn installed() -> bool { daemon_bin().is_some() || activatable() }
/// D-Bus activation first, else spawn the daemon (like phone.start()).
pub fn start() -> bool {
    if running() { return true; }
    if activatable() && dbus("StartServiceByName", Some((BUS, 0u32).to_variant())).is_some() { return true; }
    match daemon_bin() {
        Some(b) => { let mut c = std::process::Command::new(b); c.env("QT_QPA_PLATFORM", "offscreen").stdout(std::process::Stdio::null());
                     use std::os::unix::process::CommandExt; c.process_group(0);
                     c.spawn().map(|mut ch| { std::thread::spawn(move || ch.wait()); }).is_ok() }
        None => false,
    }
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Dev { pub id: String, pub name: String, pub reachable: bool, pub paired: bool, pub requested: bool, pub by_peer: bool, pub key: String, pub plugins: Vec<String> }
pub fn dpath(id: &str) -> String { format!("{ROOT}/devices/{id}") }
pub fn devices() -> Vec<Dev> {
    let ids = call(ROOT, "org.kde.kdeconnect.daemon", "devices", Some((false, false).to_variant())).ok()
        .and_then(|v| v.child_value(0).get::<Vec<String>>()).unwrap_or_default();
    ids.into_iter().map(|id| { let p = dpath(&id); Dev {
        name: { let n = ps(&p, DEVI, "name"); if n.is_empty() { id.clone() } else { n } },
        reachable: pb(&p, DEVI, "isReachable"), paired: pb(&p, DEVI, "isPaired"), requested: pb(&p, DEVI, "isPairRequested"),
        by_peer: pb(&p, DEVI, "isPairRequestedByPeer"), key: ps(&p, DEVI, "verificationKey"),
        plugins: prop(&p, DEVI, "supportedPlugins").and_then(|v| v.get::<Vec<String>>()).unwrap_or_default(), id } }).collect()
}
pub fn dev_call(id: &str, method: &str, args: Option<glib::Variant>) -> Result<glib::Variant, String> { call(&dpath(id), DEVI, method, args) }

#[derive(Clone, Debug, PartialEq)]
pub struct Notif { pub id: String, pub app: String, pub title: String, pub text: String, pub dismissable: bool, pub reply_id: String }
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Info { pub battery: Option<(i32, bool)>, pub net: Option<(String, i32)>, pub notifs: Vec<Notif>, pub clipboard: Option<bool>, pub sftp_mounted: bool }

pub fn info(d: &Dev) -> Info {
    let p = dpath(&d.id); let has = |n: &str| d.plugins.iter().any(|x| x == n);
    let mut i = Info::default();
    if has("kdeconnect_battery") {
        let bi = "org.kde.kdeconnect.device.battery";
        if let Some(c) = pi(&format!("{p}/battery"), bi, "charge").filter(|c| *c >= 0) { i.battery = Some((c, pb(&format!("{p}/battery"), bi, "isCharging"))); }
    }
    if has("kdeconnect_connectivity_report") {
        let ci = "org.kde.kdeconnect.device.connectivity_report"; let cp = format!("{p}/connectivity_report");
        let t = ps(&cp, ci, "cellularNetworkType");
        if !t.is_empty() && t != "Unknown" { i.net = Some((t, pi(&cp, ci, "cellularNetworkStrength").unwrap_or(-1))); }
    }
    if has("kdeconnect_notifications") {
        let np = format!("{p}/notifications"); let ni = "org.kde.kdeconnect.device.notifications.notification";
        let ids = call(&np, "org.kde.kdeconnect.device.notifications", "activeNotifications", None).ok()
            .and_then(|v| v.child_value(0).get::<Vec<String>>()).unwrap_or_default();
        for id in ids { let q = format!("{np}/{id}");
            i.notifs.push(Notif { app: ps(&q, ni, "appName"), title: ps(&q, ni, "title"), text: ps(&q, ni, "text"),
                                  dismissable: pb(&q, ni, "dismissable"), reply_id: ps(&q, ni, "replyId"), id }); }
    }
    if has("kdeconnect_clipboard") {
        i.clipboard = dev_call(&d.id, "isPluginEnabled", Some(("kdeconnect_clipboard",).to_variant())).ok().and_then(|v| v.child_value(0).get::<bool>());
    }
    if has("kdeconnect_sftp") {
        i.sftp_mounted = call(&format!("{p}/sftp"), "org.kde.kdeconnect.device.sftp", "isMounted", None).ok().and_then(|v| v.child_value(0).get::<bool>()).unwrap_or(false);
    }
    i
}
pub fn notif_call(id: &str, nid: &str, method: &str, args: Option<glib::Variant>) -> Result<glib::Variant, String> {
    call(&format!("{}/notifications/{nid}", dpath(id)), "org.kde.kdeconnect.device.notifications.notification", method, args)
}
pub fn plugin_call(id: &str, plugin: &str, iface: &str, method: &str, args: Option<glib::Variant>) -> Result<glib::Variant, String> {
    call(&format!("{}/{plugin}", dpath(id)), &format!("org.kde.kdeconnect.device.{iface}"), method, args)
}
/// sftp: mount (blocking until the phone answers), then {path: label} of the shared folders.
pub fn sftp_dirs(id: &str) -> Result<(String, Vec<(String, String)>), String> {
    let ok = plugin_call(id, "sftp", "sftp", "mountAndWait", None)?.child_value(0).get::<bool>().unwrap_or(false);
    if !ok { let e = plugin_call(id, "sftp", "sftp", "getMountError", None).ok().and_then(|v| v.child_value(0).get::<String>()).unwrap_or_default();
             return Err(if e.is_empty() { tr("Linking the files failed").into() } else { e }); }
    let mp = plugin_call(id, "sftp", "sftp", "mountPoint", None)?.child_value(0).get::<String>().unwrap_or_default();
    let d = plugin_call(id, "sftp", "sftp", "getDirectories", None)?.child_value(0);
    let dict = glib::VariantDict::new(Some(&d));
    let mut dirs = vec![];
    for i in 0..d.n_children() { let e = d.child_value(i); if let Some(k) = e.child_value(0).get::<String>() {
        let l = dict.lookup::<String>(&k).ok().flatten().unwrap_or_else(|| k.clone()); dirs.push((k, l)); } }
    dirs.sort();
    Ok((mp, dirs))
}
