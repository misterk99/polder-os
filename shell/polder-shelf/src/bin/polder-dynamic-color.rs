//! polder-dynamic-color <image> [--seeds] [--index N] [--theme light|dark]
//! --seeds: up to four seed colours (best first), one #rrggbb per line.  Otherwise: palette.env lines for the theme.
#[path = "../i18n.rs"] #[macro_use] mod i18n;
#[allow(unused_imports)] use i18n::tr;
#[path = "../dyncolor.rs"] mod dyncolor;
use gtk::gdk_pixbuf::{InterpType, Pixbuf};
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let Some(img) = a.get(1) else { eprintln!("usage: polder-dynamic-color <image> [--seeds] [--index N] [--theme light|dark]"); std::process::exit(2) };
    let opt = |k: &str| a.iter().position(|x| x == k).and_then(|i| a.get(i + 1)).cloned();
    let pb = match Pixbuf::from_file(img) { Ok(p) => p, Err(e) => { eprintln!("{img}: {e}"); std::process::exit(1) } };
    // ~128 px on the long side, like MCU's resize before quantizing: fast and stable
    let (w, h) = (pb.width(), pb.height()); let s = 128.0 / w.max(h) as f64;
    let pb = pb.scale_simple(((w as f64 * s).round() as i32).max(1), ((h as f64 * s).round() as i32).max(1), InterpType::Bilinear).unwrap();
    let (n, rs, ch) = (pb.n_channels() as usize, pb.rowstride() as usize, pb.has_alpha());
    let bytes = pb.read_pixel_bytes(); let mut px = vec![];
    for y in 0..pb.height() as usize { for x in 0..pb.width() as usize { let o = y * rs + x * n;
        if ch && bytes[o + 3] < 255 { continue; } px.push([bytes[o], bytes[o + 1], bytes[o + 2]]); } }
    let seeds = dyncolor::seeds(&px, 4);
    if a.iter().any(|x| x == "--seeds") { for s in &seeds { println!("{}", dyncolor::hex(*s)); } return; }
    let i: usize = opt("--index").and_then(|s| s.parse().ok()).unwrap_or(0).min(seeds.len() - 1);
    let dark = opt("--theme").as_deref() == Some("dark");
    println!("SEED={}", dyncolor::hex(seeds[i]));
    for (k, v) in dyncolor::palette(seeds[i], dark) { println!("{k}={v}"); }
}
