//! Polder OS i18n: gettext-compatible .mo catalogs (domain "polder"), English msgids.
//! A tiny loader instead of gettext-rs (not available offline); reads the same catalogs as the Python side.
//! Language: $POLDER_LANG > ~/.config/polder/language > LANGUAGE/LC_ALL/LC_MESSAGES/LANG; "en*" → English, else Dutch.
#![allow(dead_code)]
use std::{collections::HashMap, sync::OnceLock};

static CAT: OnceLock<HashMap<String, &'static str>> = OnceLock::new();
static LANG: OnceLock<String> = OnceLock::new();

pub fn language() -> &'static str {
    LANG.get_or_init(|| {
        let mut v = std::env::var("POLDER_LANG").unwrap_or_default();
        if v.is_empty() {
            if let Ok(h) = std::env::var("HOME") {
                let cfg = std::env::var("XDG_CONFIG_HOME").unwrap_or(format!("{h}/.config"));
                v = std::fs::read_to_string(format!("{cfg}/polder/language")).unwrap_or_default().trim().to_string();
            }
        }
        if v.is_empty() {
            for k in ["LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"] {
                if let Ok(x) = std::env::var(k) { if !x.is_empty() && x != "C" && x != "POSIX" && !x.starts_with("C.") { v = x.split(':').next().unwrap_or("").to_string(); break; } }
            }
        }
        if v.to_lowercase().starts_with("en") { "en".into() } else { "nl".into() }
    })
}

fn dirs() -> Vec<String> {
    let mut d = vec![];
    if let Ok(x) = std::env::var("POLDER_LOCALEDIR") { d.push(x); }
    if let Ok(exe) = std::env::current_exe() {
        // dev tree: shell/polder-shelf/target/release/<bin> -> config/locale
        if let Some(p) = exe.ancestors().nth(5) { d.push(p.join("config/locale").to_string_lossy().into()); }
    }
    d.push("/usr/share/polderos/config/locale".into());
    d.push("/usr/share/locale".into());
    d
}

fn parse_mo(b: &[u8]) -> Option<HashMap<String, &'static str>> {
    if b.len() < 28 { return None; }
    let le = u32::from_le_bytes(b[0..4].try_into().ok()?) == 0x950412de;
    let rd = |o: usize| -> Option<u32> { let s: [u8; 4] = b.get(o..o + 4)?.try_into().ok()?; Some(if le { u32::from_le_bytes(s) } else { u32::from_be_bytes(s) }) };
    if !le && rd(0)? != 0x950412de { return None; }
    let (n, oo, to) = (rd(8)? as usize, rd(12)? as usize, rd(16)? as usize);
    let mut m = HashMap::new();
    for i in 0..n {
        let (ol, oof) = (rd(oo + i * 8)? as usize, rd(oo + i * 8 + 4)? as usize);
        let (tl, tof) = (rd(to + i * 8)? as usize, rd(to + i * 8 + 4)? as usize);
        let id = std::str::from_utf8(b.get(oof..oof + ol)?).ok()?;
        let s = std::str::from_utf8(b.get(tof..tof + tl)?).ok()?;
        if id.is_empty() || s.is_empty() { continue; }
        let id = id.split('\0').next().unwrap_or(id); // plural: key on singular
        m.insert(id.to_string(), &*Box::leak(s.to_string().into_boxed_str()));
    }
    Some(m)
}

fn cat() -> &'static HashMap<String, &'static str> {
    CAT.get_or_init(|| {
        let l = language();
        if l == "en" { return HashMap::new(); }
        for d in dirs() {
            if let Ok(b) = std::fs::read(format!("{d}/{l}/LC_MESSAGES/polder.mo")) { if let Some(m) = parse_mo(&b) { return m; } }
        }
        HashMap::new()
    })
}

/// Translate an English msgid. Returns the msgid itself when there is no translation.
pub fn tr(id: &'static str) -> &'static str { cat().get(id).copied().unwrap_or(id) }
/// Translate a runtime string (e.g. a status id coming from JSON) if the catalog has it.
pub fn tr_dyn(id: &str) -> String { cat().get(id).map(|s| s.to_string()).unwrap_or_else(|| id.to_string()) }
/// Plural: n == 1 → singular msgid, else plural msgid (Dutch and English share this rule).
pub fn trn(one: &'static str, many: &'static str, n: u64) -> &'static str {
    if n == 1 { tr(one) } else { cat().get(one).and_then(|s| s.split('\0').nth(1)).unwrap_or(many) }
}

/// Runtime formatter for translated format strings: {} / {N} / {name}, with specs :.N  :o  :x  (others ignored).
pub fn fmt(t: &str, pos: &[&dyn std::fmt::Display], named: &[(&str, &dyn std::fmt::Display)]) -> String {
    let mut out = String::new(); let mut it = t.chars().peekable(); let mut next = 0usize;
    while let Some(c) = it.next() {
        if c == '{' {
            if it.peek() == Some(&'{') { it.next(); out.push('{'); continue; }
            let mut spec = String::new();
            for d in it.by_ref() { if d == '}' { break; } spec.push(d); }
            let (key, sp) = match spec.find(':') { Some(i) => (spec[..i].to_string(), spec[i + 1..].to_string()), None => (spec.clone(), String::new()) };
            let arg: Option<&dyn std::fmt::Display> = if key.is_empty() { let a = pos.get(next).copied(); next += 1; a }
                else if let Ok(i) = key.parse::<usize>() { pos.get(i).copied() }
                else { named.iter().find(|(k, _)| *k == key).map(|(_, v)| *v) };
            let Some(a) = arg else { out.push_str(&format!("{{{spec}}}")); continue };
            if let Some(p) = sp.strip_prefix('.') { out.push_str(&format!("{:.*}", p.parse().unwrap_or(0), a)); }
            else if sp == "o" || sp == "x" { let s = a.to_string(); match s.parse::<u64>() { Ok(n) => out.push_str(&if sp == "o" { format!("{n:o}") } else { format!("{n:x}") }), Err(_) => out.push_str(&s) } }
            else { out.push_str(&a.to_string()); }
        } else if c == '}' { if it.peek() == Some(&'}') { it.next(); } out.push('}'); }
        else { out.push(c); }
    }
    out
}

/// tf!("English {} with {name}", arg ; name) → translated + formatted String.
#[macro_export]
macro_rules! tf {
    ($s:literal $(, $a:expr)* $(; $($k:ident),*)?) => {
        crate::i18n::fmt(crate::i18n::tr($s), &[$(&$a as &dyn std::fmt::Display),*], &[$($((stringify!($k), &$k as &dyn std::fmt::Display)),*)?])
    };
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn formats() {
        assert_eq!(fmt("{} of {}", &[&1, &"b"], &[]), "1 of b");
        assert_eq!(fmt("{n} x {:.1}", &[&2.25f64], &[("n", &"a")]), "a x 2.2");
        assert_eq!(fmt("{{lit}} {:o}", &[&420u32], &[]), "{lit} 644");
    }
    #[test] fn dutch_catalog() {
        let b = std::fs::read(concat!(env!("CARGO_MANIFEST_DIR"), "/../../config/locale/nl/LC_MESSAGES/polder.mo")).unwrap();
        let m = parse_mo(&b).unwrap();
        assert_eq!(m["Settings"], "Instellingen");
        assert_eq!(m["Merge {} change(s)?"], "{} wijziging(en) overnemen?");
        assert_eq!(m["{} package"], "{} pakket\0{} pakketten");
    }
}

/// Mark a string for extraction in const/static context; translate it later with tr().
pub const fn n_(s: &'static str) -> &'static str { s }
