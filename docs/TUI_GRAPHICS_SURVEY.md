# TUI 绘图生态调研（2026-10-11）

问题：tui-world 的本质是「字符格渲染 + 实时动画」。这条路有没有人系统研究过？
有哪些开源项目可以直接借鉴/使用？下面按用途分七类，星数为当日实查。

---

## A. 图像/视频 → 字符画（转换引擎）

我们 `take.py`（参考图 → 字符画）所在的位置。工业级标杆：

| 项目 | 星 | 语言 | 干什么 | 对我们的价值 |
|---|---|---|---|---|
| [chafa](https://github.com/hpjansson/chafa) | 5315 | C | 图片/动图 → ANSI/Unicode 字符画。符号集齐全（ASCII/块/半块/盲文/六分/八分），抖动+色彩策略可调，SIMD 优化，极快 | **最值得对照**：拿它当 A/B 基线，对比我们描图的质量；成熟符号/抖动方案可直接移植思路 |
| [libcaca](https://github.com/cacalabs/libcaca) | 698 | C | 老牌「彩色 ASCII 库」：img2txt、3D 变换、mplayer -vo caca 视频播放 | 抖动算法与「视频级字符播放」管线参考 |
| [ascii-image-converter](https://github.com/TheZoraiz/ascii-image-converter) | 3553 | Go | CLI 图片转 ASCII，多色/尺寸参数丰富 | CLI 工程化参考 |
| [timg](https://github.com/hzeller/timg) | 2778 | C++ | 终端图片/视频播放器，多后端（真彩半块 / sixel / kitty） | 多后端策略（探测终端能力） |
| [viu](https://github.com/atanunq/viu) | 3290 | Rust | 终端看图，支持 iTerm/Kitty 原生图形 | 同上 |
| [TerminalImageViewer](https://github.com/stefanhaustein/TerminalImageViewer) | 1683 | C++ | 半块字符 + RGB 真彩看图，速度快 | 「半块 = 2×1 像素/格」的经典实现 |
| [milli](https://github.com/Amansingh-afk/milli) / [gifterm](https://github.com/cmang/gifterm) | 79/54 | Rust/Py | 动图 → 字符动画 | 帧循环/播放器结构 |

另有史前鼻祖 **AAlib**（[SourceForge](https://aa-project.sourceforge.net/aalib/)，mplayer -vo aa、演示程序 bb）——
「用字符放视频」这件事 90 年代就有人做到帧率可用，抖动是其核心。

## B. 字符格当画布：一格多像素的技巧

关键洞察：**同样一格，加细像素密度有成熟方案**——盲文 2×4 点/格、四分之一块 2×2、半块 2×1。

| 项目 | 星 | 语言 | 技巧 |
|---|---|---|---|
| [drawille](https://github.com/asciimoo/drawille)（+ node/php/rust 等移植） | 3257 | Python | 盲文字符画线（2×4 点/格），海龟绘图风 |
| [terminedia](https://github.com/jsbueno/terminedia) | 103 | Python | 块字符做「1/4 字符像素」画布，真彩、内置大字/图像加载，同语言、可读源码 |
| [batgrl](https://github.com/salt-die/batgrl) | 574 | Python | 终端图形库（游戏/模拟/应用全能），Python 生态最接近「终端画布」 |
| [textual-canvas](https://github.com/davep/textual-canvas) | 59 | Python | Textual 的字符画布组件（往 TUI 里画线/图形） |
| [rsille](https://github.com/nidhoggfgg/rsille) | 61 | Rust | 终端绘线/图形库 |
| [plutonem](https://github.com/Smart6502/plutonem) | 72 | 多语言 | 在终端「画像素」的库 |
| [tcg](https://github.com/msoap/tcg) / [libtermboy](https://github.com/dobyrch/libtermboy) | 119/73 | Go/C | 终端格图形/游戏渲染库 |

## C. 3D / 实时渲染到字符（我们的 space.py 的同类）

| 项目 | 星 | 语言 | 能力 |
|---|---|---|---|
| [TermGL](https://github.com/wojciech-graj/TermGL) | 407 | C | 终端 2D/3D 图形引擎：**自定义顶点/像素着色器、纹理映射**、24bit 色彩；C99 零依赖 | 
| [asciicker](https://github.com/msokalski/asciicker) | 369 | JS/WASM | 「3D ASCII 游戏概念」：第一人称全 3D 场景实时渲染成彩色字符画，流畅度/密度标杆 |
| [retrovoxel](https://github.com/leonmavr/retrovoxel) | 107 | C | 零依赖终端 3D 体素引擎 |
| [AsciiEngine](https://github.com/sephirot47/AsciiEngine) | 22 | C++ | 256 色终端 3D 游戏引擎 |

我们是「线框 + 雾 + 轨道相机」；TermGL/asciicker 证明了「字符格上做完整光栅化/着色」的可行性与上限。

## D. 动画编辑器与素材工具（做「帧动画 / 动作库」的镜子）

| 项目 | 星 | 语言 | 说明 |
|---|---|---|---|
| [asciimatics](https://github.com/peterbrittain/asciimatics) | 4305 | Python | curses 之上：精灵、特效、动画 API。**可直接 pip 对照** |
| [Durdraw](https://github.com/durdraw/durdraw) | 1837 | Python | 终端里的 ASCII/ANSI 编辑器，支持多帧动画 |
| [Moebius](https://github.com/blocktronics/moebius) | 982 | JS | 现代 ANSI/ASCII 美术编辑器（BBS 场景正统工具链） |
| [PabloDraw](https://github.com/cwensley/pablodraw) | 433 | Pascal | 老牌 ANSI 编辑器/查看器 |
| [text0wnz](https://github.com/xero/text0wnz) | 128 | JS | 浏览器里画/协作 ANSI/ASCII |
| PlaySCII | — | Python | 最完整的 ASCII 动画编辑器；原 GitHub 已迁 [Heptapod](https://heptapod.host/jp-lebreton/playscii)，留 [fork](https://github.com/michael-lazar/playscii) |
| [asciimation](https://github.com/octobanana/asciimation) | 111 | Rust | ASCII 动画格式解释器 |
| [ascii-live](https://github.com/hugomd/ascii-live) / [weathr](https://github.com/Veirt/weathr) | 1058/3070 | JS/Rust | 循环动画/特效先例 |

## E. 终端渲染引擎（性能侧）

| 项目 | 星 | 语言 | 关键机制 |
|---|---|---|---|
| [notcurses](https://github.com/dankamongmen/notcurses) | 4742 | C | 字符图形库天花板：真彩、平面、blitter、z-buffer、直接模式、多线程 |
| [ratatui](https://github.com/ratatui/ratatui)（+ [ratatui-image](https://github.com/benjajaja/ratatui-image) 406） | 22938 | Rust | 只写「变化的格子」（diff 渲染），image widget 多协议 |
| [Textual](https://github.com/Textualize/textual) | 37428 | Python | 现代 TUI 框架（CSS 式），同语言 |
| [bubbletea](https://github.com/charmbracelet/bubbletea) | 45433 | Go | 主流 TUI 框架 |

速度的核心两个字：**差分**（dirty cell diffing，只重画变化格）。我们现在整帧渲染 PNG 给浏览器，天然回避了这个问题；
若未来显示器跑在真终端里，必须抄这一课。

## F. 真像素旁路（了解即可）

[libsixel](https://github.com/saitoha/libsixel)（2852*）、Kitty graphics、iTerm2 inline images——
终端里直接显示真图片。**与 TUI 风格初衷相反**，不建议作为主路线；可做「高清备用层」。

## G. 索引类

- [awesome-tuis](https://github.com/rothgar/awesome-tuis)（20858*）
- [awesome-hacker-art](https://github.com/NoDataFound/awesome-hacker-art)（ANSI/ASCII 工具精选）
- [ansilove](https://github.com/ansilove/ansilove)（431*）：ANSI/ASCII 画 → PNG（反方向，可当素材来源）

---

## 对 tui-world 的结论（怎么用）

1. **描图质量对照**：把 `chafa` 当基线跑一遍同一张参考图（符号集/抖动可调），用于校准我们 `take.py` 的字符画质量与速度。
2. **一格多像素**：未来把 `model3d` 的细线用盲文点（2×4/格）画、或把素材渲染升级到半块/四分之一块——同尺寸下细节翻倍。terminedia（同语言）可读源码抄实现。
3. **着色与材质**：`space.py` 仍是纯线框；TermGL 的「字符格光栅化 + 着色器 + 纹理」是下一步升级（如暖色窗光、灯晕）的成熟路线图。
4. **动作/帧动画**：素材工作台的「动作模板」可以对照 Moebius/Durdraw 的帧模型；`asciimatics` 可 pip 直接试。
5. **性能**：若做「真终端输出」模式，用差分渲染（notcurses/ratatui 的做法）；当前浏览器 PNG 管线无需。
6. **不推荐**：sixel/kitty 真像素——好看但丢了字符画灵魂。

一句话：这条路线不仅有人研究，还有 30 年积累（AAlib→libcaca→chafa/TermGL/asciicker）；
我们缺的「着色、一格多像素、差分渲染」三块，都有现成答案可抄。
