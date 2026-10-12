"""Trace a reference image into a TUI character keyframe, and render it back.

  python -B tui_char.py render ref.jpg out/david
  python -B tui_char.py anim   ref.jpg out/david.gif

A keyframe is three equal-size string layers, in the spirit of the reference project's
poses/<pose>.txt:

  art    outline + feature glyphs; ':' = interior cell (fillable with a text stream)
  shade  brightness 0-7 per cell
  part   colour class per cell: d dark / s skin / g green / b blue / l light, ' ' empty
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

CW, CH = 5, 10                      # one cell on screen: 5 x 10 px (1:2, like a terminal)
COLS, ROWS = 96, 64
W, H = COLS * CW, ROWS * CH
FS = 9
FONT_B = "C:/Windows/Fonts/consolab.ttf"

BG = (4, 7, 15)
# part -> (lo, mid, hi) colour ramp
PALETTES = {
    "mono": {
        "d": ((16, 26, 50), (66, 106, 186), (198, 224, 255)),
        "s": ((16, 26, 50), (66, 106, 186), (198, 224, 255)),
        "g": ((16, 26, 50), (66, 106, 186), (198, 224, 255)),
        "b": ((16, 26, 50), (80, 126, 210), (208, 232, 255)),
        "l": ((26, 42, 78), (108, 154, 226), (226, 242, 255)),
    },
    "duo": {
        "d": ((12, 18, 34), (54, 82, 142), (178, 208, 248)),
        "s": ((38, 24, 26), (146, 100, 96), (228, 192, 180)),
        "g": ((26, 36, 14), (124, 172, 50), (212, 240, 132)),
        "b": ((10, 28, 52), (46, 122, 212), (156, 212, 255)),
        "l": ((28, 44, 80), (128, 170, 228), (236, 246, 255)),
    },
}
GLYPHS = {
    "": " ", "h": "-", "v": "|", "d1": "/", "d2": "\\",
    "t1": "'", "t2": ",", "dot": ".", "fill": ":",
}


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def fit_cover(img: Image.Image, crop=None) -> Image.Image:
    if crop:
        iw, ih = img.size
        l, t, r, b = crop
        img = img.crop((int(l * iw), int(t * ih), int(r * iw), int(b * ih)))
    iw, ih = img.size
    k = max(W / iw, H / ih)
    img = img.resize((max(W, int(round(iw * k))), max(H, int(round(ih * k)))), Image.LANCZOS)
    iw, ih = img.size
    return img.crop(((iw - W) // 2, (ih - H) // 2, (iw - W) // 2 + W, (ih - H) // 2 + H))


def block_mean(a, rows=None, cols=None, ch=CH, cw=CW):
    rows = ROWS if rows is None else rows      # 取全局值：换网格密度时就地生效
    cols = COLS if cols is None else cols
    a = a[: rows * ch, : cols * cw, ...]
    shape = (rows, ch, cols, cw) + a.shape[2:]
    return a.reshape(shape).mean(axis=(1, 3))


def sobel(gray):
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = 0.5 * (gray[:, 2:] - gray[:, :-2])
    gy[1:-1, :] = 0.5 * (gray[2:, :] - gray[:-2, :])
    return gx, gy


def classify(rgb, hsv):
    """mean rgb/hsv of one cell -> part letter"""
    h, s, v = float(hsv[0]), float(hsv[1]), float(hsv[2])
    r, g, b = [float(x) for x in rgb]
    if v < 0.16 and s < 0.5:
        return "d"
    if s < 0.09 and v > 0.55:
        return "l"
    if h >= 0.78 and 0.09 <= s <= 0.24 and v > 0.60:
        return "s"          # 浅粉/暖白：动漫皮肤的常见色调，别落到蓝白上
    if h < 0.10 and s >= 0.09 and v > 0.42:
        return "s"
    if 0.11 <= h <= 0.30 and s > 0.17:
        return "g"
    if 0.50 <= h <= 0.75 and s > 0.17:
        return "b"
    if v < 0.34:
        return "d"
    if s < 0.25:
        return "l" if v > 0.55 else "d"
    return "s" if h < 0.5 else "b"


def trace(img: Image.Image):
    src = fit_cover(img).filter(ImageFilter.GaussianBlur(0.9))
    arr = np.asarray(src).astype(np.float32) / 255.0
    gray = arr[..., 0] * 0.3 + arr[..., 1] * 0.59 + arr[..., 2] * 0.11
    lum = block_mean(gray)
    rgbm = block_mean(arr)
    hsvm = block_mean(np.asarray(src.convert("HSV")).astype(np.float32) / 255.0)

    # background: dark cells reachable from the border
    dark = lum < 0.155
    bg = np.zeros_like(dark, bool)
    q = deque()
    for c in range(COLS):
        for r in (0, ROWS - 1):
            if dark[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))
    for r in range(ROWS):
        for c in (0, COLS - 1):
            if dark[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))
    while q:
        r, c = q.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < ROWS and 0 <= cc < COLS and dark[rr, cc] and not bg[rr, cc]:
                bg[rr, cc] = True
                q.append((rr, cc))
    cover = ~bg

    gx, gy = sobel(gray)
    Jxx = block_mean(gx * gx)
    Jyy = block_mean(gy * gy)
    Jxy = block_mean(gx * gy)

    part = np.full((ROWS, COLS), " ", dtype="<U1")
    for r in range(ROWS):
        for c in range(COLS):
            if cover[r, c]:
                part[r, c] = classify(rgbm[r, c], hsvm[r, c])

    shade = np.zeros((ROWS, COLS), int)
    shade[cover] = np.clip(np.round(7 * np.power(np.clip(lum[cover], 0, 1), 0.9)), 0, 7).astype(int)

    # region boundaries: where two different parts meet
    bound = np.zeros((ROWS, COLS), bool)
    for r in range(ROWS):
        for c in range(COLS):
            if not cover[r, c]:
                continue
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    bound[r, c] = True
                    break
                if part[rr, cc] != part[r, c] and abs(int(shade[rr, cc]) - int(shade[r, c])) >= 2:
                    bound[r, c] = True
                    break

    art = np.full((ROWS, COLS), " ", dtype="<U1")
    for r in range(ROWS):
        for c in range(COLS):
            if not cover[r, c]:
                continue
            art[r, c] = ":" if not bound[r, c] else "?"
            if not bound[r, c]:
                continue
            jxx, jyy, jxy = float(Jxx[r, c]), float(Jyy[r, c]), float(Jxy[r, c])
            tr = jxx + jyy
            det = jxx * jyy - jxy * jxy
            coh = 0.0 if tr < 1e-12 else math.sqrt(max(0.0, (tr * tr - 4 * det))) / tr
            if coh < 0.42 or tr < 4e-5:
                art[r, c] = "." if shade[r, c] <= 2 else "'"
                continue
            tang = 0.5 * math.atan2(2 * jxy, jxx - jyy) + math.pi / 2
            sx_, sy_ = math.cos(tang), math.sin(tang)
            a = math.degrees(math.atan2(sy_ * CH, sx_ * CW))
            a = ((a + 90.0) % 180.0) - 90.0          # fold to [-90, 90)
            m = abs(a)
            if m < 22:
                art[r, c] = "-"
            elif m < 76:
                art[r, c] = "\\" if a > 0 else "/"
            else:
                art[r, c] = "|"
    # faces: the interior of every sizeable skin region (the text stream is not drawn there)
    plain = np.zeros((ROWS, COLS), bool)
    seen = np.zeros((ROWS, COLS), bool)
    for r0 in range(ROWS):
        for c0 in range(COLS):
            if part[r0, c0] != "s" or seen[r0, c0]:
                continue
            comp, q = [], deque([(r0, c0)])
            seen[r0, c0] = True
            while q:
                rr, cc = q.popleft()
                comp.append((rr, cc))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    r2, c2 = rr + dr, cc + dc
                    if 0 <= r2 < ROWS and 0 <= c2 < COLS and not seen[r2, c2] and part[r2, c2] == "s":
                        seen[r2, c2] = True
                        q.append((r2, c2))
            if len(comp) < 8:
                continue
            for (r, c) in comp:
                if all(0 <= r + dr < ROWS and 0 <= c + dc < COLS and part[r + dr, c + dc] == "s"
                       for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    plain[r, c] = True

    # small features everywhere: a cell that differs from its neighbours in luminance gets a mark.
    # eyes, mouths, shard edges and glass lines are all just that, and they must survive the grid.
    for r in range(1, ROWS - 1):
        for c in range(1, COLS - 1):
            if not cover[r, c] or art[r, c] != ":":
                continue
            nb = [float(lum[r + dr, c + dc]) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                  if dr or dc]
            d0 = float(lum[r, c]) - sum(nb) / len(nb)
            if abs(d0) > (0.030 if plain[r, c] else 0.055):
                art[r, c] = "." if d0 < 0 else "'"

    return art, shade, part, cover, plain


def ramp(part_letter, level, palette):
    lo, mid, hi = PALETTES[palette][part_letter]
    level = max(0.0, min(1.0, level))
    return mix(lo, mid, level / 0.55) if level < 0.55 else mix(mid, hi, (level - 0.55) / 0.45)


def draw_frame(art, shade, part, palette, underlay=True, postfx=True, stream=None, stream_off=0, plain=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_B, FS)
    n = 0
    for r in range(ROWS):
        for c in range(COLS):
            ch = art[r][c]
            if ch == " ":
                continue
            p = part[r][c]
            lv = (int(shade[r][c]) if str(shade[r][c]).isdigit() else 0) / 7.0
            if underlay:
                d.rectangle([c * CW, r * CH, c * CW + CW - 2, r * CH + CH - 2],
                            fill=ramp(p, 0.16 + 0.60 * lv, palette))
            if ch == ":":
                if plain is not None and plain[r][c]:
                    continue
                if stream is None:
                    continue
                ch = stream[(n + stream_off) % len(stream)]
                n += 1
                d.text((c * CW, r * CH - 1), ch, font=font, fill=ramp(p, 0.42 + 0.30 * lv, palette))
                continue
            d.text((c * CW, r * CH - 1), ch, font=font, fill=ramp(p, 0.55 + 0.45 * lv, palette))
    if postfx:
        glow = img.filter(ImageFilter.GaussianBlur(3.5))
        img = ImageChops.add(img, glow.point(lambda v: int(v * 0.30)))
        sl = Image.new("RGB", (W, H), (0, 0, 0))
        ds = ImageDraw.Draw(sl)
        for y in range(0, H, 3):
            ds.line([0, y, W, y], fill=(0, 0, 0, 0))
        img = ImageChops.subtract(img, sl.point(lambda v: 12 if v else 0))
        vg = Image.new("L", (COLS, ROWS), 0)
        pv = vg.load()
        for r in range(ROWS):
            for c in range(COLS):
                dx, dy = (c - COLS / 2) / (COLS / 2), (r - ROWS / 2) / (ROWS / 2)
                pv[c, r] = int(255 * min(1.0, max(0.0, (dx * dx + dy * dy) - 0.40) * 0.62))
        img = Image.composite(img, Image.new("RGB", (W, H), BG), ImageChops.invert(
            vg.resize((W, H), Image.BILINEAR)))
    return img


# ---------------------------------------------------------------- motion (string ops)

def _blank(a, r, c0, c1):
    for c in range(c0, c1):
        a[r][c] = " "
        a[r][c] = " "


def shift_rows(art, shade, part, amount):
    """amount(r) -> integer column shift of that row"""
    na = [[c for c in row] for row in art]
    ns = [[c for c in row] for row in shade]
    np_ = [[c for c in row] for row in part]
    for r in range(ROWS):
        k = int(round(amount(r)))
        if k == 0:
            continue
        row_a, row_s, row_p = na[r], ns[r], np_[r]
        if k > 0:
            row_a[k:], row_s[k:], row_p[k:] = row_a[:-k], row_s[:-k], row_p[:-k]
            for c in range(k):
                row_a[c] = row_s[c] = row_p[c] = " "
        else:
            k = -k
            row_a[:-k], row_s[:-k], row_p[:-k] = row_a[k:], row_s[k:], row_p[k:]
            for c in range(COLS - k, COLS):
                row_a[c] = row_s[c] = row_p[c] = " "
    return ["".join(x) for x in na], ["".join(x) for x in ns], ["".join(x) for x in np_]


def scramble(art, amount, rng):
    """corrupt glyphs and tear runs, in place: the three layers must stay aligned"""
    S = "#%&@$*+=<>/\\|?!01"
    out = []
    for r, row in enumerate(art):
        chars = list(row)
        if amount > 0 and rng.random() < amount * 0.12:
            c0 = rng.randint(0, max(0, COLS - 9))
            for c in range(c0, min(COLS, c0 + rng.randint(3, 9))):
                chars[c] = " "
        for c, ch in enumerate(chars):
            if ch != " " and rng.random() < amount * 0.35:
                chars[c] = rng.choice(S)
        out.append("".join(chars))
    return out


def materialise(art, shade, part, p, rng, order):
    """cells switch on in a fixed random order, each one flickering first"""
    na, ns, npart = [], [], []
    for r in range(ROWS):
        ra, rs, rp = [], [], []
        for c in range(COLS):
            o = order[r][c]
            if o > p:
                ra.append(" "); rs.append("0"); rp.append(" ")
            elif o > p - 0.10 and part[r][c] != " ":
                ra.append(rng.choice("#%&@$*<>/\\|")); rs.append(shade[r][c]); rp.append(part[r][c])
            else:
                ra.append(art[r][c]); rs.append(shade[r][c]); rp.append(part[r][c])
        na.append("".join(ra)); ns.append("".join(rs)); npart.append("".join(rp))
    return na, ns, npart


def neck_row(part):
    best, bestw = ROWS // 2, 10 ** 9
    c0, c1 = COLS // 4, COLS * 3 // 4
    for r in range(int(ROWS * 0.30), int(ROWS * 0.72)):
        w = sum(1 for c in range(c0, c1) if part[r][c] == "s")
        if 0 < w < bestw:
            bestw, best = w, r
    return best


def pose(art, shade, part, sway=0.0, head=0.0, squash_rows=0, hop_cols=0, neck=None, feet=None):
    feet = ROWS if feet is None else feet
    a, s, p = shift_rows(art, shade, part,
                         lambda r: math.tan(math.radians(sway)) * (feet - r) * (CH / CW) + hop_cols)
    if head and neck is not None:
        a, s, p = shift_rows(a, s, p,
                             lambda r: (math.tan(math.radians(head)) * (r - neck) * (CH / CW) if r < neck else 0.0))
    if squash_rows:
        a = a[:ROWS - squash_rows] + [a[ROWS - squash_rows - 1]] * squash_rows
        s = s[:ROWS - squash_rows] + [s[ROWS - squash_rows - 1]] * squash_rows
        p = p[:ROWS - squash_rows] + [p[ROWS - squash_rows - 1]] * squash_rows
    return a, s, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["trace", "render", "anim", "asset"])
    ap.add_argument("ref")
    ap.add_argument("out")
    ap.add_argument("--crop", help="l,t,r,b in 0-1")
    ap.add_argument("--stream", default="")
    ap.add_argument("--name", default="", help="asset: 中文名，会印在窗框上")
    ap.add_argument("--alias", default="", help="asset: 逗号分隔的别名（模型可以用它点名）")
    ap.add_argument("--tags", default="", help="asset: 逗号分隔的标签")
    a = ap.parse_args()

    crop = [float(x) for x in a.crop.split(",")] if a.crop else None
    img = Image.open(a.ref).convert("RGB")
    if crop:
        iw, ih = img.size
        img = img.crop((int(crop[0] * iw), int(crop[1] * ih), int(crop[2] * iw), int(crop[3] * ih)))
    for p in (Path(a.out).parent,):
        p.mkdir(parents=True, exist_ok=True)

    art, shade, part, cover, plain = trace(img)
    print(f"cells {COLS}x{ROWS}  covered {int(cover.sum())} ({cover.mean()*100:.1f}%)")
    counts = {}
    for r in range(ROWS):
        for c in range(COLS):
            if cover[r, c]:
                counts[part[r][c]] = counts.get(part[r][c], 0) + 1
    print("parts:", {k: v for k, v in sorted(counts.items(), key=lambda x: -x[1])})

    if a.cmd == "trace":
        txt = "\n".join(["[art]"] + list(art) + ["[shade]"] +
                        ["".join(str(x) for x in row) for row in shade] + ["[part]"] + list(part)) + "\n"
        Path(a.out).write_text(txt, encoding="utf-8")
        print("wrote", a.out)
        return

    if a.cmd == "asset":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        rows = lambda M: ["".join(str(c) for c in row) for row in M]
        shade_rows = ["".join(str(int(x)) for x in row) for row in shade]
        key = {
            "id": out.name,
            "name": a.name or out.name,
            "aliases": [s.strip() for s in a.alias.split(",") if s.strip()],
            "tags": [s.strip() for s in a.tags.split(",") if s.strip()],
            "cols": COLS, "rows": ROWS,
            "art": rows(art),
            "shade": shade_rows,
            "part": rows(part),
            "plain": ["".join("1" if x else "0" for x in row) for row in plain],
        }
        (out / "key.json").write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
        Image.open(a.ref).convert("RGB").save(out / "source.jpg", quality=88)
        draw_frame(art, shade_rows, part, palette="duo", stream=a.stream or None,
                   plain=plain).save(out / "preview.png")
        print("wrote", out / "key.json", "and preview.png")
        return

    neck = neck_row(part)
    print("neck row:", neck)
    base = (art, ["".join(str(x) for x in row) for row in shade], part)

    if a.cmd == "render":
        for pal in ("mono", "duo"):
            draw_frame(*base, palette=pal, stream=a.stream or None, plain=plain).save(f"{a.out}.{pal}.png")
            print("wrote", f"{a.out}.{pal}.png")
        m = Image.open(f"{a.out}.mono.png")
        d = Image.open(f"{a.out}.duo.png")
        sheet = Image.new("RGB", (W * 2 + 8, H), (0, 0, 0))
        sheet.paste(m, (0, 0)); sheet.paste(d, (W + 8, 0))
        sheet.save(f"{a.out}.compare.png")
        return

    rng = random.Random(11)
    order = [[rng.random() for _ in range(COLS)] for _ in range(ROWS)]
    frames = []
    N = 48
    for i in range(N):
        t = i / (N - 1)
        ph = t * math.tau
        art2, sh2, pa2 = pose(*base, sway=2.2 * math.sin(ph), head=-3.0 * math.sin(ph + 0.7),
                              neck=neck, feet=ROWS)
        amt = 0.0
        if t > 0.62:
            amt = max(0.0, 1.0 - (t - 0.62) / 0.22) * 0.9
        if amt > 0:
            art2 = scramble(art2, amt, rng)
        art2, sh2, pa2 = materialise(art2, sh2, pa2, min(1.0, t / 0.42), rng, order)
        frames.append(draw_frame(art2, sh2, pa2, "duo", postfx=(i % 2 == 0), plain=plain).convert("P", palette=Image.ADAPTIVE, colors=64))
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=70, loop=0, optimize=True)
    print("wrote", a.out, len(frames), "frames")


if __name__ == "__main__":
    main()
