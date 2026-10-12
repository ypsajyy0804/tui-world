"""世界状态：唯一事实来源。每轮对话只做增量 patch，不重画。

屏幕只有两路内容：素材信号（show/capture）和分镜（stage），后到的那一路顶掉前一路。
代码直接画的物件（place/河/冰川那一套）已按用户要求砍掉。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import assets, tools


@dataclass
class World:
    seed: int = 7
    turn: int = 0
    palette: str = "amber"
    energy: float = 0.5
    weather: str = "clear"
    focus: dict = field(default_factory=lambda: {"concept": "", "zoom": 1.0})
    signal: str = ""
    signal_name: str = ""
    signal_t0: float = 0.0
    signal_motion: str = "sway"
    signal_text: str = ""
    stage_plan: dict = field(default_factory=dict)
    stage_title: str = ""
    stage_t0: float = 0.0

    @classmethod
    def from_dict(cls, s: dict) -> "World":
        """从一份世界快照恢复（lab/snap.py 存下来的那种）。缺字段一律补默认值。"""
        w = cls(seed=int(s.get("seed") or 7))
        w.palette = s.get("palette") or "amber"
        w.energy = float(s.get("energy") or 0.5)
        w.weather = s.get("weather") or "clear"
        focus = s.get("focus") or {}
        if focus.get("concept"):
            w.focus = {"concept": focus.get("concept") or "",
                       "zoom": float(focus.get("zoom") or 1.0)}
        sig = s.get("signal")
        if isinstance(sig, dict):
            w.signal = str(sig.get("id") or "")
            w.signal_name = str(sig.get("name") or "")
            w.signal_motion = str(sig.get("motion") or "sway")
            w.signal_text = str(sig.get("text") or "")
        else:
            w.signal = str(sig or "")
            w.signal_name = str(s.get("signal_name") or "")
        w.signal_t0 = time.time() if w.signal else 0.0
        plan = s.get("stage_plan")
        if isinstance(plan, dict) and (plan.get("parts") or plan.get("scenes")):
            w.stage_plan = {"title": str(plan.get("title") or "")}
            if plan.get("parts"):
                w.stage_plan["parts"] = list(plan.get("parts") or [])
            if plan.get("scenes"):
                w.stage_plan["scenes"] = list(plan.get("scenes") or [])
            w.stage_title = w.stage_plan["title"]
            w.stage_t0 = time.time()
        return w

    def apply(self, name: str, args: dict) -> dict:
        ok, a, err = tools.coerce(name, args)
        if not ok:
            return {"ok": False, "error": err}
        if name == "set_mood":
            if a.get("palette"):
                self.palette = a["palette"]
            if a.get("energy") is not None:
                self.energy = a["energy"]
            if a.get("weather"):
                self.weather = a["weather"]
            return {"ok": True, "mood": f"{self.palette}/{self.energy:.2f}/{self.weather}"}
        if name == "focus":
            self.focus = {"concept": a["concept"], "zoom": a["zoom"]}
            return {"ok": True, "focus": a["concept"], "zoom": a["zoom"]}
        if name == "beat":
            self.energy = min(1.0, self.energy * 0.6 + 0.4 * a["intensity"])
            return {"ok": True, "energy": round(self.energy, 2)}
        if name == "show":
            asset = assets.find(a["asset"])
            if asset is None:
                return {"ok": False, "error": "素材库里没有「%s」" % a["asset"],
                        "have": sorted(assets.load_all().keys())}
            self.signal = asset.id
            self.signal_name = asset.name
            self.signal_motion = str(a.get("motion") or "sway")
            self.signal_text = str(a.get("text") or "")
            self.signal_t0 = time.time()
            self.stage_plan = {}
            self.stage_title = ""
            return {"ok": True, "signal": asset.id, "name": asset.name}
        if name == "stage":
            plan = {"title": a.get("title") or ""}
            if a.get("parts"):
                plan["parts"] = list(a["parts"])
            if a.get("scenes"):
                plan["scenes"] = list(a["scenes"])
            self.stage_plan = plan
            self.stage_title = plan["title"]
            self.stage_t0 = time.time()
            self.signal = ""
            self.signal_name = ""
            self.signal_text = ""
            n = (sum(len(sc.get("parts") or []) for sc in plan["scenes"])
                 if plan.get("scenes") else len(plan.get("parts") or []))
            return {"ok": True, "stage": self.stage_title or "分镜",
                    "parts": n, "scenes": len(plan.get("scenes") or [])}
        if name == "hide":
            self.signal = ""
            self.signal_name = ""
            self.signal_text = ""
            self.stage_plan = {}
            self.stage_title = ""
            return {"ok": True, "signal": ""}
        return {"ok": False, "error": "unreachable"}

    def snapshot(self) -> str:
        """给模型的「当前世界」摘要——它看的是状态，不是历史。"""
        if self.signal:
            screen = "素材《%s》" % (self.signal_name or self.signal)
            if self.signal_motion and self.signal_motion != "sway":
                screen += "（%s）" % self.signal_motion
        elif self.stage_plan:
            n = len(self.stage_plan.get("parts") or [])
            if self.stage_plan.get("scenes"):
                n = sum(len(sc.get("parts") or []) for sc in self.stage_plan["scenes"])
            screen = "分镜《%s》(%d 个零件)" % (self.stage_title or "?", n)
        else:
            screen = "(空)"
        return "\n".join([
            "mood=%s/%.2f/%s  focus=%s(zoom %.1f)" % (
                self.palette, self.energy, self.weather,
                self.focus["concept"] or "-", self.focus["zoom"]),
            "屏幕=" + screen,
        ])
