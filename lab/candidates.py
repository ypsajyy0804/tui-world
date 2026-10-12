"""素材候选：同一张参考图，换几组参数各描一遍，拼成对比图让人挑。

这是"预制过程自动化"的最小实验：不是为了全自动出好图，而是让"挑 + 微调"
变得很快。参数目前有三类：裁切、反差、网格密度。

用法：python lab/candidates.py <参考图> [--out out/cand_sheet.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from core.config import font
import trace as tracer

CW, CH = tracer.CW, tracer.CH


def variant(img: Image.Image, crop=None, contrast=1.0, sharp=1.0, cols=96, rows=64):
    tracer.COLS, tracer.ROWS = cols, rows
    tracer.W, tracer.H = cols * CW, rows * CH
    im = img
    if crop:
        l, t, r, b = crop
        iw, ih = im.size
        im = im.crop((int(l * iw), int(t * ih), int(r * iw), int(b * ih)))
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if sharp != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharp)
    art, shade, part, cover, plain = tracer.trace(im)
    shade_rows = ["".join(str(int(x)) for x in row) for row in shade]
    out = tracer.draw_frame(art, shade_rows, part, palette="duo", plain=plain)
    return out, float(cover.mean())


VARIANTS = [
    ("A 现状 96x64", dict()),
    ("B 反差 1.35", dict(contrast=1.35)),
    ("C 只取上半身", dict(crop=(0.06, 0.0, 1.0, 0.62))),
    ("D 上半身+反差", dict(crop=(0.06, 0.0, 1.0, 0.62), contrast=1.35)),
    ("E 密一点 120x80", dict(cols=120, rows=80)),
    ("F 面部特写", dict(crop=(0.18, 0.02, 0.95, 0.45), contrast=1.2)),
]


def main(argv):
    ref = argv[0] if argv else "D:/GitHub/temp/tui-char-lab/ref.jpg"
    out = "out/cand_sheet.png"
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    img = Image.open(ref).convert("RGB")
    tiles = []
    for name, kw in VARIANTS:
        tile, cov = variant(img, **kw)
        tiles.append((name, tile, cov))
        print("%-16s %s  覆盖 %.1f%%" % (name, tile.size, cov * 100))
    tw, th = tiles[0][1].size
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    pad, cap = 10, 22
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + cap + pad) + pad), (8, 8, 10))
    d = ImageDraw.Draw(sheet)
    for i, (name, tile, cov) in enumerate(tiles):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + cap + pad)
        d.text((x, y), name, font=font(13, "cjk"), fill=(220, 220, 230))
        sheet.paste(tile, (x, y + cap))
    sheet.save(out)
    print("拼图：", out, sheet.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
