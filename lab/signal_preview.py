"""素材动效预览：把一张素材按某个动效在几个时刻渲染出来，拼成对照图看它怎么动。

用法：
    python lab/signal_preview.py out.png 0 1 2 5
    python lab/signal_preview.py out.png 0 1 2 6 --motion text --text 霍格沃茨
    python lab/signal_preview.py out.png 0 1 --asset take_1011202210 --motion glitch
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from core import assets as assets_mod
from core.scene import render
from core.world import World


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    out = Path(argv[0])
    times, asset_id, motion, text = [], "", "sway", ""
    i = 1
    while i < len(argv):
        if argv[i] == "--asset":
            asset_id, i = argv[i + 1], i + 2
            continue
        if argv[i] == "--motion":
            motion, i = argv[i + 1], i + 2
            continue
        if argv[i] == "--text":
            text, i = argv[i + 1], i + 2
            continue
        times.append(float(argv[i]))
        i += 1
    times = times or [0.0, 1.0, 2.0, 5.0]

    lib = assets_mod.load_all()
    if not lib:
        print("素材库是空的，先用工作台/取材器入库")
        return 1
    asset = lib.get(asset_id) if asset_id else list(lib.values())[0]
    if asset is None:
        print("没有素材 %s；库里现有：%s" % (asset_id, ", ".join(sorted(lib))))
        return 1

    tiles, t0 = [], time.time()
    for t in times:
        w = World(seed=7)
        w.signal = asset.id
        w.signal_name = asset.name
        w.signal_motion = motion
        w.signal_text = text
        w.signal_t0 = time.time() - t
        img, _ = render(w, meta={"title": "%s · %s · t=%.1fs" % (asset.name, motion, t)})
        tiles.append(img)
    W, H = tiles[0].size
    cols = min(2, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols + 8 * (cols + 1), H * rows + 8 * (rows + 1)),
                      (28, 28, 32))
    for i, im in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(im, (8 + c * (W + 8), 8 + r * (H + 8)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print("渲染 %d 帧，平均 %.2fs/帧 → %s" % (
        len(tiles), (time.time() - t0) / len(tiles), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
