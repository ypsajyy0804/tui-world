'''apply_patch 的中文安全入口（写补丁时踩过的坑）。

PowerShell 5.1 把原生命令的参数按系统 ANSI 代码页转码，带中文的补丁直接递给
apply_patch 会变成乱码，它报 requires a UTF-8 PATCH argument。绕开它：把补丁写成
UTF-8 文件，再用本脚本提交——脚本找到 apply_patch 背后的 codex.exe，用 subprocess
直接传 Unicode 参数。

用法：
    python tools/ap.py 补丁文件.patch
'''
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

_Q = chr(34)


def codex_exe() -> str:
    '''从 apply_patch 的 .bat 里读出 codex.exe 的真实路径。'''
    bat = shutil.which('apply_patch') or ''
    bdir = pathlib.Path(bat).parent if bat else None
    if bat:
        txt = pathlib.Path(bat).read_text(encoding='utf-8', errors='replace')
        i = txt.find('codex.exe')
        if i >= 0:
            raw = txt[txt.rfind(' ', 0, i) + 1:i + len('codex.exe')].strip()
            cand = pathlib.Path(raw.replace(_Q, '').replace('%~dp0', str(bdir) + '\\'))
            if cand.exists():
                return str(cand)
    for d in (bdir, pathlib.Path.home() / 'AppData/Local/OpenAI/Codex/bin'):
        if d is None:
            continue
        hits = list(d.glob('**/codex.exe'))
        if hits:
            return str(hits[0])
    return ''


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    exe = codex_exe()
    if not exe:
        print('找不到 apply_patch 背后的 codex.exe')
        return 2
    patch = pathlib.Path(argv[0]).read_text(encoding='utf-8-sig')
    r = subprocess.run([exe, '--codex-run-as-apply-patch', patch], capture_output=True)
    sys.stdout.buffer.write(r.stdout)
    sys.stderr.buffer.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
