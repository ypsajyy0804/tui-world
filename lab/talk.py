"""对话测试客户端：POST /say → 等世界安静 → 打印工具调用与状态。

用法：python lab/talk.py "第一句" "第二句" ...
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf8"))


def _post(text):
    body = json.dumps({"text": text}).encode("utf8")
    req = urllib.request.Request(BASE + "/say", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf8"))


def wait_idle(timeout=120.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _get("/state")
        if s["status"] == "idle":
            return s
        time.sleep(0.5)
    raise TimeoutError("世界一直没安静下来")


def main(argv):
    for line in argv:
        t0 = time.time()
        before = len(_get("/state")["messages"])
        print("=" * 70)
        print("你：" + line)
        _post(line)
        s = wait_idle()
        for m in s["messages"][before:]:
            if m["role"] == "director":
                print("导演：" + (m.get("text") or "").replace("\n", " "))
                for c in m.get("calls") or []:
                    print("   · %s %s" % (c["name"], json.dumps(c["args"], ensure_ascii=False)))
            elif m["role"] == "system":
                print("系统：" + (m.get("text") or ""))
        w = s["world"]
        sig = w.get("signal") or {}
        print("世界：%s / E%.2f / %s  focus=%s zoom %.1f  屏幕=%s" % (
            w["palette"], w["energy"], w["weather"],
            w["focus"]["concept"] or "-", w["focus"]["zoom"],
            w.get("stage") or sig.get("name") or "（空）"))
        print("用时 %.1fs  累计 tokens %s" % (time.time() - t0, s["meta"].get("tokens")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
