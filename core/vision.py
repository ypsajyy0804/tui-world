"""视觉理解：看图 → 中文描述 → 命名/别名/标签。

两段式（工作台「AI 建议」与取材索引共用）：视觉模型只描述画面
（避免它钻牛角尖认角色烧光 token），文本模型再把描述整理成素材命名。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request

from PIL import Image

from .config import load_env

_cfg = load_env()


def _post_chat(base: str, body: dict, retries: int = 3) -> dict:
    req = urllib.request.Request(base + "/v1/chat/completions",
                                 data=json.dumps(body).encode("utf8"), method="POST")
    req.add_header("Authorization", "Bearer " + _cfg.get("DEEPSEEK_API_KEY", ""))
    req.add_header("Content-Type", "application/json")
    last = "unknown"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.loads(r.read().decode("utf8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError("HTTP %s %s" % (e.code, e.read().decode("utf8", "replace")[:200]))
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.0 + attempt)
    raise RuntimeError("连续 %d 次失败：%s" % (retries, last))


def describe(img: Image.Image) -> dict:
    """图 → 名称/别名/标签/描述。永不抛异常，失败返回 {"error": ...}。"""
    try:
        im = img.copy()
        im.thumbnail((512, 512))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        model = (_cfg.get("WB_VISION_MODEL") or os.environ.get("WB_VISION_MODEL")
                 or "deepseek-v4-flash-vision-exp")
        base = _cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        vbody = {"model": model, "messages": [{"role": "user", "content": [
            {"type": "text", "text":
                "用中文 1~3 句话描述这张图：画面主体（是谁/什么、外观特征）、构图与氛围。"
                "不确定身份就只描述外观，不要猜作品名，不要输出 JSON，不要分析推理。"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
            "max_tokens": 1200, "temperature": 0.3}
        payload = _post_chat(base, vbody)
        msg = (payload.get("choices") or [{}])[0].get("message") or {}
        desc = ((msg.get("content") or "").strip()
                or (msg.get("reasoning_content") or "").strip()[:300])
        if not desc:
            return {"error": "视觉模型没说出画面内容"}
        tbody = {"model": _cfg.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                 "messages": [
                     {"role": "system", "content":
                         "你是素材库管理员，负责给参考图起的画面描述生成素材命名。"},
                     {"role": "user", "content": desc + "\n\n只输出 JSON："
                         "{name: 素材中文名(≤8字，优先角色/作品名，否则用画面描述), "
                         "aliases: [3~6个别名，含角色名、作品名、英文名、描述性别名], "
                         "tags: [3~5个检索标签], desc: 一句话画面}。"}],
                 "max_tokens": 900, "temperature": 0.4,
                 "response_format": {"type": "json_object"}}
        payload2 = _post_chat(base, tbody)
        text = ((payload2.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        return {"name": str(data.get("name") or ""),
                "aliases": [str(x) for x in (data.get("aliases") or [])],
                "tags": [str(x) for x in (data.get("tags") or [])],
                "desc": str(data.get("desc") or desc), "model": model,
                "vision_desc": desc}
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}


def pick(query: str, paths: list) -> dict:
    """从网搜候选里挑"最适合描成字符画"的一张。

    要求：主体单一、轮廓清楚、背景干净、少文字水印。返回 {"index": n, "why": ..}；
    失败返回 {"error": ..}，调用方自行回退到可描性评分。
    """
    try:
        parts: list = [{"type": "text", "text":
            "下面是一次图搜「%s」的候选图（编号 0 起）。我们最终要把其中一张描成"
            "两色字符画。挑选标准（按重要性）：① 主体完整、不被边缘切掉、占画面一半以上；"
            "② 轮廓清楚、背景干净；③ 少文字/水印/拼贴、少杂乱人群或细碎灯光。"
            "主体太小、被裁掉、或画面被大量杂物占满的都不要选。"
            "选最适合的一张。只输出 JSON：{index: 编号, why: 一句话}" % query}]
        for i, p in enumerate(paths):
            im = Image.open(p).convert("RGB")
            im.thumbnail((300, 300))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()
            parts.append({"type": "text", "text": "候选 %d：" % i})
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:image/jpeg;base64," + b64}})
        model = (_cfg.get("WB_VISION_MODEL") or os.environ.get("WB_VISION_MODEL")
                 or "deepseek-v4-flash-vision-exp")
        base = _cfg.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        last = "模型没给出编号"
        for _ in range(2):
            body = {"model": model, "messages": [{"role": "user", "content": parts}],
                    "max_tokens": 2000, "temperature": 0.2,
                    "response_format": {"type": "json_object"}}
            payload = _post_chat(base, body)
            msg = (payload.get("choices") or [{}])[0].get("message") or {}
            text = ((msg.get("content") or "").strip()
                    or (msg.get("reasoning_content") or "").strip())
            idx = _extract_index(text, len(paths))
            if idx is not None:
                why = ""
                m = re.search(r"\{.*\}", text, re.S)
                if m:
                    try:
                        why = str((json.loads(m.group(0)) or {}).get("why") or "")
                    except Exception:
                        pass
                return {"index": idx, "why": why}
            last = "模型给的编号不合法：%s" % text[:80]
        return {"error": last}
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}


def _extract_index(text: str, n: int):
    for pat in (r'"index"\s*:\s*"?(\d+)"?', r'"编号"\s*:\s*"?(\d+)"?',
                r'"choice"\s*:\s*"?(\d+)"?'):
        m = re.search(pat, text)
        if m:
            i = int(m.group(1))
            if 0 <= i < n:
                return i
    return None
