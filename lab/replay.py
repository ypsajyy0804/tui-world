"""离线重渲染：把一个世界状态 JSON 重新画成 PNG（不走 API）。

用法：
    python lab/replay.py out/live.world.json --out out/replay.png

状态从正在跑的服务里抓：
    python lab/snap.py            （见 lab/snap.py）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scene import render
from core.world import World


def load(path) -> World:
    return World.from_dict(json.loads(Path(path).read_text(encoding="utf8")))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="replay", description="世界状态 → PNG")
    ap.add_argument("state")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = a.out or str(Path(a.state).with_suffix(".png"))
    w = load(a.state)
    _, stats = render(w, out, {"title": w.focus.get("concept") or "world",
                               "model": "replay", "seed": w.seed})
    ms = sum(v for k, v in stats.items() if k.endswith("_ms"))
    print("渲染：%s  (%.0f ms, %d faces)" % (out, ms, stats.get("faces", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
