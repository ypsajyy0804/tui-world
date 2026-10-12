"""给 Pixiv 图库建内容索引（取材器用）：逐张调视觉模型生成 名称/标签/描述。

用法：python lab/index_pixiv.py [--limit N] [--force]
已打标的文件名跳过；每张都落盘，断了直接重跑续上。
索引：.tmp/wb/pixiv_index.json
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import vision
from core import workbench as wb
from core.take import load_index, save_index


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    force = "--force" in args
    names = wb.list_pixiv()
    data = load_index()
    files = data.setdefault("files", {})
    todo = names if force else [n for n in names if n not in files]
    if limit:
        todo = todo[:limit]
    print("pixiv 共 %d 张，待打标 %d 张" % (len(names), len(todo)))
    ok = err = 0
    for i, name in enumerate(todo, 1):
        try:
            r = vision.describe(wb.pixiv_image(name))
            if r.get("error"):
                err += 1
                print("[%d/%d] %s 失败：%s" % (i, len(todo), name, r["error"][:90]))
                continue
            files[name] = {"name": r.get("name") or "",
                           "aliases": r.get("aliases") or [],
                           "tags": r.get("tags") or [],
                           "desc": r.get("desc") or "",
                           "ts": time.strftime("%Y-%m-%d %H:%M")}
            save_index(data)
            ok += 1
            print("[%d/%d] %s → %s | %s" % (i, len(todo), name, files[name]["name"],
                                            "、".join(files[name]["tags"][:4])))
        except Exception as e:
            err += 1
            print("[%d/%d] %s 异常：%s" % (i, len(todo), name, e))
    print("完成：成功 %d，失败 %d，索引共 %d 张" % (ok, err, len(files)))


if __name__ == "__main__":
    main()
