"""取材：一句话 → 从本地图源找参考图 → 自动取景 → 描摹入库。

来源优先级：Pixiv 图库内容索引（lab/index_pixiv.py 生成）→ 漫画库（系列名匹配，
逐页按可描性挑一页）→ 网搜兜底（Bing 图搜，core/webfetch.py）。产出走工作台
同一条管线，质量与手工入库一致。

每个来源产出时都会记录"来源指纹"（src_fp）。用户说"再来一张"时传 avoid
集合进来，跳开已经描过的参考图，尽量给一张不一样的。

索引结构（.tmp/wb/pixiv_index.json）：
{"files": {"<文件名>": {"name": .., "aliases": [..], "tags": [..], "desc": ..}}}
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import workbench as wb

IDX = Path(wb.CACHE) / "pixiv_index.json"


def load_index() -> dict:
    if IDX.exists():
        try:
            return json.loads(IDX.read_text(encoding="utf8"))
        except Exception:
            return {}
    return {}


def save_index(data: dict):
    IDX.parent.mkdir(parents=True, exist_ok=True)
    IDX.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")


def _fp_web(path) -> str:
    """网搜候选的指纹 = 文件内容 md5 前 12 位。"""
    return "web:" + hashlib.md5(Path(path).read_bytes()).hexdigest()[:12]


_TW2CN = {"斬": "斩", "絶": "绝", "達": "达", "後": "后", "裝": "装", "戀": "恋",
          "團": "团", "劇": "剧", "動": "动", "頻": "频", "愛": "爱", "宮": "宫",
          "學": "学", "無": "无", "轉": "转", "輝": "辉", "時": "时", "獨": "独",
          "離": "离", "夢": "梦", "劍": "剑", "傳": "传", "龍": "龙", "戰": "战",
          "靈": "灵", "麗": "丽", "蘭": "兰", "亞": "亚", "爾": "尔", "殺": "杀",
          "蓮": "莲", "寫": "写", "讀": "读", "語": "语", "話": "话", "說": "说",
          "認": "认", "識": "识", "歲": "岁", "萬": "万", "樣": "样", "產": "产",
          "業": "业", "與": "与", "為": "为", "島": "岛", "國": "国", "圍": "围",
          "塊": "块", "場": "场", "壞": "坏", "寶": "宝", "對": "对", "導": "导",
          "屆": "届", "層": "层", "嗎": "吗", "麼": "么", "紅": "红", "綠": "绿"}


def _simp(s: str) -> str:
    return "".join(_TW2CN.get(ch, ch) for ch in s)


def score_text(query: str, text: str) -> float:
    """粗略相关度：整串命中 1.0；二字窗全中 0.9；部分命中/字形覆盖 0.35~0.7。"""
    q = _simp(str(query or "").lower().strip())
    t = _simp(str(text or "").lower())
    if not q or not t:
        return 0.0
    if q in t:
        return 1.0
    if len(q) >= 2:
        grams = [q[i:i + 2] for i in range(len(q) - 1)]
        gh = sum(1 for g in grams if g in t)
        if gh == len(grams):
            return 0.9
        if gh:
            return 0.2 + 0.5 * gh / len(grams)
        chars = set(q)
        ch = sum(1 for c in chars if c in t)
        if len(chars) >= 2 and ch >= 2 and ch / len(chars) >= 0.6:
            return 0.35 + 0.3 * ch / len(chars)
    return 0.0


def find_pixiv(query: str, floor: float = 0.5, avoid=frozenset()):
    """在 pixiv 内容索引里找最相关的一张，返回 (分, 文件名, 索引项)。
    avoid 里的文件名（"pixiv:文件名"）跳过。"""
    files = (load_index().get("files") or {})
    best = None
    for fname, info in files.items():
        if ("pixiv:" + fname) in avoid:
            continue
        text = " ".join([str(info.get("name") or ""), str(info.get("desc") or "")]
                        + [str(x) for x in (info.get("tags") or [])]
                        + [str(x) for x in (info.get("aliases") or [])])
        sc = score_text(query, text)
        if sc >= floor and (best is None or sc > best[0]):
            best = (sc, fname, info)
    return best


def find_manga(query: str, floor: float = 0.5):
    best = None
    for name in wb.list_manga():
        sc = score_text(query, name)
        if sc >= floor and (best is None or sc > best[0]):
            best = (sc, name)
    return best


def find_web(query: str, budget: int = 10, avoid=frozenset()):
    """网搜取材：搜图 → 下载候选 → 视觉模型挑最适合描的一张（回退可描性评分）。
    返回 (可描性分, 本地路径, 挑选说明)。"""
    from PIL import Image
    from . import vision, webfetch
    try:
        cands = webfetch.fetch_candidates(query, budget=budget, avoid=avoid)
    except Exception:
        return None
    scores = {}
    for p in cands:
        try:
            scores[p] = wb.sketch_score(Image.open(p).convert("RGB"))["score"]
        except Exception:
            pass
    cands = [p for p in cands if p in scores]
    if not cands:
        return None
    r = vision.pick(query, cands)
    idx = r.get("index") if isinstance(r, dict) else None
    if isinstance(idx, int) and 0 <= idx < len(cands):
        p = cands[idx]
        return (scores[p], p, "视觉挑选：%s" % (r.get("why") or ""))
    p = max(cands, key=lambda x: scores[x])
    return (scores[p], p, "按可描性评分挑（视觉挑选不可用）")


def pick_page(series: str, chapter: str, budget: int = 10, top: int = 3):
    """在该章节里按可描性挑最像"主体特写"的页（扫前 budget 页 + 均匀采样），
    返回按分排序的前 top 名 [(分, 页码), ...]。"""
    names = wb.chapter_pages(series, chapter)
    n = len(names)
    if not n:
        return []
    picks = list(range(min(n, budget)))
    if n > budget:
        step = max(1, n // 6)
        picks += [i for i in range(budget, n, step)][:6]
    scored = []
    for i in picks:
        try:
            sc = wb.sketch_score(wb.page_image(series, chapter, i))["score"]
        except Exception:
            continue
        scored.append((sc, i))
    scored.sort(key=lambda x: -x[0])
    return scored[:top]


def _pick_page_fresh(series: str, chapters: list, avoid):
    """挑一页没描过的；前两章没有就再往后翻几章。返回 (分, 章节, 页码, 指纹)。"""
    best = None
    for seq in (chapters[:2], chapters[2:6]):
        for chapter in seq:
            for sc, i in pick_page(series, chapter):
                fp = "manga:%s|%s|%d" % (series, chapter, i)
                if fp in avoid:
                    continue
                if best is None or sc > best[0]:
                    best = (sc, chapter, i, fp)
        if best:
            break
    return best


def make_asset(query: str, avoid=frozenset()) -> dict:
    """取材主过程（同步，约 5~60 秒）。返回 save_asset 的结果或 {"ok": False}。

    avoid 是"已经用过的来源指纹"集合（来自资产 key.json 的 src_fp）：
    传了它，取材会跳过这些参考图，用户连说"再来一张"时每次都能拿到不一样的。
    """
    q = str(query or "").strip()
    avoid = frozenset(avoid or ())
    if not q:
        return {"ok": False, "error": "给了个空话题"}
    hit = find_pixiv(q, avoid=avoid)
    if hit:
        sc, fname, info = hit
        meta = {"id": "take_" + time.strftime("%m%d%H%M%S"),
                "src_fp": "pixiv:" + fname,
                "name": info.get("name") or q[:12],
                "aliases": "、".join([q] + [str(x) for x in (info.get("aliases") or [])][:4]),
                "tags": "、".join([str(x) for x in (info.get("tags") or [])][:6] + ["取材"])}
        r = _build({"kind": "pixiv", "name": fname}, meta, cols=144, rows=96)
        r["note"] = "pixiv 命中（%.2f）：%s" % (sc, str(info.get("desc") or "")[:40])
        return r
    mh = find_manga(q)
    if mh:
        sc, series = mh
        chapters = wb.list_chapters(series)
        picked = _pick_page_fresh(series, chapters, avoid) if chapters else None
        if picked:
            ps, chapter, page, fp = picked
            meta = {"id": "take_" + time.strftime("%m%d%H%M%S"),
                    "src_fp": fp, "name": series[:12], "aliases": q,
                    "tags": "%s、取材" % series}
            r = _build({"kind": "manga", "series": series, "chapter": chapter, "page": page},
                       meta, cols=120, rows=80)
            r["note"] = "漫画《%s》%s 第 %d 页（可描性 %d）" % (series, chapter, page + 1, ps)
            return r
        # 漫画里的页都描过 → 掉到网搜兜底，尽量给一张新的
    wh = find_web(q, avoid=avoid)
    if wh:
        sc, path, why = wh
        nm = " ".join(q.split()[:2])[:12] or q[:12]
        meta = {"id": "take_" + time.strftime("%m%d%H%M%S"),
                "src_fp": _fp_web(path), "name": nm, "aliases": q, "tags": "网搜、取材"}
        r = _build({"kind": "upload", "path": str(path)}, meta, cols=144, rows=96)
        r["note"] = "网搜取材：%s（可描性 %d；%s）" % (q, sc, why)
        return r
    return {"ok": False, "error": "本地图库和网搜里都没有和「%s」相关的新图" % q}


def _build(src: dict, meta: dict, cols: int, rows: int) -> dict:
    try:
        crop = wb.autocrop(src)
        p = {**wb.BASE, "cols": cols, "rows": rows}
        r = wb.save_asset(src, crop, p, meta)
        r["name"] = meta.get("name") or ""
        return r
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
