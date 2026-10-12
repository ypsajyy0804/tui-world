"""本地 Web 应用（M1）：左边对话，右边世界，随对话实时更新。

    python -m core.app --open
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import stage as stage_mod
from . import workbench
from .config import ROOT, load_env
from .director import Director
from .llm import LLM
from .scene import render
from .world import World

WEB = Path(__file__).resolve().parent / "web"

MAX_FRAME_AREA = 1600000   # 一帧最多约 160 万像素：越大越慢，按面积封顶
BUILD = time.strftime("%Y%m%d-%H%M%S")   # 进程启动标记：网页发现它变了就自动刷新


def _fit_view(w, h) -> tuple:
    """把网页报来的显示区尺寸收拾成一个合理的出图尺寸（保比例、封顶）。"""
    try:
        w, h = int(float(w)), int(float(h))
    except (TypeError, ValueError):
        return 880, 720
    w = max(360, min(2200, w))
    h = max(260, min(1500, h))
    area = w * h
    if area > MAX_FRAME_AREA:
        k = (MAX_FRAME_AREA / area) ** 0.5
        w, h = int(w * k), int(h * k)
    return w, h


class Session:
    """单用户会话：世界 + 帧缓存 + 一步一轮的导演。"""

    def __init__(self, cfg: dict, model: str, seed: int, load: str | None = None):
        self.model = model
        self.world = World(seed=seed)
        if load:
            try:
                self.world = World.from_dict(
                    json.loads(Path(load).read_text(encoding="utf8")))
            except Exception as e:
                print("载入世界失败（按空世界继续）：%s" % e)
        self.version = 0
        self.status = "idle"
        self.size = (880, 720)          # 出图尺寸：跟着右栏的显示区走
        self.messages: list = []
        self.stats: dict = {}
        self.meta = {"title": "world", "model": model, "tokens": 0,
                     "seconds": 0, "seed": seed}
        self.frame_ms = 0.0
        self.director = None
        key = cfg.get("DEEPSEEK_API_KEY")
        if key:
            llm = LLM(key, cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"), model)
            self.director = Director(llm, self.world, capture=self._capture,
                                     compose=self._compose)
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.last_state = 0.0
        self.rerender()
        threading.Thread(target=self._animate, daemon=True).start()

    def refresh_assets(self):
        """工作台入库后：重扫素材 + 重建导演的系统提示词。"""
        from . import assets as assets_mod
        assets_mod.reload()
        if self.director is not None:
            self.director.refresh_catalogue()

    def _capture(self, args: dict) -> dict:
        """导演点单「去描一张」：库里已有且没点名要新的就直接上屏，否则后台取材（异步上屏）。"""
        from . import assets as assets_mod
        q = str(args.get("query") or "").strip()
        motion = str(args.get("motion") or "sway")
        text = str(args.get("text") or "")
        fresh = bool(args.get("fresh"))
        if not q:
            return {"ok": False, "error": "capture 需要 query"}
        hits = assets_mod.search(q, limit=5)
        if hits and not fresh:
            self.world.apply("show", {"asset": hits[0]["id"], "motion": motion, "text": text})
            return {"ok": True, "status": "库里已有「%s」，直接切上屏；要描一张不一样的传 fresh=true"
                                          % hits[0]["name"], "asset": hits[0]["id"]}
        if getattr(self, "_capturing", False):
            return {"ok": False, "error": "上一单取材还在路上，先别急"}
        avoid = set()
        if fresh:
            all_ = assets_mod.load_all()
            for h in hits:
                a = all_.get(h["id"])
                fp = getattr(a, "src_fp", "") if a is not None else ""
                if fp:
                    avoid.add(fp)
        self._capturing = True
        threading.Thread(target=self._capture_worker, args=(q, motion, text, avoid),
                         daemon=True).start()
        return {"ok": True, "status": "正在去描新的一张，约半分钟；描好会自动上屏，先继续聊"}

    def _capture_worker(self, query: str, motion: str, text: str = "", avoid=None):
        from . import assets as assets_mod
        try:
            from . import take
            r = take.make_asset(query, avoid=frozenset(avoid or ()))
            if not r.get("ok"):
                self.messages.append({"role": "system", "text": "取材失败：%s" % r.get("error")})
                return
            assets_mod.reload()
            self.world.apply("show", {"asset": r["id"], "motion": motion, "text": text})
            self.messages.append({"role": "system", "text": "取材完成：%s · %s · 已上屏"
                                  % (r.get("name"), r.get("note") or "")})
        except Exception as e:
            self.messages.append({"role": "system", "text": "取材异常：%s" % e})
        finally:
            self._capturing = False

    def _compose(self, args: dict) -> dict:
        """导演点单「画师出稿」：后台跑画家闭环，画好自动上屏。"""
        brief = str(args.get("brief") or "").strip()
        if not brief:
            return {"ok": False, "error": "compose 需要 brief"}
        if getattr(self, "_composing", False):
            return {"ok": False, "error": "画师上一单还在画，先别急"}
        self._composing = True
        threading.Thread(target=self._compose_worker, args=(brief,), daemon=True).start()
        return {"ok": True, "status": "画师开工了：写分镜→渲染→自评→改，约 1~3 分钟；"
                                      "画好自动上屏，先继续聊"}

    def _compose_worker(self, brief: str):
        try:
            from . import painter
            r = painter.compose(brief, rounds=3, size=self.size)
            if not r.get("ok"):
                self.messages.append({"role": "system",
                                      "text": "画师没画成：%s" % r.get("error")})
                return
            self.world.apply("stage", r["plan"])
            crit = (r.get("critique") or "评审缺席（超时），按画师自稿上屏").replace("\n", " ")[:100]
            self.messages.append({"role": "system",
                                  "text": "画师交稿《%s》（%d 轮）：%s"
                                          % (r["plan"].get("title") or "?", r.get("rounds"), crit)})
        except Exception as e:
            self.messages.append({"role": "system", "text": "画师异常：%s" % e})
        finally:
            self._composing = False

    def _animate(self):
        """屏幕上有东西在动、且有人在看（最近 6 秒轮询过 /state）时才提帧率。"""
        while True:
            time.sleep(0.09)
            if (not self._alive() or self.status != "idle"
                    or time.time() - self.last_state > 6):
                continue
            try:
                self.rerender()
            except Exception:
                time.sleep(0.5)

    def _alive(self) -> bool:
        """屏幕上还有东西在动吗：素材信号，或还没演完的分镜。"""
        if self.world.signal:
            return True
        if not self.world.stage_plan:
            return False
        t = time.time() - (self.world.stage_t0 or time.time())
        return stage_mod.busy(self.world.stage_plan, t)

    def rerender(self):
        with self.render_lock:
            self._rerender()

    def _rerender(self):
        t0 = time.time()
        self.version += 1
        keep = ROOT / "out" / "frames"
        out = keep / ("frame_%04d.png" % self.version)
        meta = dict(self.meta)
        meta["mark"] = self._mark()
        img, stats = render(self.world, out, meta, W=self.size[0], H=self.size[1])
        t1 = time.time()
        self.stats = stats
        self.png = out.read_bytes()
        t2 = time.time()
        stale = keep / ("frame_%04d.png" % (self.version - 40))
        if stale.exists():
            stale.unlink()
        self.frame_ms = round((time.time() - t0) * 1000, 1)

    def set_size(self, w, h):
        """网页把右栏显示区的尺寸报过来：铺满它，不留黑边。"""
        w, h = _fit_view(w, h)
        if (w, h) == self.size:
            return
        self.size = (w, h)
        self.rerender()

    def _mark(self) -> str:
        """画面底部那行水印：模型 / tokens / 用时 / 版本 / 状态。"""
        m = self.meta
        return "%s    %s tokens    %ss    v%d    %s" % (
            self.model, m.get("tokens") or 0, m.get("seconds") or 0, self.version,
            "状态：理解中…" if self.status == "thinking" else "状态：待机")

    def say(self, text: str) -> bool:
        if not text:
            return False
        with self.lock:
            if self.status == "thinking":
                return False
            self.status = "thinking"
        self.messages.append({"role": "user", "text": text})
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return True

    def _run(self, text: str):
        t0 = time.time()
        try:
            if self.director is None:
                raise RuntimeError("缺少 DEEPSEEK_API_KEY：写进 .env 或设环境变量后重启")
            r = self.director.say(text)
            self.messages.append({
                "role": "director", "text": r["text"],
                "calls": [{"name": c["name"], "args": c["args"]} for c in r["tool_calls"]],
            })
            self.meta["tokens"] = (self.meta.get("tokens") or 0) + r["tokens"]
            self.meta["seconds"] = r["seconds"]
            self.meta["title"] = self.world.focus.get("concept") or "world"
        except Exception as e:
            self.messages.append({"role": "system", "text": "错误：%s" % e})
        finally:
            with self.lock:
                self.status = "idle"
            try:
                self.rerender()
            except Exception as e:
                self.messages.append({"role": "system", "text": "渲染失败：%s" % e})
        self.meta["last_seconds"] = round(time.time() - t0, 1)

    def state(self) -> dict:
        self.last_state = time.time()
        return {
            "version": self.version,
            "build": BUILD,
            "status": self.status,
            "model": self.model,
            "anim": self._alive(),
            "size": [self.size[0], self.size[1]],
            "frame_ms": self.frame_ms,
            "messages": self.messages,
            "world": {
                "palette": self.world.palette,
                "energy": self.world.energy, "weather": self.world.weather,
                "focus": self.world.focus,
                "signal": {"id": self.world.signal, "name": self.world.signal_name},
                "stage": self.world.stage_title if self.world.stage_plan else "",
                "stage_plan": self.world.stage_plan,
            },
            "meta": self.meta,
        }


class Handler(BaseHTTPRequestHandler):
    session: Session = None

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        r = workbench.dispatch(p, "GET", parse_qs(u.query))
        if r:
            code, ctype, body = r
            self._send(code, body, ctype)
            return
        if p in ("/", "/index.html"):
            self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif p == "/state":
            body = json.dumps(self.session.state(), ensure_ascii=False).encode("utf8")
            self._send(200, body, "application/json; charset=utf-8")
        elif p == "/frame":
            q = parse_qs(u.query)
            try:
                w = int(float(q.get("w", ["0"])[0]))
                h = int(float(q.get("h", ["0"])[0]))
            except ValueError:
                w = h = 0
            if w > 0 and h > 0:
                self.session.set_size(w, h)
            self._send(200, self.session.png, "image/png")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode("utf8") or "{}")
        except json.JSONDecodeError:
            data = {}
        r = workbench.dispatch(p, "POST", parse_qs(u.query), data,
                               on_saved=self.session.refresh_assets)
        if r:
            code, ctype, body = r
            self._send(code, body, ctype)
            return
        if p != "/say":
            self._send(404, b"not found", "text/plain")
            return
        ok = self.session.say(str(data.get("text", "")).strip())
        self._send(200 if ok else 409,
                   json.dumps({"ok": ok}, ensure_ascii=False).encode("utf8"),
                   "application/json; charset=utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="core.app", description="tui-world 本地界面")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--load", default=None,
                    help="从一个世界快照 JSON 继续（lab/snap.py 存下来的那种）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    a = ap.parse_args(argv)

    cfg = load_env()
    model = a.model or cfg.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    Handler.session = Session(cfg, model, a.seed, a.load)
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError as e:
        print("端口 %d 已被占用——多半是上一次没关掉的实例还在跑。\n"
              "要么先关掉它，要么换一个端口：--port %d\n%s" % (a.port, a.port + 1, e))
        return 1
    url = "http://127.0.0.1:%d/" % a.port
    print("tui-world 已启动：%s  (pid %d)" % (url, os.getpid()))
    print("素材工作台：%swb" % url)
    print("模型：%s（Ctrl+C 停止）" % model)
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
