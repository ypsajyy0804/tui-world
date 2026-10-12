"""具体化 + 呈现：世界 → 字符网格 → PNG（只剩窗框，没有仪表层文字）。

屏幕的两路内容（素材信号 / 分镜）画在同一个显示区里；世界本身只剩一层
星空 + 地面网格 + 地平线的底子。代码直接画的物件（河、冰川那一套）已砍掉。
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import assets as assets_mod
from . import stage as stage_mod
from .config import Pen, font

from tuikit import post, space

_CAM = {"wide": (16.0, 28.0, 10.0), "mid": (11.5, 22.0, 8.0), "close": (6.5, 14.0, 5.0)}
_CENTER = (0.0, 1.2, 4.0)


def _stage(w):
    z = w.focus.get("zoom") or 1.0
    if z < 1.35:
        return "wide"
    if z < 2.2:
        return "mid"
    return "close"


def _camera(w, stage="wide"):
    """空世界也有取景：zoom 决定机位（wide / mid / close）。"""
    dist, yaw, pitch = _CAM[stage]
    return space.orbit(target=_CENTER, yaw=yaw, pitch=pitch, dist=dist, fov=42.0)


def _stars(v, w, n=90):
    rng = random.Random(w.seed)
    pts = [(rng.uniform(-26, 26), rng.uniform(3.5, 18), rng.uniform(-6, 30)) for _ in range(n)]
    v.glyphs(pts, [rng.choice([".", "*", "+"]) for _ in range(n)], lv=0.45, color="dim")


def _weather_effects(v, w):
    if w.weather in ("rain", "storm"):
        rng = random.Random(w.seed + 3)
        for _ in range(80):
            x = rng.uniform(-13, 13)
            y = rng.uniform(0.5, 9.5)
            z = rng.uniform(-2, 14)
            v.lines((x, y, z), (x - 0.28, y - 0.7, z), lv=0.20)
    elif w.weather == "snow":
        rng = random.Random(w.seed + 5)
        pts = [(rng.uniform(-13, 13), rng.uniform(0.5, 9.5), rng.uniform(-2, 14)) for _ in range(60)]
        v.glyphs(pts, ["."] * len(pts), lv=0.5, color="hot")


def _genre(v, w, stage="wide"):
    """空世界的底子：星、地面网格、地平线（不再有代码画的物件和楼）。"""
    if stage == "close":
        v.lines((-30, 0.02, 30), (30, 0.02, 30), lv=0.18)
        space.floor_grid(v, -6, 6, -4, 12, step=1.0, lv=0.10)
        _stars(v, w, 18)
        return
    _stars(v, w, 40 if stage == "mid" else 90)
    space.floor_grid(v, -14, 14, -10, 30, step=2.0, lv=0.09)
    v.lines((-30, 0.02, 30), (30, 0.02, 30), lv=0.22)
    _weather_effects(v, w)


def _chrome(img, w, pen, meta):
    """窗框：一圈边 + 顶栏（标题 / 屏幕上的那一路叫什么）+ 画面底部一行淡字水印。"""
    d = ImageDraw.Draw(img)
    W, H = img.size
    dim, ink, hot = pen.color("dim"), pen.color("ink"), pen.color("hot")
    d.rectangle((6, 6, W - 7, H - 7), outline=dim)
    d.line((6, 34, W - 7, 34), fill=dim)
    d.text((18, 12), "WORLD", font=font(15), fill=ink)
    d.text((84, 14), meta.get("title", ""), font=font(15, "cjk"), fill=hot)
    if w.stage_plan:
        d.text((W - 20, 14), "STAGE  " + (w.stage_title or "分镜"),
               font=font(14, "cjk"), fill=hot, anchor="ra")
    elif w.signal:
        d.text((W - 20, 14), "SIGNAL  " + (w.signal_name or w.signal),
               font=font(14, "cjk"), fill=hot, anchor="ra")
    elif w.focus.get("concept"):
        d.text((W - 20, 14), "FOCUS  " + w.focus["concept"], font=font(14, "cjk"),
               fill=hot, anchor="ra")
    mark = str(meta.get("mark") or "")
    if mark:
        bg = pen.color("bg")
        wm = tuple(int(dim[i] * 0.62 + bg[i] * 0.38) for i in range(3))
        d.text((20, H - 27), mark, font=font(13, "cjk"), fill=wm)


def render(world, out_path=None, meta=None, W=880, H=720, cell=(8, 16)):
    """一帧 = 世界的一眼。显示区从顶栏下一直铺到底，meta 只用来写标题。"""
    pen = Pen(world.palette)
    stage = _stage(world)
    img = Image.new("RGB", (W, H), pen.color("bg"))
    margin = 14
    rect = (margin, 40, W - margin, H - 8)
    s_age = time.time() - (world.stage_t0 or time.time())
    if world.stage_plan and s_age >= stage_mod.FADE:
        # 分镜已经盖满屏幕：世界那一层（画 + 后处理）不用算了，省掉半条管线
        stats = {}
    else:
        fog = (4.0, 22.0, 0.10) if world.weather in ("fog", "storm") else (6.0, 40.0, 0.18)
        v = space.View(pen, rect, _camera(world, stage), cell=cell, fog=fog)
        _genre(v, world, stage)
        v.draw(img)
        img = post.make_post()(img)
        stats = v.stats
    if world.stage_plan:
        # 分镜占屏：每帧从零重画，动的不是图，是信息本身
        stage_mod.Stage(world.stage_plan, pen).draw(img, rect, s_age)
    elif world.signal:
        asset = assets_mod.find(world.signal)
        if asset is not None:
            age = time.time() - (world.signal_t0 or time.time())
            motion = getattr(world, "signal_motion", "sway")
            text = getattr(world, "signal_text", "")
            assets_mod.Signal(asset, pen, motion, text=text).draw_onto(img, rect, age)
    _chrome(img, world, pen, meta or {})
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
    return img, stats
