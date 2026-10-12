"""B站视频下载（curl.exe 版，无需登录，匿名可达的最高画质）。

用法：python lab/bili_dl.py BV1xCai6aE9g [--outdir D:\\GitHub\\.tmp\\bili]

为什么用 curl.exe：urllib 的 TLS 指纹会被 B站风控 412；curl.exe 是系统自带、零依赖。
流地址必须带 Referer，否则 403。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CURL = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
FFMPEG = (os.environ.get("WB_FFMPEG") or shutil.which("ffmpeg")
          or r"D:\ffmpeg\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
REF = "https://www.bilibili.com/"


def curl(args: list, timeout: int = 120) -> int:
    r = subprocess.run([CURL, "-s", "-L", "--max-time", str(timeout),
                        "-A", UA, "-e", REF] + args)
    return r.returncode


def get_json(url: str, dest: Path) -> dict:
    curl([url, "-o", str(dest)])
    return json.loads(dest.read_text(encoding="utf8"))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    bv = args[0]
    outdir = Path(args[args.index("--outdir") + 1]) if "--outdir" in args \
        else Path(r"D:\GitHub\.tmp\bili")
    outdir.mkdir(parents=True, exist_ok=True)
    v = get_json("https://api.bilibili.com/x/web-interface/view?bvid=" + bv,
                 outdir / "view.json")["data"]
    cid = v["cid"]
    print("标题:", v["title"], "| 时长: %ss" % v["duration"])
    pu = get_json("https://api.bilibili.com/x/player/playurl?bvid=%s&cid=%s"
                  "&fnval=16&fourk=1" % (bv, cid), outdir / "playurl.json")["data"]
    dash = pu.get("dash") or {}
    vids = [s for s in (dash.get("video") or []) if s.get("codecs", "").startswith("avc1")]
    if not vids:
        vids = dash.get("video") or []
    if not vids:
        print("没有 dash 流（可能需要登录）")
        return 2
    best = max(vids, key=lambda s: (s.get("height") or 0, s.get("bandwidth") or 0))
    av = max((dash.get("audio") or []), key=lambda s: s.get("bandwidth") or 0)
    print("画质: %dx%d  %s" % (best.get("width"), best.get("height"),
                               best.get("codecs")))
    vf, af = outdir / "video.m4s", outdir / "audio.m4s"
    curl([best["baseUrl"], "-o", str(vf)])
    if av:
        curl([av["baseUrl"], "-o", str(af)])
    out = outdir / (bv + ".mp4")
    cmd = [FFMPEG, "-y", "-i", str(vf)]
    if af.exists():
        cmd += ["-i", str(af)]
    cmd += ["-c", "copy", str(out)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        print("ffmpeg 合并失败")
        return 3
    print("输出:", out, "%.1f MB" % (out.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
