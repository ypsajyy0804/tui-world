"""素材：参考图 → 字符关键帧（assets/<id>/key.json）→ 上屏。

一个素材是三层字符网格（art / shade / part，默认 96×64 格），由 tools/trace.py
离线从参考图里描出来——它带的是真实图像信息（轮廓、明暗、内部结构），不是生成物。
这里负责按当前世界的调色板重新上色，加上浮现／摇曳／闪动，然后贴进画面。
"""
from __future__ import annotations

import json
import math
import random
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .config import ROOT, Pen, font

ASSETS = ROOT / "assets"
CELL = (5, 10)          # 一个字符格占 5×10 px（和参考实现一致，1:2）

# 素材自带色板：色相是内容的一部分（皮肤 / 衣服 / 环境要分得开），
# 只往当前世界的墨色上偏一点，免得跟窗框打架。
_SIGNAL_RAMPS = {
    "d": ((12, 18, 34), (54, 82, 142), (178, 208, 248)),
    "s": ((38, 24, 26), (146, 100, 96), (228, 192, 180)),
    "g": ((26, 36, 14), (124, 172, 50), (212, 240, 132)),
    "b": ((10, 28, 52), (46, 122, 212), (156, 212, 255)),
    "l": ((28, 44, 80), (128, 170, 228), (236, 246, 255)),
}
_TINT = 0.12

_CYCLE = 3.6          # 摇曳一轮的秒数
_STEPS = 12           # 预烘焙帧数（12 帧摊一轮）
_GLITCH = 0.28        # 每轮开头这一小段是"闪"
_MATERIALISE = 1.25   # 开场逐格浮现的时长
_BAKED: dict = {}     # (素材, 调色板) -> 预烘焙帧
_MASKS: dict = {}     # (字体, 字) -> L 蒙版：逐格 paste 比每帧 d.text 快一个量级


def _glyph_mask(fnt, ch: str):
    """把一个字预先渲染成一张 L 蒙版（和 d.text 同原点，贴出来像素一致）。"""
    key = (getattr(fnt, "path", ""), getattr(fnt, "size", 0), ch)
    m = _MASKS.get(key)
    if m is None:
        try:
            asc, desc = fnt.getmetrics()
        except Exception:
            return None
        size = getattr(fnt, "size", 12) or 12
        m = Image.new("L", (int(size * 1.9) + 4, asc + desc + 2), 0)
        ImageDraw.Draw(m).text((0, 0), ch, font=fnt, fill=255)
        _MASKS[key] = m
    return m

# 动作模板：同一张素材可以换不同的“上台方式”；模板本身不含素材信息，
# 实现全在 Signal 里，呼叫方只管传动作名。
MOTIONS = ("sway", "breathe", "emerge", "glitch", "rain", "push", "text")
_MOTION_ALIAS = {
    "摇曳": "sway", "摆动": "sway",
    "呼吸": "breathe", "静谧": "breathe", "静止": "breathe",
    "浮现": "emerge", "入场": "emerge", "慢慢出现": "emerge",
    "故障": "glitch", "闪烁": "glitch",
    "雨": "rain", "下雨": "rain", "雨幕": "rain",
    "推": "push", "推近": "push", "推镜": "push", "靠近": "push",
    "文字剪影": "text", "剪影": "text", "文字": "text", "文字流": "text",
    "流光": "text", "流字": "text", "字流": "text",
}

# 文字剪影（text）：剪影内部不画描出来的点线，改填一段一直在流动的字，整片表面持续闪变——
# 原型 PV 里那条「文字鲸鱼」的做法（见 docs/VIDEO_ANIMATION_STUDY.md）。
_DEFAULT_STREAM = "world.execute(me);"
_STREAM_MAX = 64        # 流动文字最长几个字
_STREAM_SPEED = 16.0    # 每秒流过几格（越大越急）


def clean_stream(text) -> str:
    """把模型给的一句话收拾成能在剪影里流动的一段字（去空白、限长、空则回默认）。"""
    s = "".join(ch for ch in str(text or "") if not ch.isspace())[:_STREAM_MAX]
    return s or _DEFAULT_STREAM


def norm_motion(name) -> str:
    """把模型给的动作名收拾成 MOTIONS 里的一个；不认识就回默认 sway。"""
    raw = str(name or "").strip()
    if raw in MOTIONS:
        return raw
    low = raw.lower()
    if low in MOTIONS:
        return low
    return _MOTION_ALIAS.get(raw) or _MOTION_ALIAS.get(low) or "sway"


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Asset:
    def __init__(self, data: dict):
        self.id = str(data.get("id") or "?")
        self.name = str(data.get("name") or self.id)
        self.aliases = [str(x).lower() for x in (data.get("aliases") or [])]
        self.tags = [str(x) for x in (data.get("tags") or [])]
        self.cols = int(data.get("cols") or 96)
        self.rows = int(data.get("rows") or 64)
        self.art = [str(x) for x in (data.get("art") or [])]
        self.shade = [str(x) for x in (data.get("shade") or [])]
        self.part = [str(x) for x in (data.get("part") or [])]
        self.plain = [str(x) for x in (data.get("plain") or [])]
        self.src_fp = str(data.get("src_fp") or "")   # 来源指纹（取材用，防重复描同一张）
        self._order = None

    @property
    def size(self):
        return (self.cols * CELL[0], self.rows * CELL[1])

    def order(self):
        """浮现顺序：每格一个 [0,1)，确定性的（同一张素材每次一样）。"""
        if self._order is None:
            rng = random.Random(sum(self.id.encode("utf8")) * 7919)
            self._order = [[rng.random() for _ in range(self.cols)] for _ in range(self.rows)]
        return self._order

    def neck_row(self):
        """最窄的一行 = 脖子：摇曳时上下摆幅的分界。"""
        best, row = 1 << 30, self.rows // 3
        for r in range(self.rows // 6, self.rows * 3 // 5):
            n = sum(1 for c in self.part[r] if c != " ")
            if n < best:
                best, row = n, r
        return row


_assets: dict = {}
_loaded = False
_lock = threading.RLock()


def load_all() -> dict:
    global _loaded
    with _lock:
        if _loaded:
            return _assets
        _loaded = True
        if ASSETS.exists():
            for d in sorted(ASSETS.iterdir()):
                f = d / "key.json"
                if not f.exists():
                    continue
                try:
                    a = Asset(json.loads(f.read_text(encoding="utf8")))
                    _assets[a.id] = a
                except Exception as e:
                    print("素材载入失败 %s：%s" % (f, e))
    return _assets


def reload() -> dict:
    """工作台入库后调用：清空重扫，让新素材立刻可用。"""
    global _loaded
    with _lock:
        _assets.clear()
        _loaded = False
    return load_all()


def find(name) -> Asset | None:
    """按 id / 中文名 / 别名找素材（大小写与包含都算）。"""
    key = str(name or "").strip().lower().replace(" ", "_")
    if not key:
        return None
    items = list(load_all().values())
    for a in items:
        if key == a.id.lower():
            return a
    for a in items:
        for w in [a.id.lower(), a.name.lower()] + a.aliases:
            if w and (key in w or w in key):
                return a
    return None


def catalogue() -> list:
    """给提示词用的素材清单：[{id, name, aliases, tags}]。"""
    return [{"id": a.id, "name": a.name, "aliases": a.aliases, "tags": a.tags}
            for a in load_all().values()]


def search(query: str, limit: int = 5) -> list:
    """按一句话找相关素材：名称/别名/标签的子串与二元组匹配，按分返回前 limit 个。"""
    q = str(query or "").lower()
    if not q:
        return []
    scored = []
    for a in load_all().values():
        score, seen = 0, set()
        pairs = ([(a.id, 2), (a.name, 3)]
                 + [(x, 3) for x in a.aliases] + [(t, 2) for t in a.tags])
        for w, wt in pairs:
            wl = str(w).lower()
            if not wl or wl in seen:
                continue
            seen.add(wl)
            if wl in q:
                score += wt + min(len(wl), 6)
            elif len(wl) >= 2 and any(wl[i:i + 2] in q for i in range(len(wl) - 1)):
                score += wt
        if score > 0:
            scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [{"id": a.id, "name": a.name, "aliases": a.aliases, "tags": a.tags}
            for _, a in scored[:limit]]


def _shift_rows(rows, offs):
    """按行位移（摇曳用）：offs 每行一个整数像素/格数。"""
    out = []
    n = len(rows[0]) if rows else 0
    for s, k in zip(rows, offs):
        if k > 0:
            out.append(" " * min(k, n) + s[:max(0, n - k)])
        elif k < 0:
            kk = min(-k, n)
            out.append(s[kk:] + " " * kk)
        else:
            out.append(s)
    return out


class Signal:
    """素材上屏：浮现 → 轻微摇曳 → 偶尔闪一下。t = 接入起的秒数。

    motion="text" 是「文字剪影」：剪影内部填一段流动的字（text），整片表面持续闪变。
    """

    _MAT = {"emerge": 1.6, "push": 1.05, "text": 1.4}

    def __init__(self, asset: Asset, pen: Pen, motion: str = "sway", text=None):
        self.a = asset
        self.pen = pen
        self.motion = norm_motion(motion)
        self.stream = clean_stream(text)
        # 等宽字体没有中文字形；流动的文字按内容选字体（中文隔一列填一个，不然糊成一团）
        ascii_only = all(ord(ch) < 128 for ch in self.stream)
        self.sfnt = font(9 if ascii_only else 10, "mono" if ascii_only else "cjk")
        self.sstep = 1 if ascii_only else 2   # 中文一格写不下，隔一列填一个才认得出
        self.mat = self._MAT.get(self.motion, _MATERIALISE)
        self.bg = pen.color("bg")
        self.fnt = font(9)
        self.neck = asset.neck_row()
        ink = pen.color("ink")
        self.ramps = {}
        for letter, (lo, mid, hi) in _SIGNAL_RAMPS.items():
            self.ramps[letter] = (_mix(lo, self.bg, 0.30), _mix(mid, ink, _TINT),
                                  _mix(hi, ink, _TINT * 0.5))

    def color(self, letter, level):
        lo, mid, hi = self.ramps.get(letter) or self.ramps["b"]
        return _mix(lo, mid, level / 0.55) if level < 0.55 else _mix(mid, hi, (level - 0.55) / 0.45)

    def frame(self, t: float) -> Image.Image:
        """取一帧。稳态帧是预烘焙的，只有开场（浮现/推近）和文字剪影实时算。"""
        if self.motion == "text":
            return self._render(t, reveal=min(1.0, t / self.mat))
        if t >= self.mat:
            if self.motion == "glitch":
                cyc = t % 1.15
                if cyc < 0.48:
                    return self._baked()[-1]
                return self._baked()[int((cyc - 0.48) / 0.67 * _STEPS) % _STEPS]
            cyc = t % _CYCLE
            if cyc < _GLITCH:
                return self._baked()[-1]
            return self._baked()[int(cyc / _CYCLE * _STEPS) % _STEPS]
        if self.motion == "push":
            return self._push(t)
        return self._render(t, reveal=min(1.0, t / self.mat))

    def _baked(self) -> list:
        key = (self.a.id, self.pen.palette, self.motion)
        got = _BAKED.get(key)
        if got is None:
            got = [self._render(k * _CYCLE / _STEPS) for k in range(_STEPS)]
            got.append(self._render(0.06, force_glitch=True))
            _BAKED[key] = got
        return got

    def _render(self, t: float, force_glitch: bool = False, reveal: float = 1.0) -> Image.Image:
        a, cw, ch = self.a, CELL[0], CELL[1]
        img = Image.new("RGB", a.size, self.bg)
        d = ImageDraw.Draw(img)

        if self.motion == "text":
            sway = head = 0.0          # 剪影本身不晃，动的是里面的字
        elif self.motion == "breathe":
            sway = 0.5 * math.sin(t * 1.1)
            head = -0.8 * math.sin(t * 1.1 + 0.7)
        else:
            sway = 1.7 * math.sin(t * 1.5)
            head = -2.4 * math.sin(t * 1.5 + 0.7)
        offs = []
        for r in range(a.rows):
            if r < self.neck:
                offs.append(int(round(head * (1.0 - r / max(1, self.neck)))))
            else:
                u = (r - self.neck) / max(1, a.rows - self.neck)
                offs.append(int(round(sway * math.sin(math.pi * u))))
        art = _shift_rows(a.art, offs)

        cyc = t % _CYCLE
        glitch = 1.0 - cyc / _GLITCH if cyc < _GLITCH else 0.0
        if force_glitch:
            glitch = 1.0
        if self.motion == "push":
            glitch = 0.0
        hit = 0.30 if self.motion == "glitch" else 0.06
        rng = random.Random(int(t * 24) * 7919 + 13)
        order = a.order()
        if self.motion in ("emerge", "text"):
            order = [[r / max(1, a.rows - 1) * 0.86 + v * 0.14 for v in row]
                     for r, row in enumerate(order)]

        is_text = self.motion == "text"
        stream, nstream = self.stream, len(self.stream)
        # 字流整体按时间连续左移（亚格位移），11fps 下也不会一跳一跳
        off = max(0.0, t) * _STREAM_SPEED
        fill_i, shoft = int(off), (off - int(off)) * cw
        n_fill = 0
        drawn = []          # 先铺底、再统一写字：否则后一格的底会盖掉前一格溢出的字
        for r in range(a.rows):
            row, sh, pt = art[r], a.shade[r], a.part[r]
            pl = a.plain[r] if r < len(a.plain) else ""
            for c in range(a.cols):
                glyph = row[c]
                if glyph == " " or order[r][c] > reveal:
                    continue
                lv = ((ord(sh[c]) - 48) / 7.0) if sh[c].isdigit() else 0.0
                p = pt[c] if pt[c] in self.ramps else "b"
                x, y = c * cw, r * ch
                # 文字剪影时把底压暗、字提亮，否则亮面上字色和底色撞在一起读不出来
                base = 0.22 + 0.30 * lv if is_text else 0.16 + 0.60 * lv
                d.rectangle((x, y, x + cw - 2, y + ch - 2), fill=self.color(p, base))
                if glyph == ":":
                    # 内部格：文字剪影时填流动的字；大片平色区（脸等）留白不写
                    if not is_text or c >= len(pl) or pl[c] == "1":
                        continue
                    if self.sstep > 1 and c % self.sstep:
                        continue
                    glyph = stream[(n_fill + fill_i) % nstream]
                    n_fill += 1
                    drawn.append((x - shoft, y, glyph, self.sfnt,
                                  self.color(p, 0.62 + 0.36 * lv)))
                    continue
                if glitch > 0 and rng.random() < hit * glitch:
                    glyph = rng.choice("#*+=%")
                drawn.append((x, y, glyph, self.fnt, self.color(p, 0.55 + 0.45 * lv)))
        for x, y, glyph, fnt, col in drawn:
            x, y = int(round(x)), int(y) - 1
            m = _glyph_mask(fnt, glyph)
            if m is None:
                d.text((x, y), glyph, font=fnt, fill=col)
            else:
                img.paste(col, (x, y), m)

        # 字流本来就细，光晕收小一点，免得把小字糊成噪点
        blur, gain = (2.2, 0.20) if is_text else (3.5, 0.30)
        glow = img.filter(ImageFilter.GaussianBlur(blur))
        img = ImageChops.add(img, glow.point(lambda v: int(v * gain)))
        sl = Image.new("RGB", a.size, (0, 0, 0))
        ds = ImageDraw.Draw(sl)
        for y in range(0, a.size[1], 3):
            ds.line([0, y, a.size[0], y], fill=(10, 10, 10))
        img = ImageChops.subtract(img, sl)
        vig = Image.new("L", (a.cols, a.rows), 0)
        pv = vig.load()
        for r in range(a.rows):
            for c in range(a.cols):
                dx = (c - a.cols / 2) / (a.cols / 2)
                dy = (r - a.rows / 2) / (a.rows / 2)
                v = min(1.0, max(0.0, (dx * dx + dy * dy) - 0.40) * 0.62)
                pv[c, r] = int(255 * v)
        img = Image.composite(img, Image.new("RGB", a.size, self.bg),
                              ImageChops.invert(vig.resize(a.size, Image.BILINEAR)))
        if self.motion == "breathe":
            img = ImageEnhance.Brightness(img).enhance(1.0 + 0.08 * math.sin(t * 1.9))
        elif self.motion == "rain":
            self._rain(img, t)
        return img

    def _rain(self, img: Image.Image, t: float):
        """雨幕：每列一条确定性地往下走的亮线 + 一条暗线，像素级，不占字符格。"""
        d = ImageDraw.Draw(img)
        w, h = img.size
        for x in range(4, w, 11):
            seed = (x * 2654435761) & 0xFFFF
            speed = 150 + seed % 110
            y = int((t * speed + seed % 997) % (h + 80)) - 80
            for k in range(4):
                yy = y + k * 13
                if -6 <= yy < h:
                    d.line([x, yy, x, yy + 7], fill=(96, 128, 172))
                    d.line([x, yy - 6, x, yy - 1], fill=(8, 12, 20))
        return img

    def _push(self, t: float) -> Image.Image:
        """推近：开场 1.05 秒从 1.18 倍缓缓收到 1.0，稳态照常用 sway 烘焙帧。"""
        u = min(1.0, max(0.0, t / self.mat))
        k = 1.18 - 0.18 * (1.0 - (1.0 - u) ** 3)
        img = self._render(t)
        w, h = self.a.size
        rw, rh = int(w * k), int(h * k)
        img = img.resize((rw, rh), Image.LANCZOS)
        cx, cy = w // 2, int(h * 0.42)
        x0 = max(0, min(rw - w, cx - w // 2))
        y0 = max(0, min(rh - h, cy - h // 2))
        return img.crop((x0, y0, x0 + w, y0 + h))

    def draw_onto(self, img: Image.Image, rect, t: float):
        """把信号铺进 rect：cover 放大 + 往上偏一点截（脸一般在上半），后景压暗。"""
        x0, y0, x1, y1 = rect
        sig = self.frame(t)
        rw, rh = x1 - x0, y1 - y0
        # 缩放取折中：比"塞得下"最多放大 1.5 倍，但绝不超出画布宽度——
        # 太远看不出人，太近只剩一张脸。
        sc = min(rw / sig.width, rh / sig.height * 1.5)
        w, h = max(32, int(sig.width * sc)), max(32, int(sig.height * sc))
        sig = sig.resize((w, h), Image.LANCZOS)
        region = img.crop(rect)
        img.paste(Image.blend(region, Image.new("RGB", region.size, self.bg), 0.75), (x0, y0))
        cx = max(0, (w - rw) // 2)
        cy = max(0, int((h - rh) * 0.38))
        view = sig.crop((cx, cy, cx + min(w, rw), cy + min(h, rh)))
        px = x0 + max(0, (rw - w) // 2)
        py = y0 + max(0, (rh - h) // 2)
        img.paste(view, (px, py))
        ImageDraw.Draw(img).rectangle((px - 1, py - 1, px + view.width, py + view.height),
                                      outline=self.pen.color("dim"))
        return rect
