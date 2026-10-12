r"""素材工作台后端：本地图库 → 参考图 → 候选 → 微调 → 入库。

三个来源：
- 漫画库   D:\VM_share\manga\<系列>\<章节>.cbz 的每一页（可用 WB_MANGA_DIR 改）
- Pixiv    D:\图片\pixiv                            （可用 WB_PIXIV_DIR 改）
- 上传

界在 core/web/workbench.html；本模块只做后端：列源、取图、描候选、入库、AI 建议。
入库后调用 on_saved 回调，让正在跑的会话把新素材告诉导演（重建提示词里的素材库）。
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .config import ROOT, load_env

_spec = importlib.util.spec_from_file_location("tracer", ROOT / "tools" / "trace.py")
tracer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tracer)

_cfg = load_env()
MANGA_DIR = Path(os.environ.get("WB_MANGA_DIR") or _cfg.get("WB_MANGA_DIR")
                 or r"D:\VM_share\manga")
PIXIV_DIR = Path(os.environ.get("WB_PIXIV_DIR") or _cfg.get("WB_PIXIV_DIR")
                 or r"D:\图片\pixiv")
CACHE = ROOT / ".tmp" / "wb"
UPLOADS = CACHE / "uploads"
ASSETS = ROOT / "assets"

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
LOCK = threading.Lock()            # tracer 用模块级全局量，描图必须串行
_page_cache: dict = {}
_thumb_cache: dict = {}


def _nat(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _safe(child: str, parent: Path) -> Path:
    """只允许 parent 下的直接子项（按名字精确匹配列表里的项）。"""
    for p in parent.iterdir():
        if p.name == child:
            return p
    raise FileNotFoundError(child)


def list_manga() -> list:
    if not MANGA_DIR.exists():
        return []
    return sorted([d.name for d in MANGA_DIR.iterdir()
                   if d.is_dir() and any(d.glob("*.cbz"))], key=_nat)


def list_chapters(series: str) -> list:
    d = _safe(series, MANGA_DIR)
    return sorted([f.name for f in d.glob("*.cbz")], key=_nat)


def chapter_pages(series: str, chapter: str) -> list:
    key = (series, chapter)
    got = _page_cache.get(key)
    if got is None:
        with zipfile.ZipFile(_safe(chapter, _safe(series, MANGA_DIR))) as z:
            got = sorted([n for n in z.namelist() if n.lower().endswith(IMG_EXT)], key=_nat)
        _page_cache[key] = got
    return got


def page_image(series: str, chapter: str, page: int) -> Image.Image:
    names = chapter_pages(series, chapter)
    if not 0 <= page < len(names):
        raise IndexError(page)
    cache_f = CACHE / "pages" / hashlib.md5(
        ("%s|%s|%d" % (series, chapter, page)).encode("utf8")).hexdigest()
    if not cache_f.with_suffix(".jpg").exists():
        with zipfile.ZipFile(_safe(chapter, _safe(series, MANGA_DIR))) as z:
            data = z.read(names[page])
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        Image.open(io.BytesIO(data)).convert("RGB").save(cache_f.with_suffix(".jpg"),
                                                         quality=90)
    return Image.open(cache_f.with_suffix(".jpg")).convert("RGB")


def list_pixiv() -> list:
    if not PIXIV_DIR.exists():
        return []
    return sorted([f.name for f in PIXIV_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in IMG_EXT], key=_nat)


def pixiv_image(name: str) -> Image.Image:
    return Image.open(_safe(name, PIXIV_DIR)).convert("RGB")


def load_src(src: dict) -> Image.Image:
    kind = (src or {}).get("kind")
    if kind == "manga":
        return page_image(src["series"], src["chapter"], int(src.get("page", 0)))
    if kind == "pixiv":
        return pixiv_image(src["name"])
    if kind == "upload":
        p = Path(src.get("path") or "")
        if not str(p.resolve()).startswith(str(UPLOADS.resolve())):
            raise PermissionError("上传路径不在工作台缓存里")
        return Image.open(p).convert("RGB")
    if kind == "asset":
        return Image.open(_safe(src["id"], ASSETS) / "source.jpg").convert("RGB")
    raise ValueError("未知来源：%r" % kind)


def jpeg_bytes(img: Image.Image, w: int | None = None, quality: int = 82) -> bytes:
    im = img
    if w and im.width > w:
        im = im.resize((w, max(1, int(im.height * w / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def thumb_bytes(key: str, img: Image.Image, w: int) -> bytes:
    k = (key, w)
    got = _thumb_cache.get(k)
    if got is None:
        got = jpeg_bytes(img, w=w)
        if len(_thumb_cache) > 400:
            _thumb_cache.clear()
        _thumb_cache[k] = got
    return got


# ---------------------------------------------------------------- 预处理 + 描图

def _outside_mask(small: np.ndarray, tol: float = 0.16, step: float = 0.10) -> np.ndarray:
    """small=(r,c,3) 0~1。返回 bool 掩码：与边缘连通、颜色沿路平缓过渡的区域。

    种子只取边缘上的主导色簇——人物压到图片边上时，不该把人物当成背景；
    传播看相邻格颜色差（渐变背景也能整片吃掉），碰到人物轮廓的大反差自然停下。"""
    r, c = small.shape[0], small.shape[1]
    edge = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]], axis=0)
    keys = np.round(edge * 3.999).astype(np.int32)
    key = keys[:, 0] * 16 + keys[:, 1] * 4 + keys[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    bgc = edge[key == vals[int(np.argmax(counts))]].mean(axis=0)

    visited = np.zeros((r, c), bool)
    outside = np.zeros((r, c), bool)
    q = deque()
    for x in np.where(np.linalg.norm(small[0] - bgc, axis=1) < tol)[0].tolist():
        q.append((0, x))
    for x in np.where(np.linalg.norm(small[-1] - bgc, axis=1) < tol)[0].tolist():
        q.append((r - 1, x))
    for y in np.where(np.linalg.norm(small[:, 0] - bgc, axis=1) < tol)[0].tolist():
        q.append((y, 0))
    for y in np.where(np.linalg.norm(small[:, -1] - bgc, axis=1) < tol)[0].tolist():
        q.append((y, c - 1))

    steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
    while q:
        y, x = q.popleft()
        if not (0 <= y < r and 0 <= x < c) or visited[y, x]:
            continue
        visited[y, x] = True
        outside[y, x] = True
        here = small[y, x]
        for dy, dx in steps:
            yy, xx = y + dy, x + dx
            if not (0 <= yy < r and 0 <= xx < c) or visited[yy, xx]:
                continue
            if float(np.linalg.norm(small[yy, xx] - here)) < step:
                q.append((yy, xx))
    return outside


def key_out_bg(img: Image.Image, tol: float = 0.16, feather: int = 3) -> Image.Image:
    """与边缘连通、且与某一粒边缘种子同色的区域 → 压暗。白纸底 / 平色背景都能去掉。"""
    small = np.asarray(img.resize((120, 80), Image.LANCZOS)).astype(np.float32) / 255.0
    outside = _outside_mask(small, tol)
    m = Image.fromarray((outside * 255).astype(np.uint8), "L")
    m = m.resize(img.size, Image.BILINEAR)
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    arr = np.asarray(img).astype(np.float32)
    a = (np.asarray(m).astype(np.float32) / 255.0)[..., None]
    arr = arr * (1.0 - a * 0.94)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def autocrop(src: dict, tol: float = 0.16) -> list:
    """自动取景：算出"去边"后的裁剪框（0~1）。白纸页边、纯色背景都会被切掉。"""
    img = load_src(src)
    c, r = 120, 80
    small = np.asarray(img.resize((c, r), Image.LANCZOS)).astype(np.float32) / 255.0
    inside = ~_outside_mask(small, tol)
    colsum = inside.sum(axis=0)
    rowsum = inside.sum(axis=1)
    cx = np.where(colsum > r * 0.12)[0]      # 要求整列/整行有一成以上是内容，滤掉边缘噪点
    ry = np.where(rowsum > c * 0.12)[0]
    if len(cx) == 0 or len(ry) == 0:
        return [0.0, 0.0, 1.0, 1.0]
    x0, x1, y0, y1 = int(cx[0]), int(cx[-1]), int(ry[0]), int(ry[-1])
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 0.90 * c * r:
        return [0.0, 0.0, 1.0, 1.0]
    pad = 1
    return [max(0.0, round((x0 - pad) / c, 3)), max(0.0, round((y0 - pad) / r, 3)),
            min(1.0, round((x1 + 1 + pad) / c, 3)), min(1.0, round((y1 + 1 + pad) / r, 3))]


def sketch_score(img: Image.Image) -> dict:
    """参考图的可描性评估：分辨率 / 对比度 / 主体占比 / 背景干净度，加权成 0~100。"""
    w, h = img.size
    small = np.asarray(img.resize((120, 80), Image.LANCZOS)).astype(np.float32) / 255.0
    gray = small[..., 0] * 0.3 + small[..., 1] * 0.59 + small[..., 2] * 0.11
    outside = _outside_mask(small, 0.16)
    subject = 1.0 - float(outside.mean())
    noise = float(small[outside].std(axis=0).mean()) if outside.any() else 0.05
    parts = {
        "分辨率": min(1.0, min(w, h) / 600.0),
        "对比度": min(1.0, float(gray.std()) / 0.15),
        "主体": max(0.0, 1.0 - abs(subject - 0.55) / 0.55),
        "背景": max(0.0, min(1.0, 1.0 - noise / 0.22)),
    }
    score = round(100 * (0.15 * parts["分辨率"] + 0.32 * parts["对比度"]
                         + 0.33 * parts["主体"] + 0.20 * parts["背景"]))
    tips = []
    if parts["对比度"] < 0.55:
        tips.append("画面偏灰，反差可加大")
    if subject > 0.78:
        tips.append("主体占太满，可以取景裁一裁")
    elif subject < 0.25:
        tips.append("主体偏小，适合取景放大")
    if parts["背景"] < 0.5:
        tips.append("背景杂，建议开去背")
    if parts["分辨率"] < 0.5:
        tips.append("分辨率偏低")
    return {"score": score, "subject_pct": round(subject * 100),
            "parts": {k: round(v * 100) for k, v in parts.items()},
            "advice": "；".join(tips[:2])}


def preprocess(img: Image.Image, p: dict) -> Image.Image:
    im = img
    if p.get("invert"):
        im = ImageOps.invert(im)
    if p.get("key"):
        im = key_out_bg(im, tol=float(p.get("key_tol", 0.16)))
    contrast = float(p.get("contrast", 1.0))
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    return im


def crop_of(img: Image.Image, crop) -> Image.Image:
    if not crop:
        return img
    l, t, r, b = [float(x) for x in crop]
    iw, ih = img.size
    box = (int(l * iw), int(t * ih), int(r * iw), int(b * ih))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return img
    return img.crop(box)


def trace_png(img: Image.Image, p: dict):
    """返回 (png, cover 比例, 三层数据)——串行调用。"""
    cols, rows = int(p.get("cols", 120)), int(p.get("rows", 80))
    with LOCK:
        tracer.COLS, tracer.ROWS = cols, rows
        tracer.W, tracer.H = cols * tracer.CW, rows * tracer.CH
        art, shade, part, cover, plain = tracer.trace(img)
        shade_rows = ["".join(str(int(x)) for x in row) for row in shade]
        png = tracer.draw_frame(art, shade_rows, part, "duo", plain=plain)
    return png, float(cover.mean()), (art, shade_rows, part, plain)


BASE = {"cols": 120, "rows": 80, "contrast": 1.2, "key": True, "key_tol": 0.16,
        "invert": False}


def _variants(p: dict) -> list:
    """围绕当前参数生成 6 张候选：调反差、翻转开关、换密度。"""
    p = {**BASE, **(p or {})}
    out = [("当前参数", dict(p))]
    out.append(("反差 ×0.8", {**p, "contrast": round(float(p["contrast"]) * 0.8, 2)}))
    out.append(("反差 ×1.25", {**p, "contrast": round(float(p["contrast"]) * 1.25, 2)}))
    out.append(("去背 " + ("关" if p.get("key") else "开"),
                {**p, "key": not p.get("key")}))
    out.append(("反相 " + ("关" if p.get("invert") else "开"),
                {**p, "invert": not p.get("invert")}))
    if int(p.get("cols", 120)) >= 120:
        out.append(("96×64", {**p, "cols": 96, "rows": 64}))
    else:
        out.append(("144×96", {**p, "cols": 144, "rows": 96}))
    return out


def candidates(src: dict, crop, params: dict) -> list:
    img = crop_of(load_src(src), crop)
    out = []
    for label, p in _variants(params):
        pre = preprocess(img, p)
        png, cover, _ = trace_png(pre, p)
        buf = io.BytesIO()
        png.save(buf, "PNG")
        out.append({"label": label, "params": p, "cover": round(cover * 100, 1),
                    "png_b64": base64.b64encode(buf.getvalue()).decode()})
    base = {**BASE, **(params or {})}

    def score(c: dict) -> float:
        p, cover = c["params"], c["cover"]
        s = 100.0 - abs(cover - 55) * 0.8          # 覆盖度离 55% 越远越差
        if cover > 92:
            s -= 50                                # 糊成一片
        if cover < 10:
            s -= 40                                # 几乎空屏
        s -= abs(float(p["contrast"]) - 1.3) * 10  # 反差 1.3 附近最稳
        if bool(p.get("key")) != bool(base.get("key")):
            s -= 12                                # 别乱翻开关
        if bool(p.get("invert")) != bool(base.get("invert")):
            s -= 12
        if int(p.get("cols", 120)) != 120:
            s -= 6
        return s

    best = max(range(len(out)), key=lambda i: score(out[i]))
    for i, c in enumerate(out):
        c["recommended"] = i == best
    return out


def save_asset(src: dict, crop, params: dict, meta: dict) -> dict:
    aid = re.sub(r"[^a-z0-9_\-]", "", str(meta.get("id") or "").strip().lower())
    if not aid:
        raise ValueError("id 只能用小写字母/数字/下划线/短横")
    raw = crop_of(load_src(src), crop)
    p = {**BASE, **(params or {})}
    pre = preprocess(raw, p)
    png, cover, (art, shade_rows, part, plain) = trace_png(pre, p)
    out = ASSETS / aid
    out.mkdir(parents=True, exist_ok=True)
    rows = lambda M: ["".join(str(ch) for ch in row) for row in M]
    split = lambda s: [x.strip() for x in re.split(r"[,，、]", str(s or "")) if x.strip()]
    key = {"id": aid, "name": meta.get("name") or aid,
           "aliases": split(meta.get("aliases")), "tags": split(meta.get("tags")),
           "cols": int(p["cols"]), "rows": int(p["rows"]),
           "art": rows(art), "shade": [str(x) for x in shade_rows], "part": rows(part),
           "plain": ["".join("1" if x else "0" for x in row) for row in plain]}
    if meta.get("src_fp"):
        key["src_fp"] = str(meta.get("src_fp"))[:80]
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    raw.save(out / "source.jpg", quality=88)
    png.save(out / "preview.png")
    (out / "params.json").write_text(json.dumps(
        {"src": src, "crop": crop, "params": p,
         "saved": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return {"ok": True, "id": aid, "cover": round(cover * 100, 1)}


# ---------------------------------------------------------------- AI 建议

def suggest(src: dict, crop, params: dict) -> dict:
    """AI 命名建议（两段式实现见 core/vision.py）。"""
    from . import vision
    try:
        img = crop_of(load_src(src), crop)
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}
    return vision.describe(img)


# ---------------------------------------------------------------- 路由

def dispatch(path: str, method: str, query: dict, body: dict | None = None,
             on_saved=None):
    """处理 /wb/*。返回 (code, ctype, bytes)；不是工作台路径时返回 None。"""
    q = {k: v[0] for k, v in query.items()}
    body = body or {}
    if method == "GET":
        if path in ("/wb", "/wb/"):
            return (200, "text/html; charset=utf-8",
                    (ROOT / "core" / "web" / "workbench.html").read_bytes())
        if path == "/wb/sources":
            from . import assets as assets_mod
            assets_mod.reload()
            data = {"manga": list_manga(), "pixiv": list_pixiv(),
                    "assets": assets_mod.catalogue(),
                    "dirs": {"manga": str(MANGA_DIR), "pixiv": str(PIXIV_DIR)}}
            return _json(data)
        if path == "/wb/manga":
            return _json({"chapters": list_chapters(q.get("series", ""))})
        if path == "/wb/chapter":
            pages = chapter_pages(q.get("series", ""), q.get("chapter", ""))
            return _json({"pages": len(pages)})
        if path == "/wb/page":
            img = page_image(q.get("series", ""), q.get("chapter", ""), int(q.get("page", 0)))
            w = int(q.get("w") or 0)
            key = "p|%s|%s|%s" % (q.get("series"), q.get("chapter"), q.get("page"))
            return (200, "image/jpeg",
                    thumb_bytes(key, img, w) if w else jpeg_bytes(img, quality=88))
        if path == "/wb/pixiv":
            img = pixiv_image(q.get("name", ""))
            w = int(q.get("w") or 0)
            return (200, "image/jpeg",
                    thumb_bytes("x|" + q.get("name", ""), img, w) if w else jpeg_bytes(img, quality=88))
        if path == "/wb/assetfile":
            aid = q.get("id", "")
            name = q.get("file", "")
            if name not in ("preview.png", "source.jpg"):
                raise ValueError(name)
            f = _safe(aid, ASSETS) / name
            ctype = "image/png" if name.endswith("png") else "image/jpeg"
            return (200, ctype, f.read_bytes())
        if path == "/wb/file":
            p = Path(q.get("path") or "")
            if not str(p.resolve()).startswith(str(UPLOADS.resolve())):
                raise PermissionError("只允许读上传缓存里的图")
            return (200, "image/jpeg",
                    jpeg_bytes(Image.open(p).convert("RGB"), quality=88))
        if path == "/wb/fetch/search":
            from . import fetch as fetch_mod
            kw = (q.get("kw") or "").strip()
            return _json({"hits": fetch_mod.search(kw) if kw else [],
                          "proxy": fetch_mod.client().proxy})
        if path == "/wb/fetch/chapters":
            from . import fetch as fetch_mod
            return _json({"chapters": fetch_mod.chapters(q.get("cid", ""))})
        if path == "/wb/autocrop":
            try:
                crop = autocrop(json.loads(q.get("src") or "{}"))
            except Exception:
                crop = [0.0, 0.0, 1.0, 1.0]
            return _json({"crop": crop})
        if path == "/wb/score":
            try:
                img = load_src(json.loads(q.get("src") or "{}"))
                return _json(sketch_score(img))
            except Exception as e:
                return _json({"error": str(e)})
        if path == "/wb/asset":
            d = _safe(q.get("id", ""), ASSETS)
            key = json.loads((d / "key.json").read_text(encoding="utf8"))
            params = {}
            if (d / "params.json").exists():
                try:
                    params = (json.loads((d / "params.json").read_text(encoding="utf8"))
                              .get("params") or {})
                except Exception:
                    params = {}
            return _json({"id": key.get("id"), "name": key.get("name"),
                          "aliases": key.get("aliases") or [],
                          "tags": key.get("tags") or [], "params": params})
        return None
    if path == "/wb/upload":
        name = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff\-]", "_", str(body.get("name") or "up.jpg"))
        data = base64.b64decode(body.get("data_b64") or "")
        UPLOADS.mkdir(parents=True, exist_ok=True)
        f = UPLOADS / ("%d_%s" % (int(time.time()), name))
        f.write_bytes(data)
        Image.open(f).convert("RGB")
        return _json({"path": str(f)})
    if path == "/wb/candidates":
        rows = candidates(body.get("src") or {}, body.get("crop"), body.get("params") or {})
        return _json({"candidates": rows})
    if path == "/wb/save":
        r = save_asset(body.get("src") or {}, body.get("crop"),
                       body.get("params") or {}, body.get("meta") or {})
        if on_saved:
            try:
                on_saved()
            except Exception as e:
                r["warning"] = "会话刷新失败：%s" % e
        return _json(r)
    if path == "/wb/suggest":
        return _json(suggest(body.get("src") or {}, body.get("crop"),
                             body.get("params") or {}))
    if path == "/wb/fetch/download":
        from . import fetch as fetch_mod
        r = fetch_mod.download_chapter(body.get("cid"), body.get("chid"),
                                       body.get("title") or "抓取",
                                       str(body.get("serial") or "01"), MANGA_DIR)
        return _json(r)
    if path == "/wb/asset/delete":
        import shutil
        aid = str(body.get("id") or "")
        d = _safe(aid, ASSETS)
        if not d.is_dir() or not (d / "key.json").exists():
            raise ValueError("不是素材目录：%s" % aid)
        shutil.rmtree(d)
        if on_saved:
            try:
                on_saved()
            except Exception:
                pass
        return _json({"ok": True, "id": aid})
    return None


def _json(obj) -> tuple:
    return (200, "application/json; charset=utf-8",
            json.dumps(obj, ensure_ascii=False).encode("utf8"))
