r"""网络图源：Bing 图搜 → 下载候选图（供取材器按可描性挑图）。

为什么用 curl.exe：本机 v2rayN 的 http 端口(10809)对 bing 是断的、socks(10808) 通；
Python urllib 用不了 socks，而 Windows 自带 curl.exe 支持 socks5h，零额外依赖。
候选图缓存在 .tmp/wb/uploads/web/<查询hash>/，同一话题重复取材直接复用。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

from . import workbench as wb

CURL = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
PROXIES = ("socks5h://127.0.0.1:10808", "http://127.0.0.1:10809")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
DL_DIR = wb.UPLOADS / "web"


def _curl(args: list, timeout: int):
    try:
        return subprocess.run([CURL, "-s", "-L", "--max-time", str(timeout)] + args,
                              capture_output=True, timeout=timeout + 8)
    except Exception:
        return None


def get_text(url: str, timeout: int = 25) -> str:
    """经代理抓页面文本；socks 先试、http 代理兜底。失败返回空串。"""
    for proxy in PROXIES:
        r = _curl(["-x", proxy, "-A", UA,
                   "-H", "Accept-Language: zh-CN,zh;q=0.9", url], timeout)
        if r is not None and r.returncode == 0 and r.stdout:
            t = r.stdout.decode("utf8", "ignore")
            if len(t) > 500:
                return t
    return ""


def get_file(url: str, dest: Path, timeout: int = 25) -> bool:
    for proxy in PROXIES:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = _curl(["-x", proxy, "-A", UA, "-o", str(dest), url], timeout)
        if (r is not None and r.returncode == 0 and dest.exists()
                and dest.stat().st_size > 6000):
            return True
    return False


def image_search(q: str, limit: int = 12) -> list:
    """Bing 图搜 → 图片直链列表（murl；不够时补 turl 缩略图）。"""
    url = ("https://www.bing.com/images/search?q=" + urllib.parse.quote(str(q))
           + "&mkt=zh-CN&form=HDRSC2")
    html = get_text(url)
    if not html:
        return []
    out: list = []
    for pat in (r"&quot;murl&quot;:&quot;(.*?)&quot;", r'"murl":"(.*?)"'):
        for u in re.findall(pat, html):
            u = u.replace("&amp;", "&")
            if u not in out:
                out.append(u)
    if len(out) < limit:
        for u in re.findall(r"&quot;turl&quot;:&quot;(.*?)&quot;", html):
            u = u.replace("&amp;", "&")
            if u not in out:
                out.append(u)
    return out[:limit]


def _fp(p) -> str:
    return "web:" + hashlib.md5(Path(p).read_bytes()).hexdigest()[:12]


def fetch_candidates(q: str, budget: int = 8, avoid=frozenset()) -> list:
    """搜 + 并行下载 → 本地可读图片路径列表（带缓存与应用级校验）。

    avoid 里的指纹会被跳过（"再来一张"时别挑回老图）；存货不够挑时自动
    把搜索结果的剩余链接再下一批。全都被 avoid 时才退回老图兜底。
    """
    from PIL import Image
    key = hashlib.md5(str(q).strip().lower().encode("utf8")).hexdigest()[:12]
    d = DL_DIR / key

    def cached() -> list:
        out: list = []
        if d.exists():
            for p in sorted(d.glob("*.jpg")):
                if p.stat().st_size > 6000:
                    out.append(p)
        return out

    fresh = [p for p in cached() if _fp(p) not in avoid]
    if len(fresh) >= 3:
        return fresh[:budget]

    urls = image_search(q, limit=30)
    todo = []
    for i, u in enumerate(urls):
        dest = d / ("%02d.jpg" % i)
        if not dest.exists():
            todo.append((u, dest))

    def one(u: str, dest: Path):
        if not get_file(u, dest):
            return None
        try:
            Image.open(dest).convert("RGB").load()
        except Exception:
            try:
                dest.unlink()
            except OSError:
                pass
            return None
        return dest

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(one, u, dest) for u, dest in todo[:14]]
        for f in as_completed(futs):
            f.result()

    all_ = cached()
    fresh = [p for p in all_ if _fp(p) not in avoid]
    if fresh:
        return fresh[:budget]
    return all_[:budget]          # 全被 avoid 掉了，只能退回老图
