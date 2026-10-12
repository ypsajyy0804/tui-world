"""工作台接口冒烟测试：直接用 urllib 打一遍全部路由。"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8777"


def get(path, **q):
    url = BASE + path
    if q:
        url += "?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf8"),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, r.read()


def main():
    s, ct, b = get("/wb/sources")
    j = json.loads(b)
    print("sources:", s, "| manga", len(j["manga"]), "| pixiv", len(j["pixiv"]),
          "| assets", len(j["assets"]))
    series = j["manga"][0]
    s, ct, b = get("/wb/manga", series=series)
    chapters = json.loads(b)["chapters"]
    print("chapters:", len(chapters), chapters[0] if chapters else "-")
    s, ct, b = get("/wb/chapter", series=series, chapter=chapters[0])
    pages = json.loads(b)["pages"]
    print("pages:", pages)
    s, ct, b = get("/wb/page", series=series, chapter=chapters[0],
                   page=min(3, pages - 1), w=90)
    print("thumb:", s, ct, len(b), "bytes")

    series2 = [x for x in j["manga"] if "烙印" in x][0]
    s, ct, b = get("/wb/manga", series=series2)
    ch = json.loads(b)["chapters"]
    s, ct, b = get("/wb/chapter", series=series2, chapter=ch[0])
    pages = json.loads(b)["pages"]
    t0 = time.time()
    s, b = post("/wb/candidates", {
        "src": {"kind": "manga", "series": series2, "chapter": ch[0],
                "page": min(5, pages - 1)},
        "crop": [0, 0, 1, 0.55],
        "params": {"cols": 120, "rows": 80, "contrast": 1.2, "key": True,
                   "key_tol": 0.16, "invert": False}})
    jj = json.loads(b)
    print("candidates:", s, len(jj["candidates"]),
          ["%s/%s%%" % (c["label"], c["cover"]) for c in jj["candidates"]],
          "%.1fs" % (time.time() - t0))
    for i in (0, 3):
        open(r"D:\GitHub\.tmp\probe\wb_cand%d.png" % i, "wb").write(
            base64.b64decode(jj["candidates"][i]["png_b64"]))
    print("候选已存 probe/wb_cand0.png / wb_cand3.png")

    pix = j["pixiv"][0]
    t0 = time.time()
    s, b = post("/wb/suggest", {"src": {"kind": "pixiv", "name": pix}, "crop": None})
    print("suggest:", s, json.loads(b), "%.1fs" % (time.time() - t0))


if __name__ == "__main__":
    sys.exit(main())
