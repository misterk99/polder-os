//! Launcher calculator: port of launcher.py calc(): safe arithmetic with Python semantics
//! (+ - * x × / ÷ // % ^ ** ( ), comma decimals; int/float like Python; exponents above 100 refused).
#[derive(Clone, Copy, Debug)] enum N { I(i128), F(f64) }
impl N { fn f(self) -> f64 { match self { N::I(i) => i as f64, N::F(f) => f } } }
struct P { t: Vec<char>, i: usize }
impl P {
    fn peek(&self, s: &str) -> bool { let c: Vec<char> = s.chars().collect(); self.t.len() >= self.i + c.len() && self.t[self.i..self.i + c.len()] == c[..] }
    fn eat(&mut self, s: &str) -> bool { if self.peek(s) { self.i += s.chars().count(); true } else { false } }
    fn ws(&mut self) { while self.i < self.t.len() && self.t[self.i] == ' ' { self.i += 1 } }
    fn expr(&mut self) -> Option<N> { let mut a = self.term()?; loop { self.ws();
        if self.eat("+") { a = add(a, self.term()?)? } else if self.eat("-") { a = sub(a, self.term()?)? } else { return Some(a) } } }
    fn term(&mut self) -> Option<N> { let mut a = self.unary()?; loop { self.ws();
        if self.peek("**") { return Some(a) }
        if self.eat("*") { a = mul(a, self.unary()?)? } else if self.eat("//") { a = fdiv(a, self.unary()?)? }
        else if self.eat("/") { let b = self.unary()?; if b.f() == 0.0 { return None } a = N::F(a.f() / b.f()) }
        else if self.eat("%") { a = modu(a, self.unary()?)? } else { return Some(a) } } }
    fn unary(&mut self) -> Option<N> { self.ws();
        if self.eat("-") { return Some(match self.unary()? { N::I(i) => N::I(-i), N::F(f) => N::F(-f) }) }
        if self.eat("+") { return self.unary() }
        self.power() }
    fn power(&mut self) -> Option<N> { let a = self.atom()?; self.ws();
        if self.eat("**") { let b = self.unary()?; if b.f().abs() > 100.0 { return None } return pow(a, b) } Some(a) }
    fn atom(&mut self) -> Option<N> { self.ws();
        if self.eat("(") { let v = self.expr()?; self.ws(); return if self.eat(")") { Some(v) } else { None } }
        let st = self.i; while self.i < self.t.len() && (self.t[self.i].is_ascii_digit() || self.t[self.i] == '.') { self.i += 1 }
        let s: String = self.t[st..self.i].iter().collect(); if s.is_empty() { return None }
        if s.contains('.') { if s.matches('.').count() > 1 || s == "." { return None } s.parse().ok().map(N::F) } else { s.parse().ok().map(N::I) } }
}
fn add(a: N, b: N) -> Option<N> { match (a, b) { (N::I(x), N::I(y)) => x.checked_add(y).map(N::I), _ => Some(N::F(a.f() + b.f())) } }
fn sub(a: N, b: N) -> Option<N> { match (a, b) { (N::I(x), N::I(y)) => x.checked_sub(y).map(N::I), _ => Some(N::F(a.f() - b.f())) } }
fn mul(a: N, b: N) -> Option<N> { match (a, b) { (N::I(x), N::I(y)) => x.checked_mul(y).map(N::I), _ => Some(N::F(a.f() * b.f())) } }
fn fdiv(a: N, b: N) -> Option<N> { if b.f() == 0.0 { return None } match (a, b) { (N::I(x), N::I(y)) => Some(N::I(x.div_euclid(y) - if y < 0 && x.rem_euclid(y) != 0 { 1 } else { 0 })), _ => Some(N::F((a.f() / b.f()).floor())) } }
fn modu(a: N, b: N) -> Option<N> { if b.f() == 0.0 { return None }
    match (a, b) { (N::I(x), N::I(y)) => { let r = x % y; Some(N::I(if r != 0 && (r < 0) != (y < 0) { r + y } else { r })) }
        _ => { let (x, y) = (a.f(), b.f()); let r = x % y; Some(N::F(if r != 0.0 && (r < 0.0) != (y < 0.0) { r + y } else { r })) } } }
fn pow(a: N, b: N) -> Option<N> { match (a, b) {
    (N::I(x), N::I(y)) if y >= 0 => x.checked_pow(y as u32).map(N::I),
    _ => { if a.f() == 0.0 && b.f() < 0.0 { return None } let r = a.f().powf(b.f()); if r.is_nan() { None } else { Some(N::F(r)) } } } }

/// Formatted result (ints with space thousands separators, floats with a decimal comma) or None.
pub fn calc(q: &str) -> Option<String> {
    let s = q.trim().replace(',', ".").replace('×', "*").replace('x', "*").replace('÷', "/").replace('^', "**");
    if s.is_empty() || !s.chars().any(|c| c.is_ascii_digit()) || !s.chars().any(|c| "+-*/%".contains(c)) || s.chars().any(|c| !"0123456789.+-*/%() ".contains(c)) { return None; }
    let mut p = P { t: s.chars().collect(), i: 0 }; let v = p.expr()?; p.ws(); if p.i != p.t.len() { return None; }
    let v = match v { N::F(f) => { if !f.is_finite() { return None } let r = (f * 1e10).round() / 1e10; if r == r.trunc() && r.abs() < 1e18 { N::I(r as i128) } else { N::F(r) } } i => i };
    Some(match v {
        N::I(i) => { let d = i.abs().to_string(); let mut o = String::new();
            for (k, c) in d.chars().enumerate() { if k > 0 && (d.len() - k) % 3 == 0 { o.push(' ') } o.push(c) } if i < 0 { format!("-{o}") } else { o } }
        N::F(f) => format!("{f}").replace('.', ","),
    })
}
#[cfg(test)]
mod tests { use super::calc;
    #[test] fn python_semantics() {
        for (q, r) in [("2+2", Some("4")), ("12*12", Some("144")), ("1000*1000", Some("1 000 000")), ("7/2", Some("3,5")), ("1,5+1", Some("2,5")),
                       ("2^10", Some("1 024")), ("-2**2", Some("-4")), ("-7//2", Some("-4")), ("-7%3", Some("2")), ("10/4*2", Some("5")), ("0.1+0.2", Some("0,3")),
                       ("1/0", None), ("2**200", None), ("abc", None), ("12", None), ("3x4", Some("12")), ("(1+2)*3", Some("9")), ("2**-1", Some("0,5")), ("1/3", Some("0,3333333333"))] {
            assert_eq!(calc(q).as_deref(), r, "{q}");
        }
    }
}
