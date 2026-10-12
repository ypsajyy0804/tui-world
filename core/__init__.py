"""tui-world core —— 对话驱动的世界显示器（M0 阶段）。

runtime/tuikit 是 fork 来的渲染引擎，core 只依赖它、不修改它。
"""
import sys
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parent.parent / "runtime"
if _RUNTIME.is_dir() and str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))
