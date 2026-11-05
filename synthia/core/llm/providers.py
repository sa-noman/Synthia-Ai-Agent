"""LLM Providers - Ollama (লোকাল) ও OpenAI-compatible (ক্লাউড ফ্রি API) একই ফরম্যাটে।

অভ্যন্তরীণ মেসেজ ফরম্যাট (OpenAI স্টাইল):
  {"role": "user"|"assistant"|"system"|"tool", "content": str,
   "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": "<json str>"}}],
   "tool_call_id": str, "name": str, "images": [base64...]}

রেসপন্স ফরম্যাট:
  {"content": str, "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx


class LLMError(Exception):
    def __init__(self, msg: str, *, rate_limited: bool = False, network: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.rate_limited = rate_limited
        self.network = network
        self.retry_after = retry_after


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {"value": v}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {}


class BaseProvider:
    def __init__(self, cfg: dict[str, Any], api_key: str = "") -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg["model"]
        self.base_url = cfg["base_url"].rstrip("/")

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                   temperature: float = 0.3) -> dict[str, Any]:
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            mm: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("images"):
                mm["images"] = m["images"]
            if m.get("tool_calls"):
                mm["tool_calls"] = [
                    {"function": {"name": tc["function"]["name"],
                                  "arguments": _parse_args(tc["function"]["arguments"])}}
                    for tc in m["tool_calls"]
                ]
            if m["role"] == "tool":
                mm["tool_name"] = m.get("name", "")
            out.append(mm)
        return out

    async def chat(self, messages, tools, temperature=0.3):
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert(messages),
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_ctx": int(self.cfg.get("num_ctx", 8192))},
        }
        if tools:
            body["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as c:
                r = await c.post(f"{self.base_url}/api/chat", json=body)
        except httpx.ConnectError as e:
            raise LLMError("Ollama চালু নেই (Ollama app চালু করুন)", network=True) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama error: {e}", network=True) from e
        if r.status_code != 200:
            raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        msg = r.json().get("message", {})
        calls = [
            {"id": "call_" + uuid.uuid4().hex[:8],
             "name": tc["function"]["name"],
             "arguments": _parse_args(tc["function"].get("arguments"))}
            for tc in (msg.get("tool_calls") or [])
        ]
        return {"content": msg.get("content") or "", "tool_calls": calls}


class OpenAICompatProvider(BaseProvider):
    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            mm: dict[str, Any] = {"role": m["role"]}
            content = m.get("content") or ""
            if m.get("images") and m["role"] == "user":
                parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
                for b64 in m["images"]:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:image/png;base64,{b64}"}})
                mm["content"] = parts
            else:
                mm["content"] = content
            if m.get("tool_calls"):
                mm["tool_calls"] = m["tool_calls"]
                if not content:
                    mm["content"] = None
            if m["role"] == "tool":
                mm["tool_call_id"] = m.get("tool_call_id", "")
                mm["name"] = m.get("name", "")
            out.append(mm)
        return out

    async def chat(self, messages, tools, temperature=0.3):
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert(messages),
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost/synthia"
            headers["X-Title"] = "Synthia"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=8)) as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"Network error: {e}", network=True) from e
        if r.status_code == 429 or (r.status_code == 403 and "quota" in r.text.lower()):
            ra = r.headers.get("retry-after")
            raise LLMError(f"Rate limit / quota শেষ ({r.status_code})", rate_limited=True,
                           retry_after=float(ra) if ra and ra.replace('.', '', 1).isdigit() else None)
        if r.status_code >= 500:
            raise LLMError(f"Server error {r.status_code}", network=True)
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = [
            {"id": tc.get("id") or "call_" + uuid.uuid4().hex[:8],
             "name": tc["function"]["name"],
             "arguments": _parse_args(tc["function"].get("arguments"))}
            for tc in (msg.get("tool_calls") or [])
        ]
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return {"content": content, "tool_calls": calls}


PROVIDERS = {"ollama": OllamaProvider, "openai_compat": OpenAICompatProvider}
