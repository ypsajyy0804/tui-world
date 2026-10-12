"""把正在跑的服务上的世界状态抓下来存成 JSON（配合 lab/replay.py）。

用法：python lab/snap.py [--port 8777] [--out out/live.world.json]
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="snap")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--url", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    url = a.url or "http://127.0.0.1:%d/state" % a.port
    s = json.loads(urllib.request.urlopen(url, timeout=10).read().decode("utf8"))
    world = dict(s["world"])
    out = Path(a.out or ("out/live.world.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(world, ensure_ascii=False, indent=1), encoding="utf8")
    print("已保存：%s  （屏幕：%s）" % (
        out, world.get("stage") or (world.get("signal") or {}).get("name") or "空"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
