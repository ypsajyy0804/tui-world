"""动作模板目检：同一张素材 x 6 个动作，关键帧拼一张大图。

用法：python -m lab.check_motions [素材id] [输出路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from core import assets as assets_mod
from core.config import Pen, font

TIMES = [0.15, 0.45, 0.80, 2.60]
SCALE = 0.5


def main():
    args = sys.argv[1:]
    aid = args[0] if args else "david"
    out = Path(args[1]) if len(args) > 1 else ROOT / "out" / "motions.png"
    pen = Pen("amber")
    asset = assets_mod.find(aid)
    if asset is None:
        print("no asset", aid, "have:", sorted(assets_mod.load_all().keys()))
        return
    tag_fnt = font(13)
    pad = 6

    rows = []
    for m in assets_mod.MOTIONS:
        sig = assets_mod.Signal(asset, pen, m)
        frames = [sig.frame(t) for t in TIMES]
        w, h = frames[0].size
        w2, h2 = int(w * SCALE), int(h * SCALE)
        strip = Image.new("RGB", (pad + 4 * (w2 + pad), h2 + 42), (16, 16, 20))
        d = ImageDraw.Draw(strip)
        d.text((pad, 6), "%s   t=%s" % (m, ",".join("%.2f" % t for t in TIMES)),
               font=tag_fnt, fill=(200, 200, 210))
        for i, f in enumerate(frames):
            strip.paste(f.resize((w2, h2), Image.LANCZOS), (pad + i * (w2 + pad), 30))
        rows.append(strip)

    total_w = max(r.width for r in rows)
    total_h = sum(r.height + pad for r in rows) + pad
    sheet = Image.new("RGB", (total_w + pad * 2, total_h + pad), (16, 16, 20))
    y = pad
    for r in rows:
        sheet.paste(r, (pad, y))
        y += r.height + pad
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print("OK ->", out, sheet.size)


if __name__ == "__main__":
    main()
