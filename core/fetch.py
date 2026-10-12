r"""抓取：komiic（经本机代理）→ CBZ 落进漫画库。

接口来自 D:\VM_share\爬虫工作流 里验证过的 komiic 工作流（GraphQL）。
本机直连走代理：默认 http://127.0.0.1:10809（v2rayN 的 http 端口），
可用 .env / 环境变量 WB_FETCH_PROXY 覆盖。

不内置任何账号：匿名可用；若遇到 402（每日读取上限）就在 .env 里放
KOMIIC_TOKEN，或 KOMIIC_EMAIL / KOMIIC_PASS（会自动登录换 token）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import load_env

_cfg = load_env()
BASE = "https://komiic.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")


class QuotaError(RuntimeError):
    pass


class Komiic:
    def __init__(self, proxy: str | None = None):
        self.proxy = (proxy or os.environ.get("WB_FETCH_PROXY")
                      or _cfg.get("WB_FETCH_PROXY") or "http://127.0.0.1:10809")
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        self.token = (os.environ.get("KOMIIC_TOKEN") or _cfg.get("KOMIIC_TOKEN") or "")

    def _hdr(self, extra: dict | None = None, json_body: bool = True) -> dict:
        hdr = {"User-Agent": UA, "Accept": "application/json", "Origin": BASE,
               "Referer": BASE + "/"}
        if json_body:
            hdr["Content-Type"] = "application/json"
        if self.token:
            hdr["Authorization"] = "Bearer " + self.token
        hdr.update(extra or {})
        return hdr

    def _open(self, req, timeout, retries=2):
        last = None
        for i in range(retries + 1):
            try:
                return self.opener.open(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                if e.code == 402:
                    raise QuotaError("komiic 今日图片读取已达上限（匿名/未登录）——"
                                     "在 .env 里放 KOMIIC_TOKEN 或账号密码后重试")
                last = e
            except Exception as e:
                last = e
            time.sleep(0.8 * (i + 1))
        raise RuntimeError("网络失败：%s: %s" % (type(last).__name__, last))

    def login(self) -> bool:
        email = os.environ.get("KOMIIC_EMAIL") or _cfg.get("KOMIIC_EMAIL") or ""
        pwd = os.environ.get("KOMIIC_PASS") or _cfg.get("KOMIIC_PASS") or ""
        if not email or not pwd or self.token:
            return bool(self.token)
        body = json.dumps({"email": email, "password": pwd}).encode("utf8")
        req = urllib.request.Request(BASE + "/api/login", data=body,
                                     headers=self._hdr({"Referer": BASE + "/login"}),
                                     method="POST")
        try:
            with self._open(req, 25) as r:
                self.token = (json.loads(r.read().decode("utf8")) or {}).get("token") or ""
        except Exception:
            self.token = ""
        return bool(self.token)

    def gql(self, query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode("utf8")
        req = urllib.request.Request(BASE + "/api/query", data=body,
                                     headers=self._hdr(), method="POST")
        with self._open(req, 30) as r:
            d = json.loads(r.read().decode("utf8"))
        if "errors" in d:
            raise RuntimeError(str(d["errors"][0].get("message"))[:200])
        return d.get("data") or {}

    # ---- 接口
    def search(self, kw: str, limit: int = 8) -> list:
        q = ("query s($kw:String!){ searchComics(keyword:$kw, "
             "pagination:{limit:%d, offset:0, orderBy:DATE_UPDATED, asc:false}){ "
             "id title year status authors{name} } }" % int(limit))
        d = self.gql(q, {"kw": kw})
        return [{"id": x["id"], "title": x["title"], "year": x.get("year"),
                 "authors": [a["name"] for a in (x.get("authors") or [])]}
                for x in (d.get("searchComics") or [])]

    def chapters(self, cid) -> list:
        q = "query c($id:ID!){ chaptersByComicId(comicId:$id){ id serial type size } }"
        d = self.gql(q, {"id": str(cid)})
        return [{"id": x["id"], "serial": x.get("serial"), "type": x.get("type"),
                 "size": x.get("size")}
                for x in (d.get("chaptersByComicId") or [])]

    def images(self, chid) -> list:
        q = "query i($id:ID!){ imagesByChapterId(chapterId:$id){ id kid width height orderNumber } }"
        d = self.gql(q, {"id": str(chid)})
        return sorted(d.get("imagesByChapterId") or [],
                      key=lambda x: x.get("orderNumber") or 0)

    def fetch_image(self, cid, chid, kid) -> bytes | None:
        ref = "%s/comic/%s/chapter/%s" % (BASE, cid, chid)
        req = urllib.request.Request(BASE + "/api/image/" + str(kid),
                                     headers=self._hdr({"Accept": "*/*", "Referer": ref},
                                                       json_body=False))
        for i in range(3):
            try:
                with self._open(req, 60) as r:
                    return r.read()
            except QuotaError:
                raise
            except Exception:
                time.sleep(0.6 * (i + 1))
        return None


_client: Komiic | None = None


def client() -> Komiic:
    global _client
    if _client is None:
        _client = Komiic()
    return _client


def safe(name) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip()[:120] or "unnamed"


def search(kw: str) -> list:
    return client().search(kw)


def chapters(cid) -> list:
    return client().chapters(cid)


def download_chapter(cid, chid, title: str, serial: str, out_root: Path,
                     threads: int = 6) -> dict:
    """下载一章 → 打包 CBZ 到 out_root/<标题>/<章节>.cbz。返回统计。"""
    c = client()
    imgs = c.images(chid)
    if not imgs:
        raise RuntimeError("这一章没有图片，或接口返回为空")
    got: dict = {}

    def one(item):
        data = c.fetch_image(cid, chid, item["kid"])
        if data:
            got[int(item.get("orderNumber") or 0)] = data

    todo = imgs[:400]
    with ThreadPoolExecutor(max_workers=max(1, min(threads, len(todo)))) as ex:
        futs = [ex.submit(one, it) for it in todo]
        for f in as_completed(futs):
            f.result()
    if not got:
        raise RuntimeError("一张都没下下来——多半是配额或网络问题")
    series_dir = out_root / safe(title)
    series_dir.mkdir(parents=True, exist_ok=True)
    stem = safe(serial) or "01"
    cbz = series_dir / (stem + ".cbz")
    n = 2
    while cbz.exists():
        cbz = series_dir / ("%s (%d).cbz" % (stem, n))
        n += 1
    with zipfile.ZipFile(cbz, "w", zipfile.ZIP_STORED) as z:
        for order in sorted(got):
            z.writestr("%04d.jpg" % (order + 1), got[order])
    return {"ok": True, "file": str(cbz), "pages": len(got),
            "missed": len(todo) - len(got), "mb": round(sum(len(v) for v in got.values()) / 1e6, 1)}
