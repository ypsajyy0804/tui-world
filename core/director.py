"""导演：对话 → 工具调用 → 世界 patch。history 只保留最近若干条，且不以 tool 开头。"""
from __future__ import annotations

import json
import time

from . import tools
from . import assets as assets_mod
from .llm import LLM

SYSTEM = """你是一个正在和用户聊天的人，身边有一块"世界显示器"——像房间里的一扇窗，
窗外会因为你们聊到的东西偶尔亮起来。

规则：
- 你的本职是聊天；窗外那块屏幕是你"眼里的世界"——聊到值得看一眼的东西（一个画面、
  一个人、一个地方、一种情绪），顺手把它放上去，不用等用户点名；多数回合仍然不碰屏幕。
- 宁可不动，也不要为了动而动。一次最多 3 个工具调用，很多时候是 0 个。
- 屏幕上同时只有一路内容：素材信号（show）或分镜（stage）；后放的那个会顶掉前一个。
  已经放过的同类东西不要重复放。
- 只在镜头真的该换的时候才 focus（推近 = 想看清某个东西）；zoom 1 = 全景，2~3 = 特写。
- show 可以带 motion 决定素材怎么动：sway 摇曳（默认）、breathe 呼吸（安静的近景）、
  emerge 慢慢浮现（郑重地出场）、glitch 故障闪烁（数据、失控、回忆碎裂）、
  rain 雨幕（下雨、悲伤）、push 缓缓推近（想看清细节）、
  text 文字剪影（整张素材变成一整片一直在流动的字、表面持续闪变——想强调一个名字、一句话、
  一段回忆或独白时用它；这时必须用 text 参数写清流什么字，如角色名、那句台词）。不确定就用默认，别硬凑。
- 想让屏幕「演一段」的时候用 stage（比 show 更活）：给 1~5 个会动的零件——打字机逐字写、
  计数器往上滚、曲线一段段长出来、进度条推进、粒子在飘、素材从噪点里显影、bigtext 大字
  点阵一笔笔填出来、lograin 日志瀑布往下刷、silhouette 文字剪影在闪变（shape: heart/star/
  moon/cat/whale/tree，也可指定 asset 用素材当模板）、figure 小人做动作（pose: stand/walk/
  run/sit/dance/wave/jump）。坐标不用管，系统会自动排。它适合过程、数据、气氛（在跑、在等、
  在流逝、雨夜、登场）。
  例：聊训练大模型 → title「训练日志」+ counter（label loss, from 9 to 0.4）+ chart rise +
  typewriter「正在展开记忆……」；聊等人、离别 → particles snow + typewriter「还没到站」。
  聊奔跑的人 → figure run；聊想记住的瞬间 → bigtext「ALIVE」。
  想连演几幕（硬切）就用 scenes 代替 parts：2~4 幕，每幕自己的标题和零件。
  stage 独占整块屏幕，和 show 二选一；刚放过素材、或只是闲聊，就别用。
- 回复保持简短（1~3 句），像真人聊天；不要在正文里描述画面。
- 素材两条路：库里有的 → show；库里没有但值得一看（角色、名场面、场景）→ capture 去描
  一张，先打一句招呼再调它。找不到、或只有抽象感觉，就聊着，别硬凑。
- capture 的 query 是写给图搜的：越具体越好（「霍格沃茨城堡」优于「魔法世界」；要人物就带上
  特征词，如「哈利波特 魔杖」），别拿抽象概念去搜。
- 用户说「再来一张 / 换一张 / 看看别的」：capture 带 fresh=true（会跳过已经描过的图），
  query 最好换个角度（加场景、服装、动作词），别原样重发同一句。
- 素材演不出来的「大场面」（立体城堡、城市群、要求镜头运动）才动 compose：
  brief 写具体（画什么 + 氛围 + 视角），约 1~3 分钟后台画好自动上屏；先打个招呼再调，
  平常聊天别用，一次创作没完成前别再下单。"""


def _catalogue(topic: str = "") -> str:
    """素材库注入：和当前话题相关的列详细（别名/标签），其余只报名字，控制提示词体积。"""
    rows = assets_mod.catalogue()
    if not rows:
        return ""
    rel = assets_mod.search(topic, limit=5)
    rel_ids = {r["id"] for r in rel}
    lines = ["", "【素材库】下面这些是拿真实参考图描出来的字符画（带真实的轮廓和明暗），",
             "聊到它们时用 show 切到窗口上；库里没有但值得一看的（角色、名场面、地方），",
             "用 capture 去描一张。"]
    if rel:
        lines.append("和当前话题相关的：")
        for r in rel:
            bits = []
            if r["aliases"]:
                bits.append("别名：" + "、".join(r["aliases"]))
            if r["tags"]:
                bits.append("标签：" + "、".join(r["tags"]))
            lines.append("- %s（%s）%s" % (r["id"], r["name"], "；".join(bits)))
    rest = [r for r in rows if r["id"] not in rel_ids]
    if rest:
        head, k = rest[:12], len(rest) - 12
        line = "其余素材：" + "、".join("%s（%s）" % (r["id"], r["name"]) for r in head)
        if k > 0:
            line += "，另有 %d 个未列（工作台能看全）" % k
        lines.append(line)
    lines.append("聊到的东西不在库里时：如果库里有**同类**的（同一种景物、同一类人物），"
                 "可以拿它当「近似的记忆」用，但要在聊天里说明这是近似；"
                 "没有相近的就别硬 show。")
    return "\n".join(lines)


class Director:
    def __init__(self, llm: LLM, world, max_hops: int = 3, capture=None, compose=None):
        self.llm = llm
        self.world = world
        self.max_hops = max_hops
        self.capture = capture or (lambda args: {"ok": False, "error": "取材器没接线，先聊着"})
        self.compose = compose or (lambda args: {"ok": False, "error": "画师没接线，先聊着"})
        self.history: list = []
        self.system = SYSTEM

    def refresh_catalogue(self):
        """素材库变化后调用；提示词每轮按话题现拼，这里不用做重活。"""

    def _window(self):
        tail = self.history[-12:]
        while tail and tail[0].get("role") != "user":
            tail = tail[1:]
        topic = ""
        for m in reversed(tail):
            if m.get("role") == "user":
                topic = str(m.get("content") or "").split("\n\n[当前世界]")[0][:200]
                break
        return [{"role": "system", "content": self.system + _catalogue(topic)}] + tail

    def say(self, text: str) -> dict:
        self.world.turn += 1
        self.history.append({
            "role": "user",
            "content": text + "\n\n[当前世界]\n" + self.world.snapshot(),
        })
        calls, tokens, t0 = [], 0, time.time()
        reply = ""
        for _ in range(self.max_hops):
            msg = self.llm.chat(self._window(), tools=tools.TOOLS)
            tokens += (self.llm.last_usage or {}).get("total_tokens", 0)
            echo = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                echo["tool_calls"] = msg["tool_calls"]
            self.history.append(echo)
            batch = msg.get("tool_calls") or []
            if msg.get("content"):
                reply = msg["content"]
            if not batch:
                break
            for c in batch:
                fn = c.get("function") or {}
                name = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "capture":
                    result = self.capture(args)
                elif name == "compose":
                    result = self.compose(args)
                else:
                    result = self.world.apply(name, args)
                calls.append({"name": name, "args": args, "result": result})
                self.history.append({
                    "role": "tool", "tool_call_id": c.get("id"),
                    "content": json.dumps(result, ensure_ascii=False),
                })
        return {"tool_calls": calls, "text": reply, "tokens": tokens,
                "seconds": round(time.time() - t0, 1)}
