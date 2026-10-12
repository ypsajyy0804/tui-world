"""模型调用：urllib + 重试，不引入额外依赖。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, key: str, base: str = "https://api.deepseek.com",
                 model: str = "deepseek-v4-flash", timeout: int = 180):
        if not key:
            raise LLMError("缺少 DEEPSEEK_API_KEY（写进 .env 或设环境变量）")
        self.key = key
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_usage: dict = {}

    def chat(self, messages, tools=None, temperature: float = 0.7,
             max_tokens: int = 2000, retries: int = 4) -> dict:
        """返回 assistant 的 message 字典。失败抛 LLMError。"""
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        data = json.dumps(body).encode("utf8")
        last = "unknown"
        for attempt in range(retries):
            req = urllib.request.Request(self.base + "/v1/chat/completions", data=data, method="POST")
            req.add_header("Authorization", "Bearer " + self.key)
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode("utf8"))
                self.last_usage = payload.get("usage") or {}
                self.last_finish = (payload.get("choices") or [{}])[0].get("finish_reason")
                return (payload.get("choices") or [{}])[0].get("message") or {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf8", "replace")[:400]
                if e.code in (429, 500, 502, 503):
                    last = "HTTP %s %s" % (e.code, detail)
                else:
                    raise LLMError("HTTP %s %s" % (e.code, detail))
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, e)
            time.sleep(0.8 * (attempt + 1))
        raise LLMError("连续 %d 次失败：%s" % (retries, last))
