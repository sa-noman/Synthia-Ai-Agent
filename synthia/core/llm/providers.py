"""LLM Providers - Ollama (লোকাল) ও OpenAI-compatible (ক্লাউড ফ্রি API) একই ফরম্যাটে।

অভ্যন্তরীণ মেসেজ ফরম্যাট (OpenAI স্টাইল):
  {"role": "user"|"assistant"|"system"|"tool", "content": str,
   "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": "<json str>"}}],
   "tool_call_id": str, "name": str, "images": [base64...]}

রেসপন্স ফরম্যাট:
  {"content": str, "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx


def _find_ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    candidate = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return str(candidate) if candidate.is_file() else None


async def ensure_ollama_running(base_url: str = "http://127.0.0.1:11434") -> bool:
    """লোকাল Ollama সার্ভার চালু আছে কি না দেখে; বন্ধ থাকলে ব্যাকগ্রাউন্ডে `ollama serve` চালু করে।"""
    url = base_url.rstrip("/")
    tags_url = f"{url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=1.0)) as c:
            r = await c.get(tags_url)
            if r.status_code == 200:
                return True
    except httpx.HTTPError:
        pass

    exe = _find_ollama_exe()
    if not exe:
        return False

    flags = 0
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError:
        return False

    for _ in range(20):
        await asyncio.sleep(0.4)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=1.0)) as c:
                r = await c.get(tags_url)
                if r.status_code == 200:
                    return True
        except httpx.HTTPError:
            pass
    return False


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
        self.api_key = str(api_key or "").strip()
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

        async def _send_chat() -> httpx.Response:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as c:
                resp = await c.post(f"{self.base_url}/api/chat", json=body)
                if resp.status_code == 400 and body.get("tools") and "tool" in resp.text.lower():
                    body.pop("tools", None)
                    resp = await c.post(f"{self.base_url}/api/chat", json=body)
                if resp.status_code == 400 and "think" in resp.text.lower():
                    body.pop("think", None)
                    resp = await c.post(f"{self.base_url}/api/chat", json=body)
                return resp

        try:
            try:
                r = await _send_chat()
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if await ensure_ollama_running(self.base_url):
                    r = await _send_chat()
                else:
                    raise e
        except httpx.ConnectError as e:
            raise LLMError("Ollama চালু নেই (Ollama app চালু করুন)", network=True) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama error: {e}", network=True) from e
        if r.status_code != 200:
            raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        try:
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Ollama থেকে সঠিক JSON রেসপন্স আসেনি: {r.text[:150]}") from e
        msg = payload.get("message", {}) if isinstance(payload, dict) else {}
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
            content = m.get("content")
            if content is None:
                content = ""
            if m.get("images") and m["role"] == "user":
                parts: list[dict[str, Any]] = [{"type": "text", "text": str(content)}]
                for b64 in m["images"]:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:image/png;base64,{b64}"}})
                mm["content"] = parts
            else:
                mm["content"] = content
            if m.get("extra_content"):
                mm["extra_content"] = m["extra_content"]
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
        if "generativelanguage.googleapis.com" in self.base_url:
            headers["x-goog-api-key"] = self.api_key
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost/synthia"
            headers["X-Title"] = "Synthia"
        if "models.github.ai" in self.base_url or "azure.com" in self.base_url:
            headers["User-Agent"] = "Synthia-AI-Agent"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=6.0, read=30.0)) as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"Network error: {e}", network=True) from e
        if r.status_code in (429, 402) or (r.status_code == 403 and any(w in r.text.lower() for w in ("quota", "limit", "rate", "exceeded", "credit"))):
            ra = r.headers.get("retry-after")
            raise LLMError(f"Rate limit / quota শেষ ({r.status_code})", rate_limited=True,
                           retry_after=float(ra) if ra and ra.replace('.', '', 1).isdigit() else 90.0)
        if r.status_code >= 500:
            raise LLMError(f"Server error {r.status_code}", network=True)
        if r.status_code != 200:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except Exception as e:  # noqa: BLE001
            if "models.github.ai" in self.base_url:
                raise LLMError(
                    "GitHub Models (models.github.ai) সার্ভিসটি GitHub বন্ধ করে দিয়েছে (কোনো AI রেসপন্স দিচ্ছে না)। "
                    "অনুগ্রহ করে Google AI Studio, OpenRouter, Groq বা Local মডেল ব্যবহার করুন।"
                ) from e
            raise LLMError(f"API থেকে সঠিক JSON রেসপন্স আসেনি: {r.text[:150]}") from e
        if not isinstance(data, dict):
            raise LLMError(f"API থেকে সঠিক JSON রেসপন্স আসেনি: {r.text[:150]}")
        if data.get("error"):
            err = data["error"]
            err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LLMError(f"API error: {err_msg}")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"API খালি রেসপন্স দিয়েছে: {r.text[:150]}")
        choice = choices[0]
        msg = choice.get("message") or {}
        raw_tool_calls = msg.get("tool_calls") or []
        calls = [
            {"id": tc.get("id") or "call_" + uuid.uuid4().hex[:8],
             "name": tc["function"]["name"],
             "arguments": _parse_args(tc["function"].get("arguments")),
             "raw": tc}
            for tc in raw_tool_calls
        ]
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        res = {"content": content, "tool_calls": calls}
        if msg.get("extra_content"):
            res["extra_content"] = msg["extra_content"]
        return res


PROVIDERS = {"ollama": OllamaProvider, "openai_compat": OpenAICompatProvider}
