"""M0 CLI：一句话 → 导演 → 世界 → 一帧 PNG。

用法（在仓库根目录）：
    python -m core.probe "我们聊聊霍格沃茨吧"
    python -m core.probe "聊聊霍格沃茨|他摸了摸额头上的那道疤" --out out/hogwarts.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ROOT, load_env
from .director import Director
from .llm import LLM
from .scene import render
from .world import World


def main(argv=None):
    ap = argparse.ArgumentParser(prog="core.probe", description="tui-world M0 探针")
    ap.add_argument("text", help="一句或多句中文，用 | 分隔多轮")
    ap.add_argument("--out", default=str(ROOT / "out" / "world.png"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-hops", type=int, default=3)
    a = ap.parse_args(argv)

    cfg = load_env()
    model = a.model or cfg.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    llm = LLM(cfg.get("DEEPSEEK_API_KEY", ""),
              cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"), model)
    world = World(seed=a.seed)
    d = Director(llm, world, max_hops=a.max_hops)
    total, last = 0, {}
    for line in [s.strip() for s in a.text.split("|") if s.strip()]:
        r = d.say(line)
        total += r["tokens"]
        last = r
        print("-" * 66)
        print("用户：" + line)
        for c in r["tool_calls"]:
            print("  · %s %s" % (c["name"], json.dumps(c["args"], ensure_ascii=False)))
        if r["text"]:
            print("  导演：" + r["text"][:160].replace("\n", " "))
        print("  %.1fs / %d tokens" % (r["seconds"], r["tokens"]))

    meta = {"title": world.focus.get("concept") or "world",
            "model": model, "tokens": total, "seconds": last.get("seconds", 0),
            "hops": len(last.get("tool_calls", [])), "seed": world.seed}
    img, stats = render(world, a.out, meta)
    world_json = Path(a.out).with_suffix(".world.json")
    world_json.write_text(json.dumps({
        "palette": world.palette, "energy": world.energy,
        "weather": world.weather, "focus": world.focus,
        "stage_plan": world.stage_plan,
    }, ensure_ascii=False, indent=2), encoding="utf8")
    print("=" * 66)
    print("世界：" + world.snapshot().replace("\n", "  "))
    print("渲染：" + a.out + "  （%.0f ms，%d 面）" % (
        sum(v for k, v in stats.items() if k.endswith("_ms")), stats.get("faces", 0)))
    print("状态：" + str(world_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
