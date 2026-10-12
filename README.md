# tui-world

对话驱动的 TUI 世界显示器：左侧是对话框，右侧是随对话实时渲染的终端风格画面。

本仓库 fork 自 [MisakaZentai/world-search-you-dsh-pv](https://github.com/MisakaZentai/world-search-you-dsh-pv)，用作新项目的起点。

## 现有内容

| 路径 | 说明 |
|---|---|
| `runtime/tuikit/` | 上游 TUI 渲染引擎（15 个文件，约 140 KB）：帧 = 时间的函数、字符网格绘制、转场、后处理、无头截图工具 |

上游音乐影像的内容（Mili《world.search(you);》同人 PV 的影片代码、时间轴数据与美术素材，合计约 10.9 MB）已全部移除：
`film/`、`data/`、`vendor/`、`tools/`、`build.py`、`pv_paths.py`、`pv_text.py`。
上游 README 存档见 [docs/UPSTREAM_PV02.md](docs/UPSTREAM_PV02.md)。

引擎已与原项目解耦（不再依赖 `pv_paths.py` / `pv_text.py`），可独立导入：

```python
import sys
sys.path.insert(0, "runtime")
import tuikit
```

## 运行

双击 `run.bat`（首次会自动在本目录创建 `.venv` 并安装依赖，全部在 D 盘）。也可以手动：

```text
python -m core.app --open          # 浏览器双栏界面：左对话，右世界
python -m core.probe "聊聊霍格沃茨"   # 只出一帧 PNG（out/world.png）
```

右侧画面里的素材（角色/景物）来自**素材工作台**（`http://127.0.0.1:8777/wb`，
对话页左上角有入口）：从漫画页 / Pixiv 图库 / 上传图入库，自动取景 + 六张候选 +
可描性评分，描成字符画（`assets/<id>/key.json`）。对话里聊到素材库里的东西时，
导演会用 `show` 把它切上屏，动作模板可选：摇曳 / 呼吸 / 浮现 / 故障 / 雨幕 / 推近。
屏幕只有两路内容：**素材**（show）或**分镜**（stage），不在库里、也不值得找的东西
就不再画了——屏幕留给真实参考图描出来的东西和实时长出来的画面。（原先那套"让程序
直接画物件"的 place 已删除。）
库里没有但值得一看的（角色、名场面、地方），导演会自己 `capture` 取材：先搜本地
Pixiv 内容索引 / 漫画库，再兜底 Bing 图搜（走本机 socks 代理），视觉模型从候选里
挑最适合描摹的一张，描好**自动上屏**，不用用户点名。
说「再来一张」时它会带 `fresh=true`：跳过已经用过的参考图，换个角度再描一张新的。

聊到**过程 / 数据 / 气氛**（在跑、在等、在流逝、雨夜、登场）时，导演还会用 `stage`
让屏幕当场「演一段」：打字机逐字写、计数器往上滚、曲线一段段长出来、进度条推进、
粒子在飘、素材从噪点里显影——每个零件每帧从零重画，是信息在流动，不是静态图加抖动。
（零件库在 `core/stage.py`；`lab/stage_preview.py` 可以按时刻渲染一份分镜单来目检。）

模型密钥放在 `.env`（已 git 忽略，不会提交）：

```text
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

## 状态

M0/M1 已跑通：一句话 → 导演（LLM 工具调用）→ 世界状态 → 浏览器双栏实时画面。
素材工作台（漫画库 / Pixiv / 上传 → 取景 → 候选 → 入库 + 自动标签）、
抓取（komiic）、动作模板库（一套动作套所有素材）、可描性评分均已接入。
尚未实现：变焦守卫自动触发、chronicle 回放。

## 许可

代码 MIT，见 [LICENSE](LICENSE)；美术、音乐与第三方组件的权利边界见 [NOTICE.md](NOTICE.md)。
