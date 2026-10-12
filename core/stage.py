"""舞台（stage）：分镜单 → 每帧从零重画的动态画面。

素材信号（assets.Signal）是「一张字符画 + 摇曳」；stage 不是——它是原片里那种
「屏幕上的信息在流动」：字一个一个打出来、数字在滚、曲线一段段长出来、粒子一直在飘、
进度条在推、素材从噪点里显影。每个零件都是 (t) → 当时的样子 的纯函数，
所以它会一直动下去，而不是在一张静态图上抖。

分镜单（plan）：{"title": "训练日志", "parts": [{"kind": "counter", ...}, ...]}
坐标一律是屏幕内的比例 0~1（x / y = 左上角）。零件种类见 tools.STAGE_KINDS。
"""
from __future__ import annotations

import hashlib
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from tuikit import space

from . import assets as assets_mod
from .config import Pen, font
from .tools import STAGE_KINDS

_DUR = {"counter": 4.0, "chart": 5.5, "progress": 5.5, "emerge": 1.8, "typewriter": 4.0,
        "bigtext": 3.2, "model3d": 8.0}
FADE = 0.55           # 开演淡入的秒数（scene 用它判断"是否已经盖满屏幕"）
_STYLES = ("star", "snow", "ash", "rain", "firefly")
_SHAPES = ("rise", "fall", "wave", "pulse", "steps")
_BIGSTYLES = ("cols", "rows", "diag")           # 大字揭示的填充顺序
_RAINSTYLES = ("matrix", "log")                 # 瀑布：字符坠落 / 日志滚动
_SIL_SHAPES = ("heart", "star", "moon", "cat", "whale", "tree")
_POSES = ("stand", "walk", "run", "sit", "dance", "wave", "jump")
_FOREVER = ("particles", "lograin", "figure")   # 会一直动下去的零件（busy 用）
_MASK_CACHE = {}


def _h32(s) -> int:
    return int(hashlib.md5(str(s).encode("utf8")).hexdigest()[:8], 16)


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _f(v, dflt, lo=-1e9, hi=1e9):
    try:
        return _clamp(float(v), lo, hi)
    except (TypeError, ValueError):
        return dflt


def _ease(u: float) -> float:
    """收尾减速：跑得快、停得稳。"""
    return 1.0 - (1.0 - _clamp(u, 0.0, 1.0)) ** 3


def _mixc(a, b, t):
    t = _clamp(t, 0.0, 1.0)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _font_for(s, size):
    return font(int(size), "cjk" if any(ord(c) > 127 for c in str(s)) else "mono")


def _num(v, fmt):
    f = str(fmt or "").strip()
    if f:
        try:
            return f.format(v)
        except (IndexError, KeyError, ValueError):
            pass
    a = abs(v)
    if a >= 1000:
        return "{:,.0f}".format(v)
    if a >= 100:
        return "{:.0f}".format(v)
    if a >= 10:
        return "{:.1f}".format(v)
    return "{:.2f}".format(v)


def _span(p: dict) -> float:
    """这个零件「演完」要多久（打字机按字数和速度推）。"""
    k = str(p.get("kind") or "")
    if k == "typewriter":
        return max(1.2, len(str(p.get("text") or "")) / _f(p.get("cps"), 9.0, 1.0, 80.0))
    span = _f(p.get("dur"), _DUR.get(k, 4.0), 0.4, 300.0)
    if k == "model3d":
        cam = p.get("camera")
        if isinstance(cam, list) and cam and isinstance(cam[-1], dict):
            span = max(span, _f(cam[-1].get("t"), span, 0.0, 300.0))
    return span


def _particles_table(style: str, n: int, seed: int) -> list:
    rng = random.Random(seed)
    return [{"x": rng.random(), "y": rng.random(), "ph": rng.random(),
             "sp": 0.7 + 0.7 * rng.random(), "sz": rng.choice((0, 1, 1, 2))}
            for _ in range(n)]


def _level(shape: str, u: float) -> float:
    if shape == "rise":
        return 0.12 + 0.84 * (u ** 0.7)
    if shape == "fall":
        return 0.96 - 0.84 * (u ** 0.7)
    if shape == "pulse":
        return 0.18 + 0.72 * abs(math.sin(u * 9.0 * math.pi)) * (0.35 + 0.65 * u)
    if shape == "steps":
        return 0.15 + 0.13 * int(u * 6.999)
    return 0.5 + 0.40 * math.sin(u * 3.1 * math.pi)


def _text_mask(text: str, cols: int, rows: int):
    """把一行字降采样成 cols×rows 的点阵蒙版（True=有笔画）。"""
    key = ("t", text, cols, rows)
    got = _MASK_CACHE.get(key)
    if got is not None:
        return got
    if len(_MASK_CACHE) > 128:
        _MASK_CACHE.clear()
    f = _font_for(text, 96)
    tmp = Image.new("L", (max(64, 96 * len(text)), 148), 0)
    ImageDraw.Draw(tmp).text((6, 6), text, font=f, fill=255)
    bb = tmp.getbbox()
    if bb:
        tmp = tmp.crop(bb)
    tw, th = tmp.size
    k = min(cols / tw, rows / th)
    mw, mh = max(1, int(tw * k)), max(1, int(th * k))
    small = tmp.resize((mw, mh), Image.LANCZOS).load()
    mask = [[False] * cols for _ in range(rows)]
    x0, y0 = (cols - mw) // 2, (rows - mh) // 2
    for yy in range(mh):
        for xx in range(mw):
            if small[xx, yy] > 55:
                mask[y0 + yy][x0 + xx] = True
    _MASK_CACHE[key] = mask
    return mask


def _p_bigtext(d, p, box, t, st):
    """大像素字揭示：巨字以点阵块一笔笔填出来，前沿发烫、填满后常亮微闪。"""
    ox, oy, pw, ph = box
    pen = st.pen
    text = str(p.get("text") or "WORLD")[:24]
    x = ox + int(_f(p.get("x"), 0.06) * pw)
    y = oy + int(_f(p.get("y"), 0.30) * ph)
    w = int(_f(p.get("w"), 0.88, 0.2, 1.0) * pw)
    h = int(_f(p.get("h"), 0.42, 0.08, 0.9) * ph)
    w = max(60, min(w, ox + pw - x - 8))
    h = max(36, min(h, oy + ph - y - 8))
    dur = _f(p.get("dur"), 3.2, 0.6, 60.0)
    style = str(p.get("style") or "cols").lower()
    if style not in _BIGSTYLES:
        style = "cols"
    cell = int(_f(p.get("size"), 10, 4, 28))
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    cols, rows = max(4, w // cell), max(3, h // cell)
    mask = _text_mask(text, cols, rows)
    key = _h32(text + style)
    r = _ease(max(0.0, t) / dur)
    band = 0.075
    for gy in range(rows):
        for gx in range(cols):
            if not mask[gy][gx]:
                continue
            if style == "rows":
                u = (gy * cols + gx) / max(1, cols * rows - 1)
            elif style == "diag":
                u = (gx / max(1, cols - 1) + gy / max(1, rows - 1)) * 0.5
            else:
                u = gx / max(1, cols - 1)
            u += ((gx * 7919 + gy * 104729 + key) % 97) / 97.0 * 0.05 - 0.025
            cx, cy = x + gx * cell, y + gy * cell
            if u > r:
                if u < r + 0.10 and (t % 0.5) < 0.5:
                    d.rectangle((cx, cy, cx + cell - 3, cy + cell - 3),
                                outline=_mixc(bg, dim, 0.55))
                else:
                    d.rectangle((cx, cy, cx + 1, cy + 1), fill=_mixc(bg, dim, 0.30))
                continue
            age = r - u
            if age < band:
                c = hot
            else:
                jit = 0.80 + 0.20 * (0.5 + 0.5 * math.sin(t * 2.4 + gx * 3 + gy * 5))
                c = _mixc(bg, ink, jit)
                if age < 0.20:
                    c = _mixc(c, hot, (1.0 - age / 0.20) * 0.55)
            d.rectangle((cx, cy, cx + cell - 3, cy + cell - 3), fill=c)


def _p_typewriter(d, p, box, t, st):
    """打字机：字一个一个出来，刚打出来的还是热的，末尾一块方光标在闪。"""
    ox, oy, pw, ph = box
    pen = st.pen
    size = int(_f(p.get("size"), 15, 10, 28))
    x = ox + int(_f(p.get("x"), 0.07) * pw)
    y = oy + int(_f(p.get("y"), 0.12) * ph)
    text = str(p.get("text") or "")
    cps = _f(p.get("cps"), 9.0, 1.0, 80.0)
    lh = int(size * 1.7)
    n = int(max(0.0, t) * cps)
    ink, hot = pen.color("ink"), pen.color("hot")
    cx, cy = x, y
    for i, ch in enumerate(text):
        if i >= n:
            break
        if ch == "\n":
            cx, cy = x, cy + lh
            continue
        f = _font_for(ch, size)
        d.text((cx, cy), ch, font=f, fill=hot if i >= n - max(2, int(cps * 0.18)) else ink)
        cx += int(d.textlength(ch, font=f))
    if p.get("cursor") is not False and (t % 0.9) < 0.58:
        if n < len(text) or t < _span(p) + 14.0:
            d.rectangle((cx + 2, cy + 3, cx + 3 + size // 2, cy + size + 3), fill=hot)


def _p_counter(d, p, box, t, st):
    """计数器：数字一格格往上滚，跑完停稳；label 是它的小标题。"""
    ox, oy, pw, ph = box
    pen = st.pen
    size = int(_f(p.get("size"), 34, 16, 64))
    x = ox + int(_f(p.get("x"), 0.07) * pw)
    y = oy + int(_f(p.get("y"), 0.12) * ph)
    dur = _f(p.get("dur"), 4.0, 0.6, 60.0)
    frm, to = _f(p.get("from"), 0.0), _f(p.get("to"), 100.0)
    if p.get("loop"):
        u = (max(0.0, t) % (dur + 1.3)) / dur
    else:
        u = max(0.0, t) / dur
    u = _clamp(u, 0.0, 1.0)
    s = _num(frm + (to - frm) * _ease(u), p.get("fmt"))
    label = str(p.get("label") or "")
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    ty = y
    if label:
        d.text((x, y), label, font=_font_for(label, 13), fill=dim)
        ty = y + 20
    f = font(size)
    tw = int(d.textlength(s, font=f))
    d.rectangle((x - 5, ty - 2, x + tw + 7, ty + size + 8), fill=_mixc(bg, ink, 0.10))
    d.text((x, ty), s, font=f, fill=hot)
    d.line((x - 5, ty + size + 8, x + tw + 7, ty + size + 8), fill=_mixc(bg, ink, 0.42))
    if u < 1.0:
        on = (t * 8) % 2 < 1
        d.rectangle((x + tw + 13, ty + 4, x + tw + 18, ty + size + 2),
                    fill=hot if on else dim)


def _p_chart(d, p, box, t, st):
    """成长曲线：一段段往前长，笔尖跟着走；长到头就停在那，尾巴还闪。"""
    ox, oy, pw, ph = box
    pen = st.pen
    w = int(_f(p.get("w"), 0.86, 0.2, 1.0) * pw)
    h = int(_f(p.get("h"), 0.26, 0.08, 0.95) * ph)
    x = ox + int(_f(p.get("x"), 0.07) * pw)
    y = oy + int(_f(p.get("y"), 0.42) * ph)
    x = int(_clamp(x, ox, max(ox, ox + pw - w)))
    y = int(_clamp(y, oy + 20, max(oy + 20, oy + ph - h)))
    w = max(60, min(w, ox + pw - x))
    h = max(40, min(h, oy + ph - y))
    dur = _f(p.get("dur"), 5.5, 0.8, 60.0)
    shape = str(p.get("shape") or "wave").lower()
    if shape not in _SHAPES:
        shape = "wave"
    label = str(p.get("label") or "")
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    top, bot = y + 8, y + h - 4
    n = 64
    rng = random.Random(_h32(label or shape))
    jit = [0.0] * n
    if shape != "steps":
        raw = [rng.uniform(-1.0, 1.0) for _ in range(n)]
        jit = [(raw[i - 1] + raw[i] + raw[(i + 1) % n]) / 3.0 for i in range(n)]
    lv = [_level(shape, i / (n - 1)) + 0.045 * jit[i] for i in range(n)]
    px = lambda i: x + int(i * w / (n - 1))
    py = lambda v: int(bot - _clamp(v, 0.03, 0.99) * (bot - top))
    d.rectangle((x - 6, top - 15, x + w + 6, bot + 4), outline=_mixc(bg, dim, 0.62))
    for k in (0.33, 0.66):
        yy = int(top + k * (bot - top))
        for xx in range(x, x + w - 8, 14):
            d.line((xx, yy, xx + 7, yy), fill=_mixc(bg, dim, 0.42))
    prog = _ease(max(0.0, t) / dur) * (n - 1)
    pts = [(px(i), py(lv[i])) for i in range(int(prog) + 1)]
    if len(pts) >= 2:
        d.line(pts, fill=ink)
        d.line(pts[-7:], fill=hot)
    if pts:
        tip = pts[-1]
        if prog < n - 1 or (t % 1.0) < 0.6:
            d.rectangle((tip[0] - 2, tip[1] - 4, tip[0] + 2, tip[1] + 4), fill=hot)
    if label:
        d.text((x - 4, top - 34), label, font=_font_for(label, 13), fill=dim)


def _p_progress(d, p, box, t, st):
    """进度条：小方块一格格填过去，右边跟着百分比。"""
    ox, oy, pw, ph = box
    pen = st.pen
    x = ox + int(_f(p.get("x"), 0.07) * pw)
    y = oy + int(_f(p.get("y"), 0.72) * ph)
    w = int(_f(p.get("w"), 0.6, 0.2, 1.0) * pw)
    dur = _f(p.get("dur"), 5.5, 0.8, 60.0)
    if p.get("loop"):
        u = (max(0.0, t) % (dur + 1.2)) / dur
    else:
        u = max(0.0, t) / dur
    u = _ease(_clamp(u, 0.0, 1.0))
    label = str(p.get("label") or "")
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    fy = y
    if label:
        d.text((x, y), label, font=_font_for(label, 13), fill=dim)
        fy = y + 21
    cells = max(8, min(44, w // 9))
    cw, ch = 8, 11
    filled = u * cells
    for i in range(cells):
        cx = x + i * cw
        if i + 1 <= filled:
            d.rectangle((cx, fy, cx + cw - 3, fy + ch), fill=ink)
        elif i < filled:
            d.rectangle((cx, fy, cx + max(1, int((cw - 3) * (filled - i))), fy + ch), fill=hot)
        else:
            d.rectangle((cx, fy, cx + cw - 3, fy + ch), outline=_mixc(bg, dim, 0.75))
    d.text((x + cells * cw + 8, fy - 2), "%3d%%" % int(u * 100), font=font(12), fill=hot)


def _p_particles(d, p, box, t, st):
    """粒子：星在闪、雪在落、灰在飘、雨在斜、萤火在游。铺满整块屏幕。"""
    ox, oy, pw, ph = box
    pen = st.pen
    style = str(p.get("style") or "star").lower()
    if style not in _STYLES:
        style = "star"
    n = int(_f(p.get("density"), 46, 6, 160))
    table = st.particles(style, n)
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    tt = max(0.0, t)
    for q in table:
        ph0 = q["ph"] * 6.283
        sp, sz = q["sp"], q["sz"]
        if style == "star":
            tw = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(tt * 1.6 + ph0 * 3.1))
            cx, cy = ox + int(q["x"] * pw), oy + int(q["y"] * ph)
            d.rectangle((cx, cy, cx + 1 + sz, cy + 1 + sz), fill=_mixc(bg, hot, tw))
        elif style in ("snow", "ash"):
            speed = 0.030 if style == "snow" else 0.016
            fy = (q["y"] + tt * speed * sp) % 1.0
            fx = (q["x"] + 0.012 * math.sin(tt * 0.8 + ph0)) % 1.0
            cx, cy = ox + int(fx * pw), oy + int(fy * ph)
            c = hot if style == "snow" else _mixc(bg, dim, 0.9)
            d.rectangle((cx, cy, cx + 1 + (sz > 1), cy + 1 + (sz > 1)), fill=c)
        elif style == "rain":
            fy = (q["y"] + tt * 0.80 * sp) % 1.0
            cx = ox + int(q["x"] * pw)
            cy = oy + int(fy * ph)
            d.line((cx, cy, cx - 2, cy + 8 + sz * 5), fill=_mixc(bg, ink, 0.85))
        else:
            fx = (q["x"] + 0.05 * math.sin(tt * 0.42 + ph0)) % 1.0
            fy = (q["y"] + 0.04 * math.sin(tt * 0.31 + ph0 * 1.7)) % 1.0
            gl = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(tt * 2.3 + ph0 * 4.1))
            cx, cy = ox + int(fx * pw), oy + int(fy * ph)
            d.rectangle((cx, cy, cx + 2 + sz, cy + 2 + sz), fill=_mixc(bg, hot, gl))


def _p_emerge(d, p, box, t, st):
    """显影：一张素材从噪点里慢慢长出来，长好之后轻轻动着。"""
    ox, oy, pw, ph = box
    pen = st.pen
    x = ox + int(_f(p.get("x"), 0.52) * pw)
    y = oy + int(_f(p.get("y"), 0.10) * ph)
    w = int(_f(p.get("w"), 0.42, 0.12, 1.0) * pw)
    h = int(_f(p.get("h"), 0.82, 0.12, 1.0) * ph)
    x = int(_clamp(x, ox, max(ox, ox + pw - 60)))
    y = int(_clamp(y, oy, max(oy, oy + ph - 60)))
    w = max(48, min(w, ox + pw - x))
    h = max(48, min(h, oy + ph - y))
    name = str(p.get("asset") or "")
    asset = assets_mod.find(name) if name else None
    if asset is None:
        d.rectangle((x, y, x + w, y + h), outline=pen.color("dim"))
        d.text((x + 10, y + 10), "? " + (name or "素材"),
               font=_font_for(name or "素材", 15), fill=pen.color("warn"))
        return
    sig = st.signal(asset, str(p.get("motion") or "sway"))
    sig.draw_onto(st.layer, (x, y, x + w, y + h), max(0.0, t))


_LOG_JUNK = "01ACYBERX#$%&@+*"
_LOG_FALLBACK = ("[executed] world.update(tick)",
                 "[ok] attention weights steady",
                 "[warn] loss spike ignored",
                 "[executed] she keeps running")


def _p_lograin(d, p, box, t, st):
    """日志瀑布：matrix 字符垂直坠落；log 日志一行行往下刷。铺满整块屏幕。"""
    ox, oy, pw, ph = box
    pen = st.pen
    style = str(p.get("style") or "matrix").lower()
    if style not in _RAINSTYLES:
        style = "matrix"
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    text = str(p.get("text") or "")
    speed = _f(p.get("speed"), 1.0, 0.1, 4.0)
    tt = max(0.0, t)
    if style == "log":
        lines = [q.strip() for q in text.split("\n") if q.strip()][:40] or list(_LOG_FALLBACK)
        lh, f = 20, _font_for("x", 13)
        interval = 1.15 / speed
        idx = int(tt / interval)
        local = tt - idx * interval
        prog = local / interval
        slide = (1.0 - min(1.0, prog / 0.25)) * lh if prog < 0.25 else 0.0
        y0 = oy + ph - 40
        for k in range(0, max(3, int((ph - 36) // lh))):
            j = idx - k
            if j < 0:
                break
            line = lines[j % len(lines)]
            yy = int(y0 - k * lh + slide)
            if yy < oy + 6:
                break
            if k == 0:
                shown = line[:max(1, int(prog * len(line)))] if prog < 1.0 else line
                c = hot
            else:
                shown = line
                c = _mixc(bg, ink, max(0.16, 0.75 - 0.11 * k))
            d.text((ox + 12, yy), "> " + shown, font=f, fill=c)
            if k == 0 and prog < 1.0 and (t % 0.6) < 0.4:
                wpx = int(d.textlength("> " + shown, font=f))
                d.rectangle((ox + 14 + wpx, yy + 2, ox + 18 + wpx, yy + 14), fill=hot)
        return
    cell = int(_f(p.get("size"), 12, 8, 20))
    cols = max(4, pw // (cell + 4))
    cw = max(1, pw // cols)
    trail = max(4, ph // cell // 3)
    charset = [c for c in (text or _LOG_JUNK) if c.strip()][:64] or list(_LOG_JUNK)
    f = _font_for("A", cell - 1)
    base0 = _h32(text or "#")
    for c in range(cols):
        rng = random.Random(base0 + 977 * c)
        off = rng.random() * ph
        sp = (46.0 + 96.0 * rng.random()) * speed
        x = ox + c * cw + 2
        head = (off + tt * sp) % (ph + trail * cell)
        for j in range(trail):
            yy = head - j * cell
            if yy < -cell or yy > ph + 2:
                continue
            ch = charset[(base0 + c * 31 + j * 17 + int(tt * 4.0)) % len(charset)]
            col = hot if j == 0 else _mixc(bg, ink, ((1.0 - j / trail) ** 1.7) * 0.92)
            d.text((x, oy + int(yy)), ch, font=f, fill=col)


def _sil_mask(shape: str, cols: int, rows: int):
    """内置剪影蒙版：在小画布上画出形状再降采样（True=实心）。"""
    key = ("s", shape, cols, rows)
    got = _MASK_CACHE.get(key)
    if got is not None:
        return got
    S = 4
    W, H = cols * S, rows * S
    im = Image.new("L", (W, H), 0)
    dd = ImageDraw.Draw(im)
    cx, cy = W / 2.0, H / 2.0
    if shape == "heart":
        pts = []
        for i in range(120):
            a = 2 * math.pi * i / 120
            px = 16 * math.sin(a) ** 3
            py = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
            pts.append((cx + px / 40.0 * W, cy - py / 40.0 * H))
        dd.polygon(pts, fill=255)
    elif shape == "star":
        pts, r0 = [], 0.5 * min(W, H)
        for i in range(10):
            a = -math.pi / 2 + math.pi * i / 5
            r = r0 if i % 2 == 0 else r0 * 0.42
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        dd.polygon(pts, fill=255)
    elif shape == "moon":
        r = min(W, H) * 0.46
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        dd.ellipse((cx - r + r * 0.58, cy - r * 1.05, cx + r * 1.7, cy + r * 1.05), fill=0)
    elif shape == "cat":
        r = min(W, H) * 0.34
        dd.ellipse((cx - r, cy - r * 0.55, cx + r, cy + r), fill=255)
        dd.polygon([(cx - r * 0.92, cy - r * 0.25), (cx - r * 0.62, cy - r * 1.3),
                    (cx - r * 0.12, cy - r * 0.55)], fill=255)
        dd.polygon([(cx + r * 0.12, cy - r * 0.55), (cx + r * 0.62, cy - r * 1.3),
                    (cx + r * 0.92, cy - r * 0.25)], fill=255)
    elif shape == "whale":
        bw, bh = W * 0.66, H * 0.40
        dd.ellipse((cx - bw * 0.5, cy - bh * 0.5, cx + bw * 0.5, cy + bh * 0.55), fill=255)
        dd.polygon([(cx - bw * 0.40, cy - bh * 0.02), (cx - bw * 0.82, cy - bh * 0.92),
                    (cx - bw * 0.66, cy + bh * 0.42)], fill=255)
        dd.polygon([(cx + bw * 0.02, cy - bh * 0.30), (cx + bw * 0.20, cy - bh * 0.85),
                    (cx + bw * 0.40, cy - bh * 0.22)], fill=255)
    else:  # tree
        dd.rectangle((cx - W * 0.045, cy + H * 0.02, cx + W * 0.045, cy + H * 0.48), fill=255)
        r = W * 0.20
        dd.ellipse((cx - r * 1.7, cy - r * 1.4, cx + r * 0.3, cy + r * 0.4), fill=255)
        dd.ellipse((cx - r * 0.3, cy - r * 1.9, cx + r * 1.7, cy - r * 0.1), fill=255)
        dd.ellipse((cx - r * 1.15, cy - r * 2.55, cx + r * 0.6, cy - r * 0.85), fill=255)
    px = im.resize((cols, rows), Image.BILINEAR).load()
    mask = [[px[gx, gy] > 90 for gx in range(cols)] for gy in range(rows)]
    _MASK_CACHE[key] = mask
    return mask


def _p_silhouette(d, p, box, t, st):
    """文字剪影：用流动的重复文字把一个形状填出来，整片表面一直在闪变。"""
    ox, oy, pw, ph = box
    pen = st.pen
    x = ox + int(_f(p.get("x"), 0.28) * pw)
    y = oy + int(_f(p.get("y"), 0.06) * ph)
    w = int(_f(p.get("w"), 0.44, 0.1, 1.0) * pw)
    h = int(_f(p.get("h"), 0.86, 0.1, 1.0) * ph)
    w = max(60, min(w, ox + pw - x - 6))
    h = max(60, min(h, oy + ph - y - 6))
    cell = int(_f(p.get("size"), 9, 5, 22))
    speed = _f(p.get("speed"), 5.0, 0.2, 40.0)
    ink, hot, bg = pen.color("ink"), pen.color("hot"), pen.color("bg")
    cols, rows = max(6, w // cell), max(6, h // cell)
    name = str(p.get("asset") or "").strip()
    asset = assets_mod.find(name) if name else None
    if asset is not None:
        mask = st.asset_mask(asset, cols, rows)
    else:
        shape = str(p.get("shape") or "heart").lower()
        if shape not in _SIL_SHAPES:
            shape = "heart"
        mask = _sil_mask(shape, cols, rows)
    chars = [c for c in str(p.get("text") or "world.execute(me);") if c != "\n"][:64] or list("world")
    f = _font_for("A", cell - 1)
    fl = max(0.0, t) * speed
    for gy in range(rows):
        for gx in range(cols):
            if not mask[gy][gx]:
                continue
            i = int(fl + gx + gy * 1.35) % len(chars)
            ph2 = 0.5 + 0.5 * math.sin((gx + gy * 1.35) * 0.55 - fl * 0.85)
            c = _mixc(_mixc(bg, ink, 0.55), hot, ph2 * 0.45)
            d.text((x + gx * cell, y + gy * cell), chars[i], font=f, fill=c)


def _figure_joints(pose: str, ph: float) -> dict:
    """算一具小人的关节：身高=1，脚底≈y1.0，面朝 +x（flip 时由画的人镜像）。"""
    s2 = math.sin(2 * math.pi * ph)
    pelvis = [0.0, 0.48]
    lean = 0.0
    hipL, hipR = 3.0, -3.0
    kneeL, kneeR = 5.0, 5.0
    shL, shR = 6.0, 6.0
    bndL, bndR = 9.0, 9.0
    chair = False
    if pose in ("walk", "run"):
        if pose == "walk":
            amp, k0, k1, sa, bend, lean = 24.0, 8.0, 34.0, 20.0, 18.0, 2.0
        else:
            amp, k0, k1, sa, bend, lean = 44.0, 24.0, 62.0, 38.0, 92.0, 9.0
        hipL, hipR = amp * s2, -amp * s2
        kneeL = k0 + k1 * max(0.0, math.sin(2 * math.pi * ph + 2.1))
        kneeR = k0 + k1 * max(0.0, math.sin(2 * math.pi * ph + 2.1 + math.pi))
        shL, shR = -sa * s2, sa * s2
        bndL = bndR = bend
        pelvis[1] += 0.012 * math.cos(4 * math.pi * ph)
    elif pose == "sit":
        pelvis = [0.0, 0.70]
        hipL = hipR = 86.0
        kneeL = kneeR = 84.0
        shL, shR = 40.0, 36.0
        bndL = bndR = 30.0
        chair = True
    elif pose == "dance":
        pelvis = [0.05 * s2, 0.48 + 0.02 * math.sin(4 * math.pi * ph)]
        hipL = 8.0 + 12.0 * s2
        hipR = 8.0 - 12.0 * s2
        kneeL = 14.0 + 16.0 * max(0.0, math.sin(2 * math.pi * ph + 1.6))
        kneeR = 14.0 + 16.0 * max(0.0, math.sin(2 * math.pi * ph + 1.6 + math.pi))
        shL = 118.0 + 44.0 * s2
        shR = 118.0 - 44.0 * s2
        bndL = 26.0 + 16.0 * math.sin(4 * math.pi * ph)
        bndR = 26.0 - 16.0 * math.sin(4 * math.pi * ph)
    elif pose == "wave":
        shR = 166.0
        bndR = 12.0 + 18.0 * math.sin(4 * math.pi * ph)
        shL, bndL = 7.0, 9.0
    elif pose == "jump":
        crouch = max(0.0, 1.0 - ph / 0.30) if ph < 0.30 else 0.0
        air = math.sin(math.pi * min(1.0, max(0.0, (ph - 0.25) / 0.75)))
        pelvis[1] += 0.085 * crouch - 0.16 * air
        kneeL = kneeR = 8.0 + 58.0 * crouch + 34.0 * air
        hipL = hipR = 30.0 * crouch
        shL = -24.0 * crouch + 148.0 * air
        shR = 24.0 * crouch + 148.0 * air
        bndL = bndR = 16.0
    dxn = math.sin(math.radians(lean)) * 0.245
    neck = [pelvis[0] + dxn, pelvis[1] - 0.245 + 0.004 * math.sin(2 * math.pi * ph * 0.5)]
    head = [neck[0] + dxn * 0.4, neck[1] - 0.085]

    def limb(a, ang, ln):
        r = math.radians(ang)
        return [a[0] + math.sin(r) * ln, a[1] + math.cos(r) * ln]

    sl = [neck[0] - 0.065, neck[1] + 0.012]
    sr = [neck[0] + 0.065, neck[1] + 0.012]
    el = limb(sl, shL, 0.155)
    hl = limb(el, shL + bndL, 0.145)
    er = limb(sr, shR, 0.155)
    hr = limb(er, shR + bndR, 0.145)
    pl = [pelvis[0] - 0.05, pelvis[1]]
    pr = [pelvis[0] + 0.05, pelvis[1]]
    kl = limb(pl, hipL, 0.26)
    fl2 = limb(kl, hipL - kneeL, 0.26)
    kr = limb(pr, hipR, 0.26)
    fr = limb(kr, hipR - kneeR, 0.26)
    return {"pelvis": pelvis, "neck": neck, "head": head, "chair": chair,
            "sl": sl, "sr": sr, "el": el, "hl": hl, "er": er, "hr": hr,
            "pl": pl, "kl": kl, "fl": fl2, "pr": pr, "kr": kr, "fr": fr}


def _p_figure(d, p, box, t, st):
    """人物零件：一个算出来的小人在做动作（走/跑/坐/舞/挥手/跳），全是点位不是贴图。"""
    ox, oy, pw, ph = box
    pen = st.pen
    pose = str(p.get("pose") or "stand").lower()
    if pose not in _POSES:
        pose = "stand"
    fx = ox + int(_f(p.get("x"), 0.5) * pw)
    fy = oy + int(_f(p.get("y"), 0.94) * ph)
    H = int(_f(p.get("h"), 0.52, 0.15, 0.95) * ph)
    speed = _f(p.get("speed"), 1.0, 0.1, 4.0)
    flip = -1.0 if p.get("flip") else 1.0
    ink, hot, dim, bg = pen.color("ink"), pen.color("hot"), pen.color("dim"), pen.color("bg")
    ph_ = (max(0.0, t) * speed * 0.6) % 1.0
    J = _figure_joints(pose, ph_)

    def sn2(v):
        return int(v) - int(v) % 2

    def seg(a, b, c, wdt=3, x2=0):
        d.line((sn2(fx + a[0] * H * flip) + x2, sn2(fy + (a[1] - 1.0) * H),
                sn2(fx + b[0] * H * flip) + x2, sn2(fy + (b[1] - 1.0) * H)),
               fill=c, width=wdt)

    if J["chair"]:
        px = int(fx)
        py = int(fy + (J["pelvis"][1] - 1.0) * H)
        hw = int(H * 0.085)
        d.line((px - hw, py, px + hw, py), fill=_mixc(bg, dim, 0.9), width=3)
        for sx in (-hw, hw):
            d.line((px + sx, py, px + sx, fy), fill=_mixc(bg, dim, 0.6), width=2)
    d.line((fx - int(H * 0.10), fy, fx + int(H * 0.10), fy), fill=_mixc(bg, dim, 0.55))
    limb = ink
    handc = _mixc(ink, hot, 0.35)
    footc = _mixc(ink, hot, 0.15)
    seg(J["sl"], J["el"], limb, 3, -2)
    seg(J["el"], J["hl"], handc, 3, -2)
    seg(J["sr"], J["er"], limb, 3, 2)
    seg(J["er"], J["hr"], handc, 3, 2)
    seg(J["pl"], J["kl"], limb, 3, -2)
    seg(J["kl"], J["fl"], footc, 3, -2)
    seg(J["pr"], J["kr"], limb, 3, 2)
    seg(J["kr"], J["fr"], footc, 3, 2)
    seg(J["pelvis"], J["neck"], _mixc(ink, hot, 0.14), 4)
    r = max(3, int(H * 0.05))
    hx = sn2(fx + J["head"][0] * H * flip)
    hy = sn2(fy + (J["head"][1] - 1.0) * H)
    headc = _mixc(ink, hot, 0.22)
    for oy2 in range(-r, r + 1, 3):
        for ox2 in range(-r, r + 1, 3):
            if ox2 * ox2 + oy2 * oy2 <= r * r + 1:
                d.rectangle((hx + ox2 - 1, hy + oy2 - 1, hx + ox2 + 1, hy + oy2 + 1),
                            fill=headc)


def _m3d_bbox(solids):
    xs, ys, zs = [], [], []
    for s in solids:
        pts = []
        lo, hi = s.get("lo"), s.get("hi")
        if isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple)) \
                and len(lo) == 3 and len(hi) == 3:
            pts = [lo, hi]
        elif isinstance(s.get("pts"), list):
            pts = [q for q in s["pts"] if isinstance(q, (list, tuple)) and len(q) == 3]
        for q in pts:
            try:
                xs.append(float(q[0])); ys.append(float(q[1])); zs.append(float(q[2]))
            except (TypeError, ValueError):
                pass
    if not xs:
        return None
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def _m3d_cam(t, keys):
    """把 JSON 相机关键帧换成 tuikit 的 Camera（没有就给 None，由调用方自动取景）。"""
    ks = []
    for k in (keys if isinstance(keys, list) else [])[:8]:
        if not isinstance(k, dict):
            continue
        pr = {"t": _f(k.get("t"), 0.0, 0.0, 300.0)}
        for name, lo, hi in (("yaw", -720.0, 720.0), ("pitch", -85.0, 85.0),
                             ("dist", 0.8, 400.0), ("fov", 10.0, 120.0)):
            v = _f(k.get(name), None, lo, hi)
            if v is not None:
                pr[name] = v
        tgt = k.get("target")
        if isinstance(tgt, (list, tuple)) and len(tgt) == 3:
            try:
                pr["target"] = tuple(float(x) for x in tgt)
            except (TypeError, ValueError):
                pass
        ks.append((pr.pop("t"), pr))
    if not ks:
        return None
    ks.sort(key=lambda x: x[0])
    return space.rig(max(0.0, t), ks)


def _m3d_roof(v, lo, hi, kind, rh, lv, style="dots", ramp="dots", shade=True):
    """屋顶：pyramid 四坡尖顶 / gable 双坡（屋脊沿较长的一边）。"""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    if kind == "pyramid":
        cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        verts = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (cx, y0 + rh, cz)]
        faces = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    elif (x1 - x0) >= (z1 - z0):
        czm = (z0 + z1) / 2.0
        verts = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1),
                 (x0, y0 + rh, czm), (x1, y0 + rh, czm)]
        faces = [(0, 1, 5, 4), (3, 2, 5, 4), (0, 4, 3), (1, 2, 5)]
    else:
        cxm = (x0 + x1) / 2.0
        verts = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1),
                 (cxm, y0 + rh, z0), (cxm, y0 + rh, z1)]
        faces = [(0, 1, 4, 5), (3, 2, 5, 4), (0, 4, 3), (1, 2, 5)]
    try:
        kw = {"tex": space.shade_tex(verts, faces, lv=lv, ramp=ramp)} if shade else {}
        v.solid(verts, faces, color="ink", lv=lv, edges=True, style=style, **kw)
    except Exception:
        pass


def _m3d_windows(v, o, lo, hi, lv):
    """给盒子按面点窗：亮点暖色（hot）、少量暗窗（ink）；坐标哈希保证静帧里不闪。"""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    w, h, d = x1 - x0, y1 - y0, z1 - z0
    if h < 3.0 or max(w, d) < 2.6:
        return
    pitch = 1.8
    faces = []
    if w >= 2.6:
        faces.append(("front", 2, (x0, x1), z1 + 0.06, (pitch, 0.0, 0.0)))
        faces.append(("back", 2, (x0, x1), z0 - 0.06, (pitch, 0.0, 0.0)))
    if d >= 2.6:
        faces.append(("left", 0, (z0, z1), x0 - 0.06, (0.0, 0.0, pitch)))
        faces.append(("right", 0, (z0, z1), x1 + 0.06, (0.0, 0.0, pitch)))
    for face, axis, (a0, a1), fixed, step in faces:
        span = abs(a1 - a0)
        n = max(1, int(span / pitch))
        us = [a0 + (i + 0.5) * span / n for i in range(min(n, 10))]
        ys0, ys1 = y0 + 1.1, y1 - 0.9
        if ys1 - ys0 < 1.0:
            continue
        m = max(1, min(int((ys1 - ys0) / pitch), 14))
        pts, txt, L, C = [], [], [], []
        for u in us:
            for j in range(m):
                yy = ys0 + (j + 0.5) * (ys1 - ys0) / m
                if axis == 2:
                    x, y, z = u, yy, fixed
                else:
                    x, y, z = fixed, yy, u
                hsh = (int(round(x * 3)) * 73856093
                       ^ int(round(y * 3)) * 19349663
                       ^ int(round(z * 3)) * 83492791) & 0x7FFFFFFF
                lit = (hsh % 100) < 38
                pts.append((x, y, z))
                txt.append("\u2022" if lit else "\u00b7")
                L.append(min(1.0, 0.15 + 0.95 * lv) if lit else 0.3 * lv)
                C.append("hot" if lit else "ink")
        if pts:
            v.glyphs(pts, txt, lv=L, color=C, owner=o, face=face, pitch=step)


def _p_model3d(d, p, box, t, st):
    """3D 场面：线框实体（建筑/屋顶/尖塔/折线）+ 关键帧相机，画进格子。"""
    ox, oy, pw, ph = box
    pen = st.pen
    solids = [s for s in (p.get("solids") or []) if isinstance(s, dict)][:40]
    style = str(p.get("line") or "auto").strip().lower()
    if style not in ("auto", "dots", "box", "bold"):
        style = "auto"
    ramp = "dots" if str(p.get("shade_ramp") or "").lower() == "dots" else "block"
    do_shade = p.get("shade") is not False
    do_win = p.get("windows") is not False
    weight = "bold" if str(p.get("weight") or "").lower() == "bold" else "dots"
    bb = _m3d_bbox(solids)
    cam = _m3d_cam(t, p.get("camera"))
    if cam is None:
        if bb is None:
            cam = space.orbit(target=(0.0, 3.0, 10.0), yaw=0.6, pitch=10.0, dist=30.0, fov=42.0)
        else:
            (x0, x1), (y0, y1), (z0, z1) = bb
            cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
            span = max(x1 - x0, z1 - z0, y1 - y0, 4.0)
            cam = space.orbit(target=(cx, y0 + (y1 - y0) * 0.45, cz),
                              yaw=0.6, pitch=12.0, dist=span * 2.1 + 8.0, fov=42.0)
    fog = p.get("fog")
    if not (isinstance(fog, (list, tuple)) and len(fog) == 3):
        try:
            d0 = math.dist(cam.pos, cam.target)
        except (AttributeError, TypeError, ValueError):
            d0 = 40.0
        fog = (max(8.0, d0 * 0.7), max(40.0, d0 * 2.2), 0.14)
    v = space.View(pen, (ox, oy, ox + pw, oy + ph), cam, cell=(8, 16), fog=tuple(fog),
                   weight=weight)
    if p.get("grid", True):
        if bb is None:
            gx0, gx1, gz0, gz1 = -20.0, 20.0, -10.0, 30.0
        else:
            (x0, x1), _, (z0, z1) = bb
            gx0, gx1 = x0 - 8.0, x1 + 8.0
            gz0, gz1 = min(z0 - 10.0, -6.0), z1 + 24.0
        space.floor_grid(v, gx0, gx1, gz0, gz1, step=2.0, lv=0.085)
    for s in solids:
        lv = _f(s.get("lv"), 0.8, 0.15, 1.0)
        kind = str(s.get("kind") or "box").lower()
        if kind == "poly":
            pts = []
            for q in (s.get("pts") or [])[:64]:
                if isinstance(q, (list, tuple)) and len(q) == 3:
                    try:
                        pts.append(tuple(float(c) for c in q))
                    except (TypeError, ValueError):
                        pass
            if len(pts) >= 2:
                v.polyline(pts, closed=bool(s.get("closed")), color="ink", lv=lv)
            continue
        lo, hi = s.get("lo"), s.get("hi")
        if not (isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple))
                and len(lo) == 3 and len(hi) == 3):
            continue
        try:
            lo = [float(c) for c in lo]
            hi = [float(c) for c in hi]
        except (TypeError, ValueError):
            continue
        lox, loy, loz = min(lo[0], hi[0]), min(lo[1], hi[1]), min(lo[2], hi[2])
        hix, hiy, hiz = max(lo[0], hi[0]), max(lo[1], hi[1]), max(lo[2], hi[2])
        hix, hiy, hiz = max(hix, lox + 0.05), max(hiy, loy + 0.05), max(hiz, loz + 0.05)
        use_shade = do_shade and (s.get("shade") is not False)
        kwb = {}
        if use_shade:
            kwb["tex"] = space.shade_box((lox, loy, loz), (hix, hiy, hiz), lv=lv, ramp=ramp)
        o = v.box((lox, loy, loz), (hix, hiy, hiz), color="ink", lv=lv, edges=True,
                  style=style, **kwb)
        if do_win and (s.get("windows") is not False):
            _m3d_windows(v, o, (lox, loy, loz), (hix, hiy, hiz), lv)
        roof = str(s.get("roof") or "").lower()
        if roof in ("gable", "pyramid"):
            rh = _f(s.get("roof_h"), 0.35 * max(hix - lox, hiz - loz), 0.2, 40.0)
            _m3d_roof(v, (lox, hiy, loz), (hix, hiy, hiz), roof, rh, lv,
                      style=style, ramp=ramp, shade=use_shade)
        if s.get("spire"):
            sw = max(0.25, min(hix - lox, hiz - loz) * 0.35)
            scx, scz = (lox + hix) / 2.0, (loz + hiz) / 2.0
            sh = max(1.6, (hiy - loy) * 0.35)
            v.box((scx - sw / 2, hiy, scz - sw / 2), (scx + sw / 2, hiy + sh, scz + sw / 2),
                  color="ink", lv=lv * 0.95, style=style)
            v.lines((scx, hiy + sh, scz), (scx, hiy + sh + 0.9, scz), lv=lv * 0.8)
    v.draw(st.layer)


_PARTS = {"typewriter": _p_typewriter, "counter": _p_counter, "chart": _p_chart,
          "progress": _p_progress, "particles": _p_particles, "emerge": _p_emerge,
          "bigtext": _p_bigtext, "lograin": _p_lograin, "silhouette": _p_silhouette,
          "figure": _p_figure, "model3d": _p_model3d}


def _auto_place(parts: list) -> list:
    """给没写坐标的零件排个位置：从上往下依次排，别叠在一起。"""
    out, y = [], 0.16
    for q in parts:
        p = dict(q)
        k = str(p.get("kind"))
        if k == "particles":
            p.setdefault("x", 0.0)
            p.setdefault("y", 0.0)
        elif k == "model3d":
            p.setdefault("x", 0.0)
            p.setdefault("y", 0.0)
            p.setdefault("w", 1.0)
            p.setdefault("h", 1.0)
        elif k == "lograin":
            p.setdefault("x", 0.0)
            p.setdefault("y", 0.0)
            p.setdefault("w", 1.0)
            p.setdefault("h", 1.0)
        elif k == "bigtext":
            p.setdefault("x", 0.06)
            p.setdefault("y", 0.28)
            p.setdefault("w", 0.88)
            p.setdefault("h", 0.44)
        elif k == "silhouette":
            p.setdefault("x", 0.30)
            p.setdefault("y", 0.05)
            p.setdefault("w", 0.40)
            p.setdefault("h", 0.88)
        elif k == "figure":
            p.setdefault("x", 0.5)
            p.setdefault("y", 0.94)
            p.setdefault("h", 0.52)
        elif k == "emerge":
            p.setdefault("x", 0.52)
            p.setdefault("y", 0.10)
            p.setdefault("w", 0.42)
            p.setdefault("h", 0.82)
        else:
            p.setdefault("x", 0.07)
            p.setdefault("y", round(y, 3))
            y += 0.19
        out.append(p)
    return out


def _screen(layer: Image.Image) -> Image.Image:
    """把画出来的这一层过成「屏幕」：发光 + 扫描线，和素材信号同一套质感。"""
    glow = layer.filter(ImageFilter.GaussianBlur(3.0))
    layer = ImageChops.add(layer, glow.point(lambda v: int(v * 0.30)))
    w, h = layer.size
    sl = Image.new("RGB", (w, h), (0, 0, 0))
    ds = ImageDraw.Draw(sl)
    for y in range(0, h, 3):
        ds.line((0, y, w, y), fill=(12, 12, 12))
    return ImageChops.subtract(layer, sl)


class Stage:
    """一份分镜单的实况渲染器：同一份 plan 每帧重画，t = 开演起的秒数。"""

    def __init__(self, plan: dict, pen: Pen):
        self.plan = plan if isinstance(plan, dict) else {}
        self.pen = pen
        self.bg = pen.color("bg")
        self.title = str(self.plan.get("title") or "")[:24]
        parts = [q for q in (self.plan.get("parts") or [])
                 if isinstance(q, dict) and q.get("kind") in STAGE_KINDS]
        self.parts = _auto_place(parts)
        self.scenes = []
        self.total = 0.0
        raw = self.plan.get("scenes")
        if isinstance(raw, list):
            acc = 0.0
            for sc in raw[:4]:
                if not isinstance(sc, dict):
                    continue
                ps = [q for q in (sc.get("parts") or [])
                      if isinstance(q, dict) and q.get("kind") in STAGE_KINDS]
                if not ps:
                    continue
                ps = _auto_place(ps)
                span = max(_span(q) for q in ps)
                dur = _f(sc.get("dur"), span, 0.8, 120.0)
                self.scenes.append({"t0": acc, "dur": dur,
                                    "title": str(sc.get("title") or self.title)[:24],
                                    "parts": ps})
                acc += dur
            self.total = acc
        self.layer = None
        self._ptab = {}
        self._sig = {}
        pool = list(self.parts)
        for sc in self.scenes:
            pool.extend(sc["parts"])
        self.has3d = any(str(q.get("kind")) == "model3d" for q in pool)

    def particles(self, style: str, n: int) -> list:
        got = self._ptab.get((style, n))
        if got is None:
            got = _particles_table(style, n, _h32(style) + 131 * n)
            self._ptab[(style, n)] = got
        return got

    def signal(self, asset, motion: str):
        got = self._sig.get((asset.id, motion))
        if got is None:
            got = assets_mod.Signal(asset, self.pen, motion)
            self._sig[(asset.id, motion)] = got
        return got

    def asset_mask(self, asset, cols: int, rows: int):
        """把素材的实心格采样成 cols×rows 布尔蒙版（文字剪影拿素材当模板时用）。"""
        key = ("a", asset.id, cols, rows)
        got = _MASK_CACHE.get(key)
        if got is not None:
            return got
        src = asset.part or asset.art or []
        sr = max(1, len(src))
        mask = [[False] * cols for _ in range(rows)]
        for gy in range(rows):
            row = src[min(sr - 1, gy * sr // rows)]
            for gx in range(cols):
                x = min(max(0, asset.cols - 1), gx * asset.cols // cols)
                mask[gy][gx] = x < len(row) and row[x] != " "
        if len(_MASK_CACHE) > 128:
            _MASK_CACHE.clear()
        _MASK_CACHE[key] = mask
        return mask

    def busy(self, t: float) -> bool:
        """还需要继续刷新吗？（粒子/人物一直在动；打字机收尾后光标还闪一会儿）"""
        pool = self.parts
        if self.scenes:
            pool = [q for sc in self.scenes for q in sc["parts"]]
        for q in pool:
            k = str(q.get("kind"))
            if k in _FOREVER or (k == "counter" and q.get("loop")):
                return True
            if k == "emerge":
                if t < _span(q) + 5.0:
                    return True
                continue
            if t < _span(q) + (14.0 if k == "typewriter" else 0.8):
                return True
        if self.scenes and t < self.total + 0.8:
            return True
        return False

    def _live(self, t: float):
        """此刻该画哪组零件：没有 scenes 就是原来的 parts；有就按幕硬切。"""
        if not self.scenes:
            return self.parts, self.title, t, None
        tt = max(0.0, t)
        for i, sc in enumerate(self.scenes):
            if tt < sc["t0"] + sc["dur"]:
                lt = tt - sc["t0"]
                return sc["parts"], sc["title"], lt, (lt if i else None)
        last = self.scenes[-1]
        return last["parts"], last["title"], last["dur"], None

    def draw(self, img, rect, t: float):
        x0, y0, x1, y1 = rect
        w, h = max(8, x1 - x0), max(8, y1 - y0)
        parts, title, lt, cut = self._live(t)
        layer = Image.new("RGB", (w, h), self.bg)
        d = ImageDraw.Draw(layer)
        if not self.has3d:
            self._ground(d, w, h)
        if title:
            self._title(d, w, lt, title)
        self.layer = layer
        for q in parts:
            fn = _PARTS.get(str(q.get("kind")))
            if fn is None:
                continue
            try:
                fn(d, q, (0, 0, w, h), lt, self)
            except Exception:
                continue
        self.layer = None
        layer = _screen(layer)
        if cut is not None and cut < 0.20:
            layer = Image.blend(layer, Image.new("RGB", (w, h), self.pen.color("hot")),
                                0.26 * (1.0 - cut / 0.20))
        alpha = _clamp(t / FADE, 0.0, 1.0)
        region = img.crop(rect)
        img.paste(Image.blend(region, layer, alpha), (x0, y0))
        ImageDraw.Draw(img).rectangle((x0 - 1, y0 - 1, x1, y1),
                                      outline=self.pen.color("dim"))
        return rect

    def _ground(self, d, w, h):
        faint = _mixc(self.bg, self.pen.color("dim"), 0.18)
        for gx in range(0, w, 44):
            d.line((gx, 0, gx, h), fill=faint)
        for gy in range(0, h, 44):
            d.line((0, gy, w, gy), fill=faint)
        c = self.pen.color("dim")
        for cx, cy, sx, sy in ((10, 10, 1, 1), (w - 10, 10, -1, 1),
                               (10, h - 10, 1, -1), (w - 10, h - 10, -1, -1)):
            d.line((cx, cy, cx + 18 * sx, cy), fill=c)
            d.line((cx, cy, cx, cy + 18 * sy), fill=c)

    def _title(self, d, w, t, title=None):
        pen = self.pen
        hot, dim = pen.color("hot"), pen.color("dim")
        text = title or self.title
        on = (t % 1.2) < 0.72
        d.rectangle((18, 16, 26, 30), fill=hot if on else _mixc(self.bg, dim, 0.8))
        d.text((36, 14), text, font=_font_for(text, 15), fill=hot)
        d.line((18, 40, w - 18, 40), fill=_mixc(self.bg, dim, 0.7))


def busy(plan, t: float) -> bool:
    """这份分镜在 t 时刻还需要继续刷新吗（给动画循环用）。"""
    try:
        return Stage(plan, Pen("amber")).busy(t)
    except Exception:
        return False
