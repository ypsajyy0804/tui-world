# -*- coding: utf-8 -*-
"""探针：Bing 图搜走代理，看能不能抓到原图链接并下载。"""
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROXY = "http://127.0.0.1:10809"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def search(q, engine="bing"):
    if engine == "bing":
        url = ("https://www.bing.com/images/search?q=" + urllib.parse.quote(q)
               + "&mkt=zh-CN&form=HDRSC2")
    elif engine == "bingcn":
        url = ("https://cn.bing.com/images/search?q=" + urllib.parse.quote(q)
               + "&mkt=zh-CN")
    elif engine == "so360":
        url = ("https://image.so.com/j?q=" + urllib.parse.quote(q)
               + "&pn=30&rn=30&src=srp")
    elif engine == "sogou":
        url = ("https://pic.sogou.com/napi/pc/searchList?mode=1&start=0&xml_len=30&query="
               + urllib.parse.quote(q))
    else:
        url = ("https://image.baidu.com/search/acjson?tn=resultjson_com&word="
               + urllib.parse.quote(q) + "&pn=0&rn=10")
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    html = opener.open(req, timeout=25).read().decode("utf8", "ignore")
    print(engine, "html len:", len(html))
    if engine == "bing":
        murls = re.findall(r"&quot;murl&quot;:&quot;(.*?)&quot;", html)
        if not murls:
            murls = re.findall(r'"murl":"(.*?)"', html)
    elif engine == "bingcn":
        murls = re.findall(r"&quot;murl&quot;:&quot;(.*?)&quot;", html)
        if not murls:
            murls = re.findall(r'"murl":"(.*?)"', html)
    elif engine == "so360":
        murls = re.findall(r'"img":"(.*?)"', html)
    elif engine == "sogou":
        murls = re.findall(r'"oriPicUrl":"(.*?)"', html)
    else:
        murls = re.findall(r'"objURL":"(.*?)"', html)
        if not murls:
            murls = re.findall(r'"hoverURL":"(.*?)"', html)
    print("murl count:", len(murls))
    return murls


def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "霍格沃茨城堡"
    for engine in ("bingcn", "so360", "sogou", "baidu"):
        try:
            urls = search(q, engine)
            for u in urls[:6]:
                print("  -", u[:130])
        except Exception as e:
            print(engine, "ERR", type(e).__name__, e)


if __name__ == "__main__":
    main()
