"""AI 画师：一句话需求 → 分镜单 DSL → 渲染 → 视觉评审 → 带批评迭代 → 存进配方库。

- 画师只写数据（分镜单 JSON），引擎负责渲；AI 不碰代码、不画像素。
- 每轮画完把截图交给视觉模型当评委：像不像、差在哪、下一步改什么。
- 达标（或轮数用尽）后成品存 assets/recipes/，供导演复演。
"""
from __future__ import annotations

import base64
import io
import json
import re
import time

from . import tools
from .config import ROOT, load_env
from .llm import LLM

RECIPES = ROOT / "assets" / "recipes"

_SYS = (
    "你是这个世界的分镜画师：把一句需求画成能实时演出的「分镜单」JSON。"
    "你只写数据，引擎会把它渲成会动的字符画屏幕。\n"
    "零件（parts 数组放 1~4 个；坐标不用管，系统自动排版）：\n"
    "- typewriter 打字机 {text,cps,size}；counter 计数 {label,from,to,fmt,dur}；"
    "chart 曲线 {label,shape:rise/fall/wave/pulse/steps}；progress 进度 {label,dur}；"
    "particles 粒子 {style:star/snow/ash/rain/firefly,density}；bigtext 大字 {text,size}；"
    "lograin 日志瀑布 {style:matrix/log,text}；silhouette 文字剪影 "
    "{shape:heart/star/moon/cat/whale/tree,text}；figure 小人 "
    "{pose:stand/walk/run/sit/dance/wave/jump}；emerge 素材显影 {asset,motion}\n"
    "- model3d 三维场面 {solids:[...], camera:[...], grid:true}\n"
    '  盒子 {kind:"box", lo:[x,y,z], hi:[x,y,z], roof:"gable"/"pyramid", roof_h:数字, '
    'spire:true}；折线 {kind:"poly", pts:[[x,y,z],...], closed:true}。'
    "y 朝上、地面 y=0，单位≈1 格；盒子总量 ≤ 40。先摆主体（最大体块居中），再两翼对称陪衬；"
    "屋顶 gable（人字坡）或 pyramid（四面坡），高塔加 spire。\n"
    "  camera 关键帧 [{t:秒, yaw:角度, pitch:俯仰, dist:距离, fov:视角, target:[x,y,z]}]："
    "给 2~4 个（0 秒起手远、末帧稍推近），dist 约为场景尺寸的 1.6~2.6 倍，pitch 8~20。\n"
    "  默认已开：墙面明暗填充（shade）和楼体亮窗（windows）——墙是实的、夜里有暖窗光；"
    "线型 line 可换 auto/dots/box，填充样式 shade_ramp 可换 block/dots（单盒可写 "
    "shade:false / windows:false 关掉）。\n"
    "画面要一眼认出是什么：轮廓清晰、有层次（主体 / 陪衬 / 地面），别贪多。"
    "零件和实体的字段名是 kind；三维盒子总量 ≤ 32，宁可少而准。\n"
    '只输出 JSON：{"title":"≤6字","parts":[...]}，不要任何多余文字。'
)

_REV = ("这是你要改的分镜单：\n%s\n\n评审意见：\n%s\n\n"
        "请输出修改后的完整 JSON（好用的部分保留，按要求改）。")


def _extract_json(text: str):
    t = str(text or "").strip().replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def validate(obj):
    """分镜单过一遍 coerce 清洗；返回 (plan, err)。plan 形状和 world.apply 一致。"""
    ok, args, err = tools.coerce("stage", obj if isinstance(obj, dict) else {})
    if not ok:
        return None, err
    return {"title": args.get("title") or "", "parts": args.get("parts") or [],
            "scenes": args.get("scenes") or []}, None


def _ask(llm, brief, prev=None, feedback=None) -> str:
    user = "需求：%s。直接输出 JSON。" % brief
    if prev is not None and feedback:
        user = "需求：%s\n\n" % brief + _REV % (json.dumps(prev, ensure_ascii=False), feedback)
    msg = llm.chat([{"role": "system", "content": _SYS},
                    {"role": "user", "content": user}],
                   temperature=0.4, max_tokens=8000)
    return str(msg.get("content") or "")


def _spans(plan) -> float:
    from . import stage as stage_mod
    pool = list(plan.get("parts") or [])
    for sc in plan.get("scenes") or []:
        pool += list(sc.get("parts") or [])
    return max([stage_mod._span(q) for q in pool] or [5.0])


def render_tiles(plan, times=None, size=(880, 720), seed=7):
    """把分镜单渲成几帧图（屏幕实况）。返回 (tiles, times)。"""
    from .scene import render
    from .world import World
    tmax = _spans(plan)
    times = list(times or [max(0.6, tmax * 0.25), tmax * 0.6, max(1.2, tmax * 0.95)])
    world = World(seed=seed)
    world.stage_plan = plan
    world.stage_title = str(plan.get("title") or "")
    tiles = []
    for t in times:
        world.stage_t0 = time.time() - t
        img, _ = render(world, meta={"title": "AI 画师 · t=%.1fs" % t},
                        W=size[0], H=size[1])
        tiles.append(img)
    return tiles, times


def _sheet(tiles):
    from PIL import Image
    W, H = tiles[0].size
    cols = min(2, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols + 8 * (cols + 1), H * rows + 8 * (rows + 1)),
                      (28, 28, 32))
    for i, im in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(im, (8 + c * (W + 8), 8 + r * (H + 8)))
    return sheet


_VIS_PASS = ("达标", "通过", "可以了", "已经很好", "没问题", "足够了")


def critique(tiles, brief: str) -> str:
    """视觉评审：像不像、差在哪、下一步改什么。失败返回空串（不阻塞，但视为没过）。"""
    from . import vision as vision_mod
    try:
        imgs = []
        for im in tiles[:2]:
            im2 = im.copy()
            im2.thumbnail((640, 640))
            buf = io.BytesIO()
            im2.convert("RGB").save(buf, "JPEG", quality=82)
            imgs.append(base64.b64encode(buf.getvalue()).decode())
        ask = ("这两帧是同一段动画（CRT 显示器上的字符画）。需求：「%s」。\n"
               "严格按下面格式回答，不复述任务、不写草稿：\n"
               "第 1 行：达标 或 不达标\n"
               "之后最多 3 行，每行一条具体修改建议（面向分镜单 JSON：加零件 / "
               "改形状参数 / 调镜头），短句。" % brief)
        content = [{"type": "text", "text": ask}]
        for b in imgs:
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + b}})
        sys_msg = {"role": "system",
                   "content": "你是苛刻但务实的动画评审：只判断像不像、指出最该改的地方，"
                              "绝不复述任务说明。"}
        cfg = load_env()
        base = cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        model = cfg.get("WB_VISION_MODEL") or "deepseek-v4-flash-vision-exp"
        payload = vision_mod._post_chat(
            base, {"model": model, "messages": [sys_msg, {"role": "user", "content": content}],
                   "max_tokens": 700, "temperature": 0.2})
        msg = (payload.get("choices") or [{}])[0].get("message") or {}
        return str(msg.get("content") or msg.get("reasoning_content") or "").strip()[:800]
    except Exception:
        return ""


def _passed(text: str) -> bool:
    t = str(text or "")
    lines = [x.strip() for x in t.strip().splitlines() if x.strip()]
    if not lines:
        return False
    first = lines[0]
    if "不" in first or "未" in first:
        return False
    return any(w in first for w in _VIS_PASS)


def compose(brief: str, rounds: int = 3, llm=None, size=(880, 720), seed=7) -> dict:
    """完整闭环：写 DSL → 渲 → 评 → 带批评改（≤rounds 轮）→ 存档。"""
    brief = str(brief or "").strip()[:200]
    if not brief:
        return {"ok": False, "error": "compose 需要 brief"}
    cfg = load_env()
    if llm is None:
        llm = LLM(cfg.get("DEEPSEEK_API_KEY", ""),
                  cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                  cfg.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    log, plan, feedback, tiles, crit, used = [], None, None, None, "", 0
    for r in range(1, max(1, int(rounds)) + 1):
        used = r
        try:
            raw = _ask(llm, brief, plan, feedback)
        except Exception as e:
            log.append({"round": r, "error": "调用失败：%s" % e})
            break
        cand = _extract_json(raw)
        if cand is None and getattr(llm, "last_finish", "") == "length":
            feedback = ("上一次输出被截断（草稿太长了）：想清楚后直接给最终 JSON，"
                        "压缩规模（三维盒子 ≤ 24 个、零件 ≤ 3 个）。")
            log.append({"round": r, "error": "输出被截断"})
            continue
        new_plan, err = (None, "输出不是合法 JSON") if cand is None else validate(cand)
        if new_plan is None:
            feedback = "上一次输出不合格：%s。只输出 JSON。" % err
            log.append({"round": r, "error": err})
            continue
        try:
            tiles, times = render_tiles(new_plan, size=size, seed=seed)
        except Exception as e:
            feedback = "渲染失败了：%s。坐标参数改稳妥些。" % e
            log.append({"round": r, "error": "渲染失败：%s" % e})
            plan = new_plan
            continue
        crit = critique([tiles[len(tiles) // 2], tiles[-1]], brief)
        log.append({"round": r, "plan": new_plan, "critique": crit, "times": times})
        plan = new_plan
        if _passed(crit):
            break
        feedback = crit or "评审没有通过，请自己复查并改进画面辨识度。"
    if plan is None:
        return {"ok": False, "error": "画师没能交出合法分镜单", "log": log}
    RECIPES.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", brief)[:28] or "paint"
    try:
        if tiles:
            _sheet(tiles).save(RECIPES / (slug + ".png"))
    except Exception:
        pass
    meta = {"brief": brief, "plan": plan, "critique": crit, "model": llm.model,
            "rounds": used, "at": time.strftime("%Y-%m-%d %H:%M")}
    (RECIPES / (slug + ".json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf8")
    return {"ok": True, "plan": plan, "critique": crit, "rounds": used,
            "preview": str(RECIPES / (slug + ".png")),
            "recipe": str(RECIPES / (slug + ".json")), "log": log}


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python -m core.painter 「画什么」 [--rounds 3]")
        return 1
    rounds, parts = 3, []
    i = 0
    while i < len(argv):
        if argv[i] == "--rounds":
            rounds = int(argv[i + 1])
            i += 2
            continue
        parts.append(argv[i])
        i += 1
    r = compose(" ".join(parts), rounds=rounds)
    for entry in r.get("log", []):
        print("[轮 %d] %s" % (entry.get("round"), entry.get("critique") or entry.get("error")))
    if not r.get("ok"):
        print("失败：", r.get("error"))
        return 2
    print("OK  标题=%s  轮数=%d  评审=%s" % (r["plan"].get("title"), r["rounds"],
                                             (r["critique"] or "")[:80]))
    print("对照图：", r["preview"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
