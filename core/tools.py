"""工具表：声明式状态变更。LLM 只做选择，不给坐标、不画像素。"""
from __future__ import annotations

PALETTES = ("amber", "phosphor", "deepsea")
WEATHERS = ("clear", "fog", "rain", "storm", "snow", "candlelight", "none")
STAGE_KINDS = ("typewriter", "counter", "chart", "progress", "particles", "emerge",
               "bigtext", "lograin", "silhouette", "figure", "model3d")
STAGE_POSES = ("stand", "walk", "run", "sit", "dance", "wave", "jump")
STAGE_SHAPES = ("rise", "fall", "wave", "pulse", "steps",
                "heart", "star", "moon", "cat", "whale", "tree")
STAGE_STYLES = ("star", "snow", "ash", "rain", "firefly", "cols", "rows", "diag",
                "matrix", "log")

_REASON = {"type": "string", "description": "一句话说明为什么（会显示在仪表层）"}

_PART_PROPS = {
    "kind": {"type": "string", "enum": list(STAGE_KINDS),
             "description": "typewriter 打字机 / counter 计数 / chart 曲线 / progress 进度条 / "
                            "particles 粒子 / emerge 素材显影 / bigtext 大字点阵揭示 / "
                             "lograin 日志瀑布 / silhouette 文字剪影 / figure 人物动作 / "
                             "model3d 3D 场面（线框城堡、城市、塔）"},
    "x": {"type": "number", "description": "横向位置 0~1"},
    "y": {"type": "number", "description": "纵向位置 0~1"},
    "text": {"type": "string",
             "description": "typewriter 写的字 / bigtext 那个大字 / silhouette 用来填的重复文字 / "
                            "lograin 的字符集或日志行（多行用 \\n）"},
    "cps": {"type": "number", "description": "typewriter 打字速度，字/秒，默认 9"},
    "label": {"type": "string", "description": "counter / chart / progress 的小标题"},
    "from": {"type": "number", "description": "counter 起始值"},
    "to": {"type": "number", "description": "counter 结束值"},
    "fmt": {"type": "string", "description": "counter 数字格式，如 {:.2f}，也可带前缀文字"},
    "dur": {"type": "number", "description": "演多久（秒），默认 4~5.5；bigtext 默认 3.2"},
    "loop": {"type": "boolean", "description": "counter / progress 循环重演"},
    "shape": {"type": "string", "enum": list(STAGE_SHAPES),
              "description": "chart 的形状（rise/fall/wave/pulse/steps）或 "
                             "silhouette 的剪影（heart/star/moon/cat/whale/tree）"},
    "style": {"type": "string", "enum": list(STAGE_STYLES),
              "description": "particles 种类（star/snow/ash/rain/firefly）/ "
                             "lograin 走法（matrix 字符坠落、log 日志滚动）/ "
                             "bigtext 揭示顺序（cols/rows/diag）"},
    "pose": {"type": "string", "enum": list(STAGE_POSES),
             "description": "figure 的动作：stand 站 / walk 走 / run 跑 / sit 坐 / "
                            "dance 舞 / wave 挥手 / jump 跳"},
    "speed": {"type": "number", "description": "figure / silhouette / lograin 的速度倍率，默认 1"},
    "flip": {"type": "boolean", "description": "figure 转身面向左边"},
    "density": {"type": "number", "description": "particles 密度，默认 46"},
    "asset": {"type": "string", "description": "emerge 用哪张素材；silhouette 可指定素材当模板"},
    "motion": {"type": "string", "description": "emerge 的动作，同 show 的 motion"},
    "w": {"type": "number",
          "description": "占屏宽 0~1（chart / progress / emerge / bigtext / silhouette 用）"},
    "h": {"type": "number",
          "description": "占屏高 0~1（chart / emerge / bigtext / silhouette / figure 用）"},
    "size": {"type": "number",
             "description": "字号（typewriter 默认 15，counter 默认 34）；"
                            "bigtext / silhouette 是点阵格子像素（默认 10 / 9）"},
    "solids": {"type": "array", "description": "model3d 的实体（最多 40 个）。"
               "盒子：{kind:box, lo:[x,y,z], hi:[x,y,z], roof:gable/pyramid 屋顶, roof_h, "
               "spire:true 尖塔, lv:线条亮度}；折线：{kind:poly, pts:[[x,y,z],...], closed:true}。"
               "y 轴朝上，地面 y=0。"},
    "camera": {"type": "array", "description": "model3d 相机关键帧：[{t:秒, yaw:水平角, pitch:俯仰, "
               "dist:距离, fov:视场角, target:[x,y,z]}]，2~8 个自动补间；不写就自动取景。"},
    "grid": {"type": "boolean", "description": "model3d 地面网格，默认 true"},
    "fog": {"type": "array", "description": "model3d 雾：[近,远,最远暗度]，默认 [14,70,0.07]"},
    "line": {"type": "string", "enum": ["auto", "dots", "box", "bold"],
             "description": "model3d 线条风格：auto（默认，横平竖直实线、斜线点阵）/ dots 全点阵 / "
                            "box 全实线 / bold 加粗点阵"},
    "shade": {"type": "boolean", "description": "model3d 面明暗填充（墙变实体），默认 true"},
    "shade_ramp": {"type": "string", "enum": ["block", "dots"],
                   "description": "model3d 填充样式：block（░▒▓█ 砖石感，默认）/ dots（盲文点阵）"},
    "windows": {"type": "boolean",
                "description": "model3d 给塔楼/楼房点窗（亮点暖色，夜景很出效果），默认 true；"
                               "单个盒子可写 windows:false 关掉"},

}
_PARTS_SCHEMA = {"type": "array", "description": "1~5 个零件，没写坐标就自动从上往下排",
                 "items": {"type": "object", "properties": _PART_PROPS,
                           "required": ["kind"]}}

TOOLS = [
    {"type": "function", "function": {
        "name": "set_mood",
        "description": "设置世界的气氛：色调、能量、天气。随时可改。",
        "parameters": {"type": "object", "properties": {
            "palette": {"type": "string", "enum": list(PALETTES)},
            "energy": {"type": "number", "description": "0~1，世界活跃度"},
            "weather": {"type": "string", "enum": list(WEATHERS)},
            "reason": _REASON,
        }}}},
    {"type": "function", "function": {
        "name": "focus",
        "description": "把镜头对准某个概念（推近或拉远）。",
        "parameters": {"type": "object", "properties": {
            "concept": {"type": "string"},
            "zoom": {"type": "number", "description": "1=全景，>1 推近，最大 4"},
            "reason": _REASON,
        }, "required": ["concept"]}}},
    {"type": "function", "function": {
        "name": "beat",
        "description": "给世界一次脉冲（强调、惊吓、心跳）。",
        "parameters": {"type": "object", "properties": {
            "intensity": {"type": "number"},
            "reason": _REASON,
        }}}},
    {"type": "function", "function": {
        "name": "show",
        "description": "把一张素材（用真实参考图描出来的字符画）切到窗口上，像给显示器换一路信号。"
                       "只在聊到素材库里的东西时才用；素材名见系统提示。可用 motion 决定它怎么动。",
        "parameters": {"type": "object", "properties": {
            "asset": {"type": "string", "description": "素材名（id、中文名或别名）"},
            "motion": {"type": "string",
                       "enum": ["sway", "breathe", "emerge", "glitch", "rain", "push", "text"],
                       "description": "上台动作：sway 摇曳（默认）/ breathe 呼吸（安静的近景）/ "
                                      "emerge 慢慢浮现 / glitch 故障闪烁 / rain 雨幕 / push 缓缓推近（想看清细节）/ "
                                      "text 文字剪影（剪影内部填一段流动的字，整片表面持续闪变，配 text 参数用）"},
            "text": {"type": "string",
                     "description": "仅 motion=text 时用：剪影里流动的那段字，聊到什么就流什么"
                                    "（角色名、一句关键词；不填用默认）"},
            "reason": _REASON,
        }, "required": ["asset"]}}},
    {"type": "function", "function": {
        "name": "capture",
        "description": "素材库里没有、但值得一看的东西出现时用：系统会去本地图库找参考图，"
                       "描一张新素材（约 10~30 秒，描好后自动上屏；期间可以先聊着）。"
                       "query 用具体名词（角色、地点、物件），虚的意象别用这个。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要找/描的东西，如「霍格沃茨」「葬送的芙莉莲」"},
            "motion": {"type": "string",
                       "enum": ["sway", "breathe", "emerge", "glitch", "rain", "push", "text"],
                       "description": "描好后上屏的动作，同 show"},
            "text": {"type": "string", "description": "同 show 的 text（仅 motion=text 时用）"},
            "fresh": {"type": "boolean",
                      "description": "用户要「再来一张/换一张/看看其它的」时传 true："
                                     "即使库里已有同类素材，也要去描一张不一样的"
                                     "（query 最好换个角度，如加场景/服装/动作词）"},
            "reason": _REASON,
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "hide",
        "description": "关掉素材信号，窗口回到世界本身。",
        "parameters": {"type": "object", "properties": {"reason": _REASON}}}},
    {"type": "function", "function": {
        "name": "compose",
        "description": "让系统里的 AI 画师从零创作一段新分镜（约 1~3 分钟，后台画、画好自动上屏）。"
                       "只在素材库和现有零件都演不出来、又真的值得一看的大场面上用，"
                       "比如「夜色中的霍格沃茨城堡」这种需要立体轮廓和镜头运动的画面；平常聊天别用。"
                       "brief 要具体：画什么（建筑/场景/角色轮廓）+ 氛围 + 视角。",
        "parameters": {"type": "object", "properties": {
            "brief": {"type": "string",
                      "description": "一两句话，如「夜色中的霍格沃茨城堡，尖塔成群，近景湖面」"},
            "reason": _REASON,
        }, "required": ["brief"]}}},
    {"type": "function", "function": {
        "name": "stage",
        "description": "让窗口当场演一段：屏幕切成分镜，零件自己动起来——打字机逐字写、"
                       "计数器往上滚、曲线一段段长出来、进度条推进、粒子在飘、素材从噪点里显影、"
                       "大字点阵一笔笔填出来、日志瀑布往下刷、文字剪影在闪变、小人在走/跑/坐/跳舞。"
                       "聊到过程、数据、气氛、正在发生的事（在跑、在等、在流逝、雨夜、登场）时用。"
                       "想看立体的大场面（城堡、城市天际线、塔楼群）就用 model3d 零件："
                       "给 solids（盒子+屋顶+尖塔）和 camera 关键帧，引擎会把 3D 线框渲出来；"
                       "只有规整的体块才值得用它，人和自然景物别硬塞。"
                       "想连演几幕（硬切）：用 scenes 代替 parts——每幕各带自己的标题和零件，切得干脆。"
                       "屏幕归它独占（和 show 二选一），刚放过素材、或只是闲聊，就别用。",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "屏幕左上角的标题，很短，如「训练日志」「站台」"},
            "parts": _PARTS_SCHEMA,
            "scenes": {"type": "array", "description": "2~4 幕硬切（有它就不必再给 parts）",
                       "items": {"type": "object", "properties": {
                           "title": {"type": "string", "description": "这一幕左上角的标题"},
                           "dur": {"type": "number",
                                   "description": "这一幕演多久（秒），默认取最长零件的时长"},
                           "parts": _PARTS_SCHEMA,
                       }, "required": ["parts"]}},
            "reason": _REASON,
        }}}},
]


def _f(v, lo, hi, dflt):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return dflt


def coerce(name: str, args: dict) -> tuple:
    """把模型给的参数收拾干净：坏值降级而不是崩溃。返回 (ok, args, error)。"""
    a = dict(args or {})
    if name == "set_mood":
        out = {"reason": str(a.get("reason", ""))[:120]}
        if "palette" in a:
            out["palette"] = a["palette"] if a["palette"] in PALETTES else None
        if "energy" in a:
            out["energy"] = _f(a.get("energy"), 0.0, 1.0, None)
        if "weather" in a:
            w = str(a.get("weather", "")).lower()
            out["weather"] = w if w in WEATHERS else "none"
        return True, out, None
    if name == "focus":
        concept = str(a.get("concept", "")).strip()[:80]
        if not concept:
            return False, {}, "focus 需要 concept"
        return True, {"concept": concept, "zoom": _f(a.get("zoom"), 0.5, 4.0, 1.0),
                      "reason": str(a.get("reason", ""))[:120]}, None
    if name == "beat":
        return True, {"intensity": _f(a.get("intensity"), 0.0, 1.0, 0.5),
                      "reason": str(a.get("reason", ""))[:120]}, None
    if name == "show":
        asset = str(a.get("asset", "")).strip()[:64]
        if not asset:
            return False, {}, "show 需要 asset"
        return True, {"asset": asset, "motion": str(a.get("motion", "")).strip()[:16],
                      "text": str(a.get("text", "")).strip()[:64],
                      "reason": str(a.get("reason", ""))[:120]}, None
    if name == "capture":
        query = str(a.get("query", "")).strip()[:60]
        if not query:
            return False, {}, "capture 需要 query"
        return True, {"query": query, "motion": str(a.get("motion", "")).strip()[:16],
                      "text": str(a.get("text", "")).strip()[:64],
                      "fresh": bool(a.get("fresh")),
                      "reason": str(a.get("reason", ""))[:120]}, None
    if name == "compose":
        brief = str(a.get("brief", "")).strip()[:160]
        if not brief:
            return False, {}, "compose 需要 brief"
        return True, {"brief": brief, "reason": str(a.get("reason", ""))[:120]}, None
    if name == "stage":
        def _clean(q):
            kind = str(q.get("kind") or q.get("type") or "").strip().lower()
            if kind not in STAGE_KINDS:
                return None
            item: dict = {"kind": kind}
            for k, lo, hi in (("x", 0.0, 1.0), ("y", 0.0, 1.0), ("w", 0.05, 1.0),
                              ("h", 0.05, 1.0), ("density", 4.0, 160.0), ("size", 4.0, 64.0),
                              ("dur", 0.6, 60.0), ("cps", 1.0, 80.0), ("speed", 0.1, 8.0),
                              ("from", -1e12, 1e12), ("to", -1e12, 1e12)):
                v = _f(q.get(k), lo, hi, None)
                if v is not None:
                    item[k] = v
            if q.get("loop"):
                item["loop"] = True
            if q.get("cursor") is False:
                item["cursor"] = False
            if q.get("flip"):
                item["flip"] = True
            for k, n in (("text", 300), ("label", 32), ("asset", 64), ("fmt", 24),
                         ("shape", 12), ("style", 12), ("motion", 12), ("pose", 12),
                         ("line", 8), ("shade_ramp", 8)):
                v = str(q.get(k) or "").strip()
                if v:
                    item[k] = v[:n]
            if kind == "model3d":
                if q.get("shade") is False:
                    item["shade"] = False
                if q.get("windows") is False:
                    item["windows"] = False
                solids = []
                for s in (q.get("solids") if isinstance(q.get("solids"), list) else [])[:40]:
                    if not isinstance(s, dict):
                        continue
                    sk = str(s.get("kind") or "box").strip().lower()
                    it = {"kind": sk if sk in ("box", "poly") else "box"}
                    lv = _f(s.get("lv"), 0.15, 1.0, None)
                    if lv is not None:
                        it["lv"] = lv
                    if it["kind"] == "poly":
                        pts = []
                        for c in (s.get("pts") if isinstance(s.get("pts"), list) else [])[:64]:
                            if isinstance(c, (list, tuple)) and len(c) == 3:
                                try:
                                    pts.append([max(-1e4, min(1e4, float(c[i]))) for i in range(3)])
                                except (TypeError, ValueError):
                                    pass
                        if len(pts) < 2:
                            continue
                        it["pts"] = pts
                        if s.get("closed"):
                            it["closed"] = True
                    else:
                        lo, hi = s.get("lo"), s.get("hi")
                        if not (isinstance(lo, (list, tuple)) and isinstance(hi, (list, tuple))
                                and len(lo) == 3 and len(hi) == 3):
                            continue
                        try:
                            it["lo"] = [max(-1e4, min(1e4, float(c))) for c in lo]
                            it["hi"] = [max(-1e4, min(1e4, float(c))) for c in hi]
                        except (TypeError, ValueError):
                            continue
                        roof = str(s.get("roof") or "").strip().lower()
                        if roof in ("gable", "pyramid"):
                            it["roof"] = roof
                            rh = _f(s.get("roof_h"), 0.2, 40.0, None)
                            if rh is not None:
                                it["roof_h"] = rh
                        if s.get("spire"):
                            it["spire"] = True
                    if s.get("shade") is False:
                        it["shade"] = False
                    if s.get("windows") is False:
                        it["windows"] = False
                    solids.append(it)
                if solids:
                    item["solids"] = solids
                cam = []
                for kf in (q.get("camera") if isinstance(q.get("camera"), list) else [])[:8]:
                    if not isinstance(kf, dict):
                        continue
                    key = {"t": _f(kf.get("t"), 0.0, 300.0, 0.0)}
                    for name, lo_, hi_ in (("yaw", -720.0, 720.0), ("pitch", -85.0, 85.0),
                                           ("dist", 0.8, 400.0), ("fov", 10.0, 120.0)):
                        v = _f(kf.get(name), lo_, hi_, None)
                        if v is not None:
                            key[name] = v
                    tgt = kf.get("target")
                    if isinstance(tgt, (list, tuple)) and len(tgt) == 3:
                        try:
                            key["target"] = [max(-1e4, min(1e4, float(c))) for c in tgt]
                        except (TypeError, ValueError):
                            pass
                    cam.append(key)
                if cam:
                    item["camera"] = cam
                if q.get("grid") is False:
                    item["grid"] = False
                fog = q.get("fog")
                if isinstance(fog, (list, tuple)) and len(fog) == 3:
                    try:
                        item["fog"] = [float(c) for c in fog]
                    except (TypeError, ValueError):
                        pass
            return item

        def _clean_list(raw, cap):
            out = []
            for q in (raw if isinstance(raw, list) else [])[:cap]:
                if isinstance(q, dict):
                    it = _clean(q)
                    if it:
                        out.append(it)
            return out

        parts = _clean_list(a.get("parts"), 5)
        scenes = []
        for sc in (a.get("scenes") if isinstance(a.get("scenes"), list) else [])[:4]:
            if not isinstance(sc, dict):
                continue
            ps = _clean_list(sc.get("parts"), 5)
            if not ps:
                continue
            item2 = {"title": str(sc.get("title") or "").strip()[:24], "parts": ps}
            d = _f(sc.get("dur"), 0.8, 120.0, None)
            if d is not None:
                item2["dur"] = d
            scenes.append(item2)
        if not parts and not scenes:
            return False, {}, ("stage 需要 parts 或 scenes（至少一个零件；kind 只能是 %s）"
                               % "/".join(STAGE_KINDS))
        return True, {"title": str(a.get("title") or "").strip()[:24],
                      "parts": parts, "scenes": scenes,
                      "reason": str(a.get("reason", ""))[:120]}, None
    if name == "hide":
        return True, {"reason": str(a.get("reason", ""))[:120]}, None
    return False, {}, "未知工具：" + str(name)
