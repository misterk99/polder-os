#!/usr/bin/env python3
"""'Polderheuvel' wallpaper for Polder OS: original procedural artwork (rolling hill + blue sky + clouds,
with a sloot, a distant windmill and a few cows). usage: make-polder.py  -> writes polderheuvel*.png here."""
import math, random, os
from PIL import Image, ImageDraw, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__)); W, H = 1920, 1080

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def vgrad(w, h, stops):
    im = Image.new('RGB', (1, h)); px = im.load()
    for y in range(h):
        t = y / (h - 1)
        for i in range(len(stops) - 1):
            (t0, c0), (t1, c1) = stops[i], stops[i + 1]
            if t0 <= t <= t1: px[0, y] = lerp(c0, c1, (t - t0) / (t1 - t0)); break
    return im.resize((w, h))

def hill_y(x, base, amp):  # smooth Bliss-like rolling crest
    u = x / W
    return base - amp * (0.75 * math.exp(-((u - 0.38) / 0.33) ** 2) + 0.35 * math.exp(-((u - 0.95) / 0.25) ** 2)) - 18 * math.sin(u * 5.1)

def make(evening=False):
    rnd = random.Random(7)
    if not evening: sky = vgrad(W, H, [(0, (22, 86, 196)), (0.45, (74, 144, 226)), (0.75, (170, 210, 245)), (1, (205, 228, 250))])
    else: sky = vgrad(W, H, [(0, (12, 18, 48)), (0.4, (40, 42, 92)), (0.62, (150, 84, 110)), (0.72, (242, 150, 96)), (1, (250, 190, 120))])
    img = sky.convert('RGBA')
    # stars (evening) / clouds
    if evening:
        d = ImageDraw.Draw(img)
        for _ in range(140):
            x, y = rnd.randrange(W), rnd.randrange(int(H * 0.45)); r = rnd.choice([1, 1, 1, 2])
            d.ellipse([x, y, x + r, y + r], fill=(255, 255, 255, rnd.randrange(90, 230)))
    cl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(cl)
    for cx, cy, s in [(330, 210, 1.2), (900, 140, 0.9), (1450, 260, 1.4), (1750, 120, 0.7), (620, 360, 0.8), (1200, 400, 0.6)]:
        for _ in range(int(60 * s)):
            rx, ry = rnd.uniform(25, 75) * s, rnd.uniform(18, 42) * s
            x, y = cx + rnd.gauss(0, 110 * s), cy - abs(rnd.gauss(0, 26 * s))
            col = (255, 255, 255, 70) if not evening else (255, 190, 170, 34)
            d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=col)
    cl = cl.filter(ImageFilter.GaussianBlur(9)); img = Image.alpha_composite(img, cl)
    # distant flat polder strip + windmill on the horizon (left) behind the hill
    hz = int(H * 0.60)
    far = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(far)
    d.rectangle([0, hz, W, H], fill=(96, 150, 92, 255) if not evening else (40, 52, 46, 255))
    mx, my = 1530, hz; mc = (60, 78, 70, 255) if not evening else (20, 22, 34, 255)
    d.polygon([(mx - 14, my), (mx + 14, my), (mx + 8, my - 62), (mx - 8, my - 62)], fill=mc)   # body
    d.polygon([(mx - 11, my - 62), (mx + 11, my - 62), (mx, my - 74)], fill=mc)                # cap
    hub = (mx, my - 64)
    for a in (20, 110, 200, 290):                                                            # sails
        r = math.radians(a); ex, ey = hub[0] + 58 * math.cos(r), hub[1] + 58 * math.sin(r)
        nx, ny = -math.sin(r) * 7, math.cos(r) * 7
        d.polygon([(hub[0], hub[1]), (ex, ey), (ex + nx, ey + ny), (hub[0] + nx * 0.3, hub[1] + ny * 0.3)], fill=mc)
    for x in range(0, W, 140):  # far tree line dots
        if abs(x - mx) > 60: d.ellipse([x, hz - 9, x + 22 + (x * 7) % 18, hz + 3], fill=(74, 118, 74, 255) if not evening else (30, 38, 36, 255))
    img = Image.alpha_composite(img, far.filter(ImageFilter.GaussianBlur(1.2)))
    # the hill
    hill = Image.new('RGBA', (W, H), (0, 0, 0, 0)); mask = Image.new('L', (W, H), 0); md = ImageDraw.Draw(mask)
    pts = [(x, hill_y(x, H * 0.70, 230)) for x in range(0, W + 1, 8)]
    md.polygon(pts + [(W, H), (0, H)], fill=255)
    top, bot = ((126, 196, 64), (38, 110, 34)) if not evening else ((58, 86, 48), (16, 34, 20))
    hill = vgrad(W, H, [(0, top), (0.55, top), (1, bot)]).convert('RGBA'); hill.putalpha(mask)
    # soft light on the crest + mottled grass
    tex = Image.effect_noise((W, H), 28).convert('L').filter(ImageFilter.GaussianBlur(6))
    shade = Image.merge('RGBA', (tex, tex, tex, Image.new('L', (W, H), 26)))
    img = Image.alpha_composite(img, hill)
    sh = Image.new('RGBA', (W, H)); sh.paste(shade, mask=mask); img = Image.alpha_composite(img, sh)
    # sloot: a straight ditch running from bottom-right up the hill, narrowing (perspective)
    dd = ImageDraw.Draw(img)
    x0, y0 = 1180, H; x1 = 820; y1 = hill_y(x1, H * 0.70, 230) + 40
    water = (150, 196, 236, 235) if not evening else (232, 150, 110, 200)
    dd.polygon([(x0 - 70, y0), (x0 + 70, y0), (x1 + 4, y1), (x1 - 4, y1)], fill=water)
    dd.line([(x0 - 70, y0), (x1 - 4, y1)], fill=(30, 90, 30, 200) if not evening else (14, 28, 18, 220), width=4)
    # cows: a few black-and-white dots on the slope
    for cx, cy in [(520, 0), (575, 6), (640, -4), (1380, 0)]:
        y = hill_y(cx, H * 0.70, 230) + 70 + cy; s = 1 if cx < 1000 else 0.8
        dd.ellipse([cx, y, cx + 18 * s, y + 9 * s], fill=(245, 245, 240) if not evening else (120, 120, 130))
        dd.ellipse([cx + 3 * s, y + 1, cx + 9 * s, y + 7 * s], fill=(25, 25, 25))
        dd.ellipse([cx + 15 * s, y - 2, cx + 21 * s, y + 4 * s], fill=(25, 25, 25))
    img = img.convert('RGB')
    suf = '-avond' if evening else ''
    img.save(os.path.join(HERE, f'polderheuvel{suf}-1920.png'))
    img.resize((1366, 768), Image.LANCZOS).save(os.path.join(HERE, f'polderheuvel{suf}.png'))

def logo():
    """Polder OS mark: white windmill sails on a rounded accent-blue square, plus a green 'polder' band."""
    S = 256; im = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, S - 1, S - 1], 64, fill=(11, 87, 208, 255))
    d.rounded_rectangle([0, 176, S - 1, S - 1], 64, fill=(52, 168, 83, 255)); d.rectangle([0, 176, S - 1, 200], fill=(52, 168, 83, 255))
    c = (128, 112)
    for a in (45, 135, 225, 315):
        r = math.radians(a); ex, ey = c[0] + 86 * math.cos(r), c[1] + 86 * math.sin(r); nx, ny = -math.sin(r) * 22, math.cos(r) * 22
        d.polygon([c, (ex, ey), (ex + nx, ey + ny), (c[0] + nx * 0.25, c[1] + ny * 0.25)], fill=(255, 255, 255, 255))
    d.ellipse([c[0] - 12, c[1] - 12, c[0] + 12, c[1] + 12], fill=(255, 255, 255, 255))
    out = os.path.join(HERE, '..', 'brand'); os.makedirs(out, exist_ok=True)
    im.save(os.path.join(out, 'polderos-logo.png')); im.resize((64, 64), Image.LANCZOS).save(os.path.join(out, 'polderos-logo-64.png'))

make(False); make(True); logo()
