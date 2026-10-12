"""工作台前置实验：自动去背 + 描图，挑默认参数。

假设：trace() 的甜区是深底 + 主体占满 + 扁平色。白底漫画 / 彩色杂底需要
先把"与边缘连通、颜色接近边缘"的区域压暗（去背），再描。
"""
from __future__ import annotations

import io
import sys
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import trace as tracer  # noqa: E402

OUT = Path(r"D:\GitHub\.tmp\probe")


def key_out_bg(img: Image.Image, tol: float = 0.16, feather: int = 3) -> Image.Image:
    """在 120x80 小图上做固定种子色的泛洪：与某粒边缘种子同色（且与之连通）的区域压暗。"""
    c, r = 120, 80
    small = np.asarray(img.resize((c, r), Image.LANCZOS)).astype(np.float32) / 255.0
    visited = np.zeros((r, c), bool)
    outside = np.zeros((r, c), bool)
    seeds = []
    for x in range(c):
        seeds.append((0, x)); seeds.append((r - 1, x))
    for y in range(r):
        seeds.append((y, 0)); seeds.append((y, c - 1))
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for sy, sx in seeds:
        if visited[sy, sx]:
            continue
        seed_color = small[sy, sx]
        q = deque([(sy, sx)])
        while q:
            y, x = q.popleft()
            if not (0 <= y < r and 0 <= x < c) or visited[y, x]:
                continue
            visited[y, x] = True
            outside[y, x] = True
            for dy, dx in steps:
                yy, xx = y + dy, x + dx
                if not (0 <= yy < r and 0 <= xx < c) or visited[yy, xx]:
                    continue
                if float(np.linalg.norm(small[yy, xx] - seed_color)) < tol:
                    q.append((yy, xx))
    m = Image.fromarray((outside * 255).astype(np.uint8), "L")
    m = m.resize(img.size, Image.BILINEAR)
    if feather:
        from PIL import ImageFilter
        m = m.filter(ImageFilter.GaussianBlur(feather))
    arr = np.asarray(img).astype(np.float32)
    a = (np.asarray(m).astype(np.float32) / 255.0)[..., None]
    arr = arr * (1.0 - a * 0.94)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def shoot(img: Image.Image, name: str, contrast: float = 1.0, invert: bool = False,
          key: bool = False, tol: float = 0.16, cols: int = 120, rows: int = 80):
    im = img
    if invert:
        im = ImageOps.invert(im)
    if key:
        im = key_out_bg(im, tol=tol)
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    tracer.COLS, tracer.ROWS = cols, rows
    tracer.W, tracer.H = cols * tracer.CW, rows * tracer.CH
    art, shade, part, cover, plain = tracer.trace(im)
    shade_rows = ["".join(str(int(x)) for x in row) for row in shade]
    png = tracer.draw_frame(art, shade_rows, part, "duo", plain=plain)
    p = OUT / ("p_%s.png" % name)
    png.save(p)
    print("%-22s cover %5.1f%%  -> %s" % (name, cover.mean() * 100, p.name))
    return p


def manga_page(series: str, chapter_idx: int, page_idx: int) -> Image.Image:
    d = Path(r"D:\VM_share\manga") / series
    f = sorted(d.glob("*.cbz"))[chapter_idx]
    with zipfile.ZipFile(f) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
        return Image.open(io.BytesIO(z.read(names[page_idx]))).convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    berserk = Image.open(OUT / "berserk_mid.png").convert("RGB")
    pixiv = Image.open(r"D:\图片\pixiv\100156549_p0_master1200.jpg").convert("RGB")

    for tol in (0.10, 0.16, 0.24):
        shoot(berserk, "berserk_t%02d" % int(tol * 100), key=True, tol=tol, contrast=1.2)
        shoot(pixiv, "pixiv_t%02d" % int(tol * 100), key=True, tol=tol, contrast=1.15)

    try:
        page = manga_page("私のこと好きじゃなかったのかよ", 0, 6)
        page.save(OUT / "suki_p6.png")
        w, h = page.size
        crop = page.crop((0, 0, w, int(h * 0.55)))          # 上半页，多是人物对话格
        for tol in (0.16, 0.24):
            shoot(crop, "suki_t%02d" % int(tol * 100), key=True, tol=tol, contrast=1.2)
    except Exception as e:
        print("suki 页失败：", e)


if __name__ == "__main__":
    main()
