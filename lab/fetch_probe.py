"""komiic 抓取链路探针（标准库 + 代理）：搜索 → 章节 → 图片 → 下载一张验证。"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://komiic.com"
PROXY = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:10809"
OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
OUT = Path(r"D:\GitHub\.tmp\probe\fetch")


def req(path, data=None, headers=None, method=None):
    hdr = {"User-Agent": UA, "Accept": "application/json",
           "Content-Type": "application/json", "Origin": BASE, "Referer": BASE + "/"}
    hdr.update(headers or {})
    r = urllib.request.Request(BASE + path, data=data, headers=hdr, method=method)
    with OPENER.open(r, timeout=30) as resp:
        return resp.status, resp.read()


def gql(query, variables):
    s, b = req("/api/query", data=json.dumps({"query": query, "variables": variables}).encode())
    d = json.loads(b)
    if "errors" in d:
        raise RuntimeError(str(d["errors"])[:300])
    return d.get("data", {})


def main():
    kw = "葬送的芙莉莲"
    q = ('query s($kw:String!){ searchComics(keyword:$kw, '
         'pagination:{limit:6, offset:0, orderBy:DATE_UPDATED, asc:false}){ '
         'id title year status authors{name} } }')
    d = gql(q, {"kw": kw})
    hits = d.get("searchComics") or []
    print("搜索 %s -> %d 条" % (kw, len(hits)))
    for x in hits[:6]:
        print("  ", x["id"], x["title"], x.get("year"),
              [a["name"] for a in (x.get("authors") or [])])
    if not hits:
        return
    cid = hits[0]["id"]
    d = gql('query c($id:ID!){ chaptersByComicId(comicId:$id){ id serial type size } }',
            {"id": str(cid)})
    chs = d.get("chaptersByComicId") or []
    print("章节 %d 个，例如：" % len(chs))
    for c in chs[:4]:
        print("  ", c["id"], c.get("serial"), c.get("type"), c.get("size"))
    chid = chs[0]["id"]
    d = gql('query i($id:ID!){ imagesByChapterId(chapterId:$id){ id kid width height orderNumber } }',
            {"id": str(chid)})
    imgs = sorted(d.get("imagesByChapterId") or [],
                  key=lambda x: x.get("orderNumber") or 0)
    print("第一话图片数：", len(imgs))
    if imgs:
        img = imgs[0]
        url = BASE + "/api/image/" + img["kid"]
        ref = "%s/comic/%s/chapter/%s" % (BASE, cid, chid)
        hdr = {"User-Agent": UA, "Accept": "*/*", "Referer": ref}
        r = urllib.request.Request(url, headers=hdr)
        t0 = time.time()
        try:
            with OPENER.open(r, timeout=60) as resp:
                data = resp.read()
            OUT.mkdir(parents=True, exist_ok=True)
            f = OUT / "probe_p1.jpg"
            f.write_bytes(data)
            print("下载一张: %d KB, %.1fs -> %s" % (len(data) // 1024, time.time() - t0, f))
        except Exception as e:
            print("下载失败:", type(e).__name__, str(e)[:200])


if __name__ == "__main__":
    main()
