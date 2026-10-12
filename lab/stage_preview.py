"""分镜预览：把一份 stage 分镜按几个时刻渲染出来，拼成一张对照图看它怎么动。

用法：
    python lab/stage_preview.py out.png 0 1 3 6 10            # 内置示例分镜
    python lab/stage_preview.py out.png 0 2 5 --plan p.json   # 换自己的分镜单
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from core.scene import render
from core.world import World

SAMPLE = {
    "title": "训练日志",
    "parts": [
        {"kind": "counter", "label": "loss", "from": 9.2, "to": 0.42, "dur": 6, "fmt": "{:.3f}"},
        {"kind": "chart", "label": "grad norm", "shape": "fall", "dur": 8, "y": 0.40},
        {"kind": "progress", "label": "checkpoint", "dur": 7, "y": 0.76, "w": 0.5},
        {"kind": "particles", "style": "star", "density": 40},
    ],
}


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    out = Path(argv[0])
    times, plan = [], SAMPLE
    i = 1
    while i < len(argv):
        if argv[i] == "--plan":
            plan = json.loads(Path(argv[i + 1]).read_text(encoding="utf-8-sig"))
            i += 2
            continue
        times.append(float(argv[i]))
        i += 1
    times = times or [0.0, 1.0, 3.0, 6.0]
    world = World(seed=7)
    world.stage_plan = plan
    world.stage_title = str(plan.get("title") or "")
    tiles, t0 = [], time.time()
    for t in times:
        world.stage_t0 = time.time() - t
        img, _ = render(world, meta={"title": "t=%.1fs" % t})
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
