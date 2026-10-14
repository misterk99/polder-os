//! Material You "kleuren uit achtergrond": a Rust port of the relevant parts of Google's Material Color Utilities
//! (Apache-2.0): QuantizerWu + QuantizerWsmeans (= QuantizerCelebi), Score, CAM16/HCT and SchemeTonalSpot palettes.
//! Not in Debian's crate registry, hence implemented here; constants follow the MCU sources.

// ---------------- colour spaces ----------------
const SRGB_TO_XYZ: [[f64; 3]; 3] = [[0.41233895, 0.35762064, 0.18051042], [0.2126, 0.7152, 0.0722], [0.01932141, 0.11916382, 0.95034478]];
const XYZ_TO_SRGB: [[f64; 3]; 3] = [[3.2413774792388685, -1.5376652402851851, -0.49885366846268053],
    [-0.9691452513005321, 1.8758853451067872, 0.04156585616912061], [0.05562093689691305, -0.20395524564742123, 1.0571799111220335]];
const WHITE: [f64; 3] = [95.047, 100.0, 108.883];
fn mul(m: &[[f64; 3]; 3], v: [f64; 3]) -> [f64; 3] { [0, 1, 2].map(|i| m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]) }
fn linearized(c: u8) -> f64 { let n = c as f64 / 255.0; (if n <= 0.040449936 { n / 12.92 } else { ((n + 0.055) / 1.055).powf(2.4) }) * 100.0 }
fn delinearized(l: f64) -> u8 { let n = l / 100.0; let d = if n <= 0.0031308 { n * 12.92 } else { 1.055 * n.powf(1.0 / 2.4) - 0.055 }; (d * 255.0).round().clamp(0.0, 255.0) as u8 }
pub type Rgb = [u8; 3];
pub fn xyz_from_rgb(c: Rgb) -> [f64; 3] { mul(&SRGB_TO_XYZ, c.map(linearized)) }
fn lab_f(t: f64) -> f64 { let e = 216.0 / 24389.0; let k = 24389.0 / 27.0; if t > e { t.cbrt() } else { (k * t + 16.0) / 116.0 } }
pub fn lab_from_rgb(c: Rgb) -> [f64; 3] {
    let x = xyz_from_rgb(c); let f = [0, 1, 2].map(|i| lab_f(x[i] / WHITE[i]));
    [116.0 * f[1] - 16.0, 500.0 * (f[0] - f[1]), 200.0 * (f[1] - f[2])]
}
fn lab_finv(ft: f64) -> f64 { let e = 216.0 / 24389.0; let k = 24389.0 / 27.0; let c = ft * ft * ft; if c > e { c } else { (116.0 * ft - 16.0) / k } }
pub fn rgb_from_lab(l: [f64; 3]) -> Rgb {
    let fy = (l[0] + 16.0) / 116.0; let fx = l[1] / 500.0 + fy; let fz = fy - l[2] / 200.0;
    let xyz = [lab_finv(fx) * WHITE[0], lab_finv(fy) * WHITE[1], lab_finv(fz) * WHITE[2]];
    mul(&XYZ_TO_SRGB, xyz).map(delinearized)
}
pub fn y_from_lstar(l: f64) -> f64 { 100.0 * lab_finv((l + 16.0) / 116.0) }
pub fn lstar_from_y(y: f64) -> f64 { 116.0 * lab_f(y / 100.0) - 16.0 }
pub fn hex(c: Rgb) -> String { format!("#{:02x}{:02x}{:02x}", c[0], c[1], c[2]) }

// ---------------- CAM16 (default viewing conditions) ----------------
const M16: [[f64; 3]; 3] = [[0.401288, 0.650173, -0.051461], [-0.250268, 1.204414, 0.045854], [-0.002079, 0.048952, 0.953127]];
const M16INV: [[f64; 3]; 3] = [[1.8620678, -1.0112547, 0.14918678], [0.38752654, 0.62144744, -0.00897398], [-0.0158415, -0.03412294, 1.0499644]];
struct Vc { n: f64, aw: f64, nbb: f64, ncb: f64, c: f64, nc: f64, rgb_d: [f64; 3], fl: f64, z: f64 }
fn vc() -> Vc {
    let la = (200.0 / std::f64::consts::PI) * y_from_lstar(50.0) / 100.0;
    let rgb_w = mul(&M16, WHITE);
    let f = 0.8 + 2.0 / 10.0;
    let c = 0.59 + (0.69 - 0.59) * ((f - 0.9) * 10.0);
    let d = (f * (1.0 - (1.0 / 3.6) * ((-la - 42.0) / 92.0).exp())).clamp(0.0, 1.0);
    let rgb_d = rgb_w.map(|w| d * (100.0 / w) + 1.0 - d);
    let k = 1.0 / (5.0 * la + 1.0); let k4 = k.powi(4); let k4f = 1.0 - k4;
    let fl = k4 * la + 0.1 * k4f * k4f * (5.0 * la).cbrt();
    let n = y_from_lstar(50.0) / WHITE[1]; let z = 1.48 + n.sqrt(); let nbb = 0.725 / n.powf(0.2);
    let rgb_a = [0, 1, 2].map(|i| { let f = (fl * rgb_d[i] * rgb_w[i] / 100.0).powf(0.42); 400.0 * f / (f + 27.13) });
    let aw = (2.0 * rgb_a[0] + rgb_a[1] + 0.05 * rgb_a[2]) * nbb;
    Vc { n, aw, nbb, ncb: nbb, c, nc: f, rgb_d, fl, z }
}
/// (hue, chroma, J) of an sRGB colour
pub fn cam16(c: Rgb) -> (f64, f64, f64) {
    let v = vc(); let rgb_c = mul(&M16, xyz_from_rgb(c));
    let ra = [0, 1, 2].map(|i| { let d = v.rgb_d[i] * rgb_c[i]; let af = (v.fl * d.abs() / 100.0).powf(0.42); d.signum() * 400.0 * af / (af + 27.13) });
    let a = (11.0 * ra[0] - 12.0 * ra[1] + ra[2]) / 11.0; let b = (ra[0] + ra[1] - 2.0 * ra[2]) / 9.0;
    let u = (20.0 * ra[0] + 20.0 * ra[1] + 21.0 * ra[2]) / 20.0; let p2 = (40.0 * ra[0] + 20.0 * ra[1] + ra[2]) / 20.0;
    let mut hue = b.atan2(a).to_degrees(); if hue < 0.0 { hue += 360.0 } if hue >= 360.0 { hue -= 360.0 }
    let ac = p2 * v.nbb; let j = 100.0 * (ac / v.aw).powf(v.c * v.z);
    let hp = if hue < 20.14 { hue + 360.0 } else { hue };
    let e_hue = 0.25 * ((hp.to_radians() + 2.0).cos() + 3.8);
    let p1 = 50000.0 / 13.0 * e_hue * v.nc * v.ncb; let t = p1 * a.hypot(b) / (u + 0.305);
    let alpha = t.powf(0.9) * (1.64 - 0.29f64.powf(v.n)).powf(0.73);
    (hue, alpha * (j / 100.0).sqrt(), j)
}
/// linear sRGB (0..100) of CAM16 (J, C, h)
fn cam16_inv(j: f64, c: f64, h: f64, v: &Vc) -> [f64; 3] {
    let alpha = if c == 0.0 || j == 0.0 { 0.0 } else { c / (j / 100.0).sqrt() };
    let t = (alpha / (1.64 - 0.29f64.powf(v.n)).powf(0.73)).powf(1.0 / 0.9);
    let hr = h.to_radians(); let e_hue = 0.25 * ((hr + 2.0).cos() + 3.8);
    let ac = v.aw * (j / 100.0).powf(1.0 / v.c / v.z);
    let p1 = e_hue * (50000.0 / 13.0) * v.nc * v.ncb; let p2 = ac / v.nbb;
    let (hs, hc) = hr.sin_cos();
    let gamma = 23.0 * (p2 + 0.305) * t / (23.0 * p1 + 11.0 * t * hc + 108.0 * t * hs);
    let a = gamma * hc; let b = gamma * hs;
    let ra = [(460.0 * p2 + 451.0 * a + 288.0 * b) / 1403.0, (460.0 * p2 - 891.0 * a - 261.0 * b) / 1403.0, (460.0 * p2 - 220.0 * a - 6300.0 * b) / 1403.0];
    let rf = [0, 1, 2].map(|i| { let base = (27.13 * ra[i].abs() / (400.0 - ra[i].abs())).max(0.0); ra[i].signum() * (100.0 / v.fl) * base.powf(1.0 / 0.42) / v.rgb_d[i] });
    mul(&XYZ_TO_SRGB, mul(&M16INV, rf))
}
/// HCT -> sRGB: the colour with this hue and tone (L*) and the requested chroma, or the highest in-gamut chroma below it.
pub fn hct(h: f64, c: f64, t: f64) -> Rgb {
    if c < 0.5 || t <= 0.01 || t >= 99.99 { let y = y_from_lstar(t); let g = delinearized(y); return [g, g, g]; }
    let v = vc(); let ty = y_from_lstar(t);
    let solve = |c: f64| -> Option<[f64; 3]> {   // J with Y == ty (Y grows with J at fixed C, h)
        let (mut lo, mut hi) = (0.0f64, 100.0f64);
        for _ in 0..40 { let m = (lo + hi) / 2.0; let lin = cam16_inv(m, c, h, &v); let y = SRGB_TO_XYZ[1].iter().zip(lin).map(|(a, b)| a * b).sum::<f64>();
            if y < ty { lo = m } else { hi = m } }
        let lin = cam16_inv((lo + hi) / 2.0, c, h, &v);
        if lin.iter().all(|x| *x >= -0.01 && *x <= 100.01) { Some(lin) } else { None }
    };
    if let Some(l) = solve(c) { return l.map(|x| delinearized(x.clamp(0.0, 100.0))); }
    let (mut lo, mut hi) = (0.0, c); let mut best = None;
    for _ in 0..25 { let m = (lo + hi) / 2.0; match solve(m) { Some(l) => { best = Some(l); lo = m } None => hi = m } }
    best.map(|l| l.map(|x| delinearized(x.clamp(0.0, 100.0)))).unwrap_or_else(|| { let g = delinearized(ty); [g, g, g] })
}

// ---------------- QuantizerWu ----------------
const SIDE: usize = 33; const TOTAL: usize = SIDE * SIDE * SIDE;
fn idx(r: usize, g: usize, b: usize) -> usize { r * SIDE * SIDE + g * SIDE + b }
#[derive(Clone, Copy, Default)] struct Cube { r0: usize, r1: usize, g0: usize, g1: usize, b0: usize, b1: usize, vol: usize }
#[derive(Clone, Copy)] enum Dir { R, G, B }
struct Wu { w: Vec<i64>, mr: Vec<i64>, mg: Vec<i64>, mb: Vec<i64>, m: Vec<f64> }
impl Wu {
    fn vol_i(&self, c: &Cube, m: &[i64]) -> i64 {
        m[idx(c.r1, c.g1, c.b1)] - m[idx(c.r1, c.g1, c.b0)] - m[idx(c.r1, c.g0, c.b1)] + m[idx(c.r1, c.g0, c.b0)]
            - m[idx(c.r0, c.g1, c.b1)] + m[idx(c.r0, c.g1, c.b0)] + m[idx(c.r0, c.g0, c.b1)] - m[idx(c.r0, c.g0, c.b0)]
    }
    fn vol_f(&self, c: &Cube) -> f64 { let m = &self.m;
        m[idx(c.r1, c.g1, c.b1)] - m[idx(c.r1, c.g1, c.b0)] - m[idx(c.r1, c.g0, c.b1)] + m[idx(c.r1, c.g0, c.b0)]
            - m[idx(c.r0, c.g1, c.b1)] + m[idx(c.r0, c.g1, c.b0)] + m[idx(c.r0, c.g0, c.b1)] - m[idx(c.r0, c.g0, c.b0)] }
    fn bottom(c: &Cube, d: Dir, m: &[i64]) -> i64 { match d {
        Dir::R => -m[idx(c.r0, c.g1, c.b1)] + m[idx(c.r0, c.g1, c.b0)] + m[idx(c.r0, c.g0, c.b1)] - m[idx(c.r0, c.g0, c.b0)],
        Dir::G => -m[idx(c.r1, c.g0, c.b1)] + m[idx(c.r1, c.g0, c.b0)] + m[idx(c.r0, c.g0, c.b1)] - m[idx(c.r0, c.g0, c.b0)],
        Dir::B => -m[idx(c.r1, c.g1, c.b0)] + m[idx(c.r1, c.g0, c.b0)] + m[idx(c.r0, c.g1, c.b0)] - m[idx(c.r0, c.g0, c.b0)] } }
    fn top(c: &Cube, d: Dir, p: usize, m: &[i64]) -> i64 { match d {
        Dir::R => m[idx(p, c.g1, c.b1)] - m[idx(p, c.g1, c.b0)] - m[idx(p, c.g0, c.b1)] + m[idx(p, c.g0, c.b0)],
        Dir::G => m[idx(c.r1, p, c.b1)] - m[idx(c.r1, p, c.b0)] - m[idx(c.r0, p, c.b1)] + m[idx(c.r0, p, c.b0)],
        Dir::B => m[idx(c.r1, c.g1, p)] - m[idx(c.r1, c.g0, p)] - m[idx(c.r0, c.g1, p)] + m[idx(c.r0, c.g0, p)] } }
    fn variance(&self, c: &Cube) -> f64 {
        let (dr, dg, db) = (self.vol_i(c, &self.mr) as f64, self.vol_i(c, &self.mg) as f64, self.vol_i(c, &self.mb) as f64);
        let xx = self.vol_f(c); let v = self.vol_i(c, &self.w) as f64;
        if v == 0.0 { 0.0 } else { xx - (dr * dr + dg * dg + db * db) / v }
    }
    fn maximize(&self, c: &Cube, d: Dir, first: usize, last: usize, whole: [i64; 4]) -> (f64, i64) {
        let b = [Self::bottom(c, d, &self.mr), Self::bottom(c, d, &self.mg), Self::bottom(c, d, &self.mb), Self::bottom(c, d, &self.w)];
        let (mut max, mut cut) = (0.0, -1i64);
        for i in first..last {
            let h = [b[0] + Self::top(c, d, i, &self.mr), b[1] + Self::top(c, d, i, &self.mg), b[2] + Self::top(c, d, i, &self.mb), b[3] + Self::top(c, d, i, &self.w)];
            if h[3] == 0 { continue; }
            let mut t = ((h[0] * h[0] + h[1] * h[1] + h[2] * h[2]) as f64) / h[3] as f64;
            let h2 = [whole[0] - h[0], whole[1] - h[1], whole[2] - h[2], whole[3] - h[3]];
            if h2[3] == 0 { continue; }
            t += ((h2[0] * h2[0] + h2[1] * h2[1] + h2[2] * h2[2]) as f64) / h2[3] as f64;
            if t > max { max = t; cut = i as i64; }
        }
        (max, cut)
    }
    fn cut(&self, one: &mut Cube, two: &mut Cube) -> bool {
        let whole = [self.vol_i(one, &self.mr), self.vol_i(one, &self.mg), self.vol_i(one, &self.mb), self.vol_i(one, &self.w)];
        let (mr, cr) = self.maximize(one, Dir::R, one.r0 + 1, one.r1, whole);
        let (mg, cg) = self.maximize(one, Dir::G, one.g0 + 1, one.g1, whole);
        let (mb, cb) = self.maximize(one, Dir::B, one.b0 + 1, one.b1, whole);
        let d = if mr >= mg && mr >= mb { if cr < 0 { return false; } Dir::R } else if mg >= mr && mg >= mb { Dir::G } else { Dir::B };
        two.r1 = one.r1; two.g1 = one.g1; two.b1 = one.b1;
        match d {
            Dir::R => { one.r1 = cr as usize; two.r0 = one.r1; two.g0 = one.g0; two.b0 = one.b0; }
            Dir::G => { if cg < 0 { return false; } one.g1 = cg as usize; two.r0 = one.r0; two.g0 = one.g1; two.b0 = one.b0; }
            Dir::B => { if cb < 0 { return false; } one.b1 = cb as usize; two.r0 = one.r0; two.g0 = one.g0; two.b0 = one.b1; }
        }
        one.vol = (one.r1 - one.r0) * (one.g1 - one.g0) * (one.b1 - one.b0);
        two.vol = (two.r1 - two.r0) * (two.g1 - two.g0) * (two.b1 - two.b0);
        true
    }
}
fn quantize_wu(pixels: &[Rgb], max: usize) -> Vec<Rgb> {
    let mut q = Wu { w: vec![0; TOTAL], mr: vec![0; TOTAL], mg: vec![0; TOTAL], mb: vec![0; TOTAL], m: vec![0.0; TOTAL] };
    for p in pixels {
        let i = idx((p[0] >> 3) as usize + 1, (p[1] >> 3) as usize + 1, (p[2] >> 3) as usize + 1);
        q.w[i] += 1; q.mr[i] += p[0] as i64; q.mg[i] += p[1] as i64; q.mb[i] += p[2] as i64;
        q.m[i] += (p[0] as f64).powi(2) + (p[1] as f64).powi(2) + (p[2] as f64).powi(2);
    }
    for r in 1..SIDE {
        let (mut a, mut ar, mut ag, mut ab, mut a2) = (vec![0i64; SIDE], vec![0i64; SIDE], vec![0i64; SIDE], vec![0i64; SIDE], vec![0f64; SIDE]);
        for g in 1..SIDE {
            let (mut l, mut lr, mut lg, mut lb, mut l2) = (0i64, 0i64, 0i64, 0i64, 0f64);
            for b in 1..SIDE {
                let i = idx(r, g, b);
                l += q.w[i]; lr += q.mr[i]; lg += q.mg[i]; lb += q.mb[i]; l2 += q.m[i];
                a[b] += l; ar[b] += lr; ag[b] += lg; ab[b] += lb; a2[b] += l2;
                let p = idx(r - 1, g, b);
                q.w[i] = q.w[p] + a[b]; q.mr[i] = q.mr[p] + ar[b]; q.mg[i] = q.mg[p] + ag[b]; q.mb[i] = q.mb[p] + ab[b]; q.m[i] = q.m[p] + a2[b];
            }
        }
    }
    let mut cubes = vec![Cube::default(); max];
    cubes[0] = Cube { r0: 0, r1: SIDE - 1, g0: 0, g1: SIDE - 1, b0: 0, b1: SIDE - 1, vol: 0 };
    let mut var = vec![0.0; max]; let mut next = 0; let mut count = max; let mut i = 1;
    while i < max {
        let (mut one, mut two) = (cubes[next], cubes[i]);
        if q.cut(&mut one, &mut two) {
            cubes[next] = one; cubes[i] = two;
            var[next] = if one.vol > 1 { q.variance(&one) } else { 0.0 };
            var[i] = if two.vol > 1 { q.variance(&two) } else { 0.0 };
        } else { var[next] = 0.0; i -= 1; }
        next = 0; let mut t = var[0];
        for j in 1..=i { if var[j] > t { t = var[j]; next = j; } }
        if t <= 0.0 { count = i + 1; break; }
        i += 1;
    }
    cubes[..count].iter().filter_map(|c| { let w = q.vol_i(c, &q.w); if w <= 0 { return None; }
        Some([(q.vol_i(c, &q.mr) / w) as u8, (q.vol_i(c, &q.mg) / w) as u8, (q.vol_i(c, &q.mb) / w) as u8]) }).collect()
}

// ---------------- QuantizerWsmeans (k-means in L*a*b*, seeded with Wu) ----------------
fn quantize_wsmeans(pixels: &[Rgb], start: &[Rgb]) -> Vec<(Rgb, u32)> {
    let mut counts: std::collections::HashMap<Rgb, u32> = std::collections::HashMap::new();
    for p in pixels { *counts.entry(*p).or_default() += 1; }
    let pts: Vec<([f64; 3], u32)> = counts.iter().map(|(c, n)| (lab_from_rgb(*c), *n)).collect();
    let mut cl: Vec<[f64; 3]> = start.iter().map(|c| lab_from_rgb(*c)).collect();
    let d2 = |a: &[f64; 3], b: &[f64; 3]| (a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2);
    let mut assign = vec![usize::MAX; pts.len()];
    for _ in 0..10 {
        let mut moved = 0;
        for (k, (p, _)) in pts.iter().enumerate() {
            let best = (0..cl.len()).min_by(|a, b| d2(p, &cl[*a]).partial_cmp(&d2(p, &cl[*b])).unwrap()).unwrap();
            if best != assign[k] { assign[k] = best; moved += 1; }
        }
        let mut sum = vec![[0.0f64; 3]; cl.len()]; let mut w = vec![0u64; cl.len()];
        for (k, (p, n)) in pts.iter().enumerate() { let c = assign[k]; for i in 0..3 { sum[c][i] += p[i] * *n as f64; } w[c] += *n as u64; }
        for c in 0..cl.len() { if w[c] > 0 { cl[c] = sum[c].map(|s| s / w[c] as f64); } }
        if moved == 0 { break; }
    }
    let mut pop = vec![0u32; cl.len()]; for (k, (_, n)) in pts.iter().enumerate() { pop[assign[k]] += n; }
    let mut out: std::collections::HashMap<Rgb, u32> = std::collections::HashMap::new();
    for c in 0..cl.len() { if pop[c] > 0 { *out.entry(rgb_from_lab(cl[c])).or_default() += pop[c]; } }
    out.into_iter().collect()
}

// ---------------- Score ----------------
fn hue_diff(a: f64, b: f64) -> f64 { 180.0 - ((a - b).abs() - 180.0).abs() }
/// Up to `desired` seed colours, best first (MCU Score.score with filtering; fallback Google blue).
pub fn score(colors: &[(Rgb, u32)], desired: usize) -> Vec<Rgb> {
    let hcts: Vec<(Rgb, f64, f64)> = colors.iter().map(|(c, _)| { let (h, ch, _) = cam16(*c); (*c, h, ch) }).collect();
    let mut hue_pop = [0f64; 360]; let total: f64 = colors.iter().map(|x| x.1 as f64).sum();
    for (k, (_, n)) in colors.iter().enumerate() { hue_pop[(hcts[k].1.floor() as usize) % 360] += *n as f64; }
    let mut excited = [0f64; 360];
    for h in 0..360 { let p = hue_pop[h] / total; for i in (h as i64 - 14)..(h as i64 + 16) { excited[i.rem_euclid(360) as usize] += p; } }
    let mut scored: Vec<(f64, Rgb, f64)> = vec![];
    for (c, h, ch) in &hcts {
        let p = excited[(h.round() as i64).rem_euclid(360) as usize];
        if *ch < 5.0 || p <= 0.01 { continue; }
        let s = p * 100.0 * 0.7 + (ch - 48.0) * if *ch < 48.0 { 0.1 } else { 0.3 };
        scored.push((s, *c, *h));
    }
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let mut chosen: Vec<(Rgb, f64)> = vec![];
    for deg in (15..=90).rev() {
        chosen.clear();
        for (_, c, h) in &scored {
            if !chosen.iter().any(|(_, ch)| hue_diff(*h, *ch) < deg as f64) { chosen.push((*c, *h)); }
            if chosen.len() >= desired { break; }
        }
        if chosen.len() >= desired { break; }
    }
    if chosen.is_empty() { return vec![[0x42, 0x85, 0xf4]]; }
    chosen.into_iter().map(|x| x.0).collect()
}
/// QuantizerCelebi (Wu 128 -> WSMeans) + Score on the image pixels.
pub fn seeds(pixels: &[Rgb], desired: usize) -> Vec<Rgb> { let wu = quantize_wu(pixels, 128); score(&quantize_wsmeans(pixels, &wu), desired) }

/// SchemeTonalSpot roles mapped onto Polder OS palette.env keys.
pub fn palette(seed: Rgb, dark: bool) -> Vec<(&'static str, String)> {
    let (h, _, _) = cam16(seed);
    let p = |t| hex(hct(h, 36.0, t)); let n = |t| hex(hct(h, 6.0, t)); let nv = |t| hex(hct(h, 8.0, t));
    if !dark { vec![("SURFACE", n(98.0)), ("SURFACE_VARIANT", nv(92.0)), ("OUTLINE", nv(80.0)), ("ON_SURFACE", n(10.0)), ("ON_SURFACE_VARIANT", nv(30.0)),
                    ("ACCENT", p(40.0)), ("ACCENT_CONTAINER", p(90.0)), ("ON_ACCENT_CONTAINER", p(10.0)), ("ON_ACCENT", p(100.0))] }
    else { vec![("SURFACE", n(12.0)), ("SURFACE_VARIANT", nv(22.0)), ("OUTLINE", nv(30.0)), ("ON_SURFACE", n(90.0)), ("ON_SURFACE_VARIANT", nv(80.0)),
                ("ACCENT", p(80.0)), ("ACCENT_CONTAINER", p(30.0)), ("ON_ACCENT_CONTAINER", p(90.0)), ("ON_ACCENT", p(20.0))] }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn cam16_reference() {   // MCU cam_test: blue h 282.788 C 87.230 J 25.465; red h 27.408 C 113.357 J 46.445
        let (h, c, j) = cam16([0, 0, 255]); assert!((h - 282.788).abs() < 0.01 && (c - 87.230).abs() < 0.01 && (j - 25.465).abs() < 0.01, "{h} {c} {j}");
        let (h, c, j) = cam16([255, 0, 0]); assert!((h - 27.408).abs() < 0.01 && (c - 113.357).abs() < 0.01 && (j - 46.445).abs() < 0.01, "{h} {c} {j}");
    }
    #[test] fn hct_roundtrip() {
        for c in [[0x42u8, 0x85, 0xf4], [0xd9, 0x30, 0x25], [0x14, 0x6c, 0x2e]] {
            let (h, ch, _) = cam16(c); let t = lstar_from_y(xyz_from_rgb(c)[1]);
            let back = hct(h, ch, t); for i in 0..3 { assert!((back[i] as i32 - c[i] as i32).abs() <= 2, "{c:?} -> {back:?}"); }
        }
    }
    #[test] fn tones_are_monotonic() { let (h, _, _) = cam16([0x42, 0x85, 0xf4]);
        let ys: Vec<f64> = [10.0, 30.0, 50.0, 70.0, 90.0].iter().map(|t| xyz_from_rgb(hct(h, 36.0, *t))[1]).collect();
        assert!(ys.windows(2).all(|w| w[0] < w[1])); }
    #[test] fn single_colour_image() { let px = vec![[0x14u8, 0x6c, 0x2e]; 1000]; let s = seeds(&px, 4); assert_eq!(s.len(), 1);
        let (h1, _, _) = cam16(s[0]); let (h2, _, _) = cam16([0x14, 0x6c, 0x2e]); assert!(hue_diff(h1, h2) < 3.0); }
}
