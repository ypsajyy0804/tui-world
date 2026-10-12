# tui-world 项目记忆

> 开发代理记事本：接手先读本文件；重要决策、约定、坑随手追加。
> 最后更新：2026-10-12

## 一、定位
- 形态：聊天窗口 + 右侧 TUI 显示器；聊天时显示器自然呈现“AI 眼中的世界”（TUI 图案 / TUI 动画）。
- 原则：聊到什么自然浮现相关画面（例：聊哈利波特 → 可能是城堡，也可能是那道疤）；反对“为展示而展示”的催促式提示词；反对把素材库当作全世界。
- 画面标准：追求参考图级真实感（源自《边缘行者》大卫/露西参考图方案）；纯程序直绘抽象图案的路线已被用户否决并砍掉。
- 原型参考：B站《如果聊天窗口就是她的整个世界 —— world.execute(me)》（BV1xCai6aE9g），关键是画面“动”且流畅。

## 二、架构地图（D:\GitHub\tui-world）
- core/app.py —— HTTP 服务 + 后台线程（_compose/_compose_worker）
- core/scene.py —— 画面合成 + CRT 后处理
- core/stage.py —— 零件库：typewriter / counter / chart / progress / particles / emerge / bigtext / lograin / silhouette / figure / model3d
- core/assets.py —— 素材上屏（参考图描出的字符画）：motion = sway / breathe / emerge / glitch / rain / push / text（文字剪影）
- core/tools.py —— 工具 schema + 参数 coerce（兜底模型把 kind 写成 type）
- core/painter.py —— 画师流水线：flash 写分镜单 → 渲染 → 视觉评审 → 迭代 → 存 assets/recipes/
- core/director.py —— 导演（聊天循环 LLM），持 compose 工具，可把绘制任务派给画师
- core/take.py —— 取材器（素材抓取）
- runtime/tuikit/ —— fork 的 TUI 渲染引擎（space.py / post.py）；core/__init__.py 将其塞入 sys.path；本地已给 space.py 追加 shade_tex() / shade_box()
- lab/stage_preview.py / lab/signal_preview.py / lab/talk.py —— 分镜预览 / 素材动效预览 / 实聊脚本
- docs/DESIGN.md（已到第 25 节）、docs/TUI_GRAPHICS_SURVEY.md（TUI 绘图开源方案调研）、docs/VIDEO_ANIMATION_STUDY.md（原片动效研究）

## 三、角色定义
- 导演 = 聊天循环的 LLM（deepseek-v4-flash）：决定聊什么、何时派活。
- 画师 = 后台 compose 流水线（flash 写分镜单 JSON → 渲染 → 视觉质检 → 迭代 → 存配方）。
- 取材器 = take.py：抓素材供描摹。

## 四、硬性约定
- 只占 D 盘：每条命令先 `$env:TEMP='D:\GitHub\.tmp'; $env:TMP='D:\GitHub\.tmp'`
- 不 git commit；改文件走 apply_patch。中文补丁别直接把内容当参数递给 apply_patch：
  PowerShell 5.1 会按系统 ANSI 转码搞乱它（报 requires a UTF-8 PATCH argument）；
  把补丁写成 UTF-8 文件，再走 `python tools\ap.py <补丁文件>`（脚本内部用 subprocess
  调 codex.exe --codex-run-as-apply-patch，参数走 Unicode）
- 中文交流；完成后停下汇报，附图用绝对路径
- 模型：主力 deepseek-v4-flash；视觉评审 deepseek-v4-flash-vision-exp（WB_VISION_MODEL）；deepseek-v4-pro 贵，仅备用；密钥在 .env
- painter max_tokens=8000；flash 推理易吃满被截断，截断则压缩重试
- 对画面直说问题，不粉饰

## 五、常用命令
- 起服务（组合命令会被策略拦，需拆分）：
  Start-Process D:\GitHub\tui-world\.venv\Scripts\python.exe -ArgumentList -X,utf8,-u,-m,core.app,--port,8777 -WorkingDirectory D:\GitHub\tui-world
  日志：D:\GitHub\.tmp\app8777.*.log
- 关服务：Get-CimInstance Win32_Process 匹配 *core.app* → Stop-Process
- 离线预览：.venv\Scripts\python.exe -X utf8 lab\stage_preview.py out\x.png 0 2 5 --plan <plan.json>
- 实聊：.venv\Scripts\python.exe -X utf8 lab\talk.py 话
- 画师单跑：.venv\Scripts\python.exe -X utf8 -m core.painter 画什么 --rounds 3
- 无头截图：Edge headless → out/web_*.png

## 六、待办 / 悬而未决
- 【待用户确认】L0~L3 框架（AI 与绘制引擎的接触面），推荐 L2「生成器脚本」：AI 写带循环/参数的白名单脚本 → 编译成分镜单 JSON，进不了运行时。待产出设计文档 + model3d 最小原型（如 gen: {for n 座塔…}）。
- 候选增强：poly 地形填充、半块字符细度、盲文细线、真终端差分模式
- 素材语义动效（按 VIDEO_ANIMATION_STUDY 的结论，换掉「整图位移」）：已做「文字剪影」
  （show/capture 带 motion=text + text 参数，剪影内部填流动的字）；未做 分区形变 / 粒子层 /
  文字层（台词字幕、计数、块光标）
- 可用素材源（软件可内置自动取材）：D:\VM_share\manga、D:\VM_share\爬虫工作流、D:\图片\pixiv
- 本机代理：socks 10808 / http 10809
- 当前状态（2026-10-12）：DESIGN 到第 25 节（素材语义动效·文字剪影）；服务已关闭（8777 无监听）；改动均未 commit

## 七、由来
- 参考项目：MisakaZentai/world-execute-me-dsh-pv、MisakaZentai/world-search-you-dsh-pv
- 本仓库：ypsajyy0804/tui-world（fork 后大幅改造）
