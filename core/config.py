"""基础设施：.env 读取、调色板、字体，以及 View 需要的 Project 替身。"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent.parent

MONO_FALLBACK = [
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
CJK_FALLBACK = [
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def load_env(path=None) -> dict:
    """读 .env（环境变量优先），返回配置字典。"""
    cfg: dict = {}
    p = Path(path) if path else ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        v = os.environ.get(k)
        if v:
            cfg[k] = v
    return cfg


PALETTES = {
    "amber": {
        "bg": (10, 7, 3), "ink": (255, 176, 84), "dim": (104, 62, 24),
        "hot": (255, 240, 200), "warn": (255, 118, 62), "ok": (150, 255, 172),
    },
    "phosphor": {
        "bg": (2, 8, 4), "ink": (110, 255, 150), "dim": (36, 96, 58),
        "hot": (220, 255, 232), "warn": (255, 112, 92), "ok": (140, 255, 180),
    },
    "deepsea": {
        "bg": (4, 7, 15), "ink": (150, 190, 240), "dim": (52, 74, 110),
        "hot": (226, 240, 255), "warn": (255, 122, 122), "ok": (120, 255, 202),
    },
}


class Pen:
    """tuikit.space.View 需要的最小 Project 替身：color / path / style。"""

    style: dict = {}

    def __init__(self, palette: str = "amber"):
        self.palette = palette if palette in PALETTES else "amber"
        self.colors = dict(PALETTES[self.palette])

    def path(self, rel):
        return Path(rel)

    def color(self, name):
        return self.colors.get(name, self.colors["ink"])


_fonts: dict = {}


def font(size: int, kind: str = "mono"):
    key = (int(size), kind)
    if key in _fonts:
        return _fonts[key]
    cands = CJK_FALLBACK if kind == "cjk" else MONO_FALLBACK
    picked = None
    for c in cands:
        if Path(c).exists():
            picked = ImageFont.truetype(c, int(size))
            break
    _fonts[key] = picked or ImageFont.load_default()
    return _fonts[key]
