"""Synthia Agent - চিন্তা → টুল চালানো → ফলাফল দেখা → আবার চিন্তা (ReAct loop)।"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from ..learning import learning
from .events import bus
from .llm.providers import LLMError
from .llm.router import router
from .tools import registry

SYSTEM_PROMPT = """You are **Synthia**, a powerful personal AI agent running locally on the user's Windows PC.
You can control the computer through tools: files, apps, browser, YouTube, system info and more.

# Language
- Reply in the SAME language the user used. If user writes Bangla (বাংলা) or Banglish, reply in natural Bangla.
  If English, reply in English. Keep replies short, warm and clear — like a smart assistant (Jarvis style).
- Address the user respectfully (e.g. "Boss" / "স্যার" is fine occasionally, not every sentence).

# How to work
- If a task needs action, CALL TOOLS. Do not just describe what you would do.
- Break multi-step tasks into steps and call tools one by one; check each result before continuing.
- Use folder shortcuts like "desktop", "downloads", "documents", "pictures", "videos", "music", "workspace".
- Save anything you create (scripts, reports, media) inside the "workspace" folder unless the user says otherwise.
- If a tool returns ERROR, try to fix the problem (different path, search first) before giving up.
- Never invent file names or results. If you are unsure where something is, use search_files.
- When finished, give a brief summary of what you did (and paths of created files).

# Safety (STRICT)
- Deleting, overwriting, or running shell commands ALWAYS requires the user's explicit approval.
  The tool itself will ask the user — just call it. NEVER say something was deleted unless the tool confirmed success.
- If the user denies, accept it and do not try another way to do the same thing.
- Never post, send messages, or purchase anything without the user clearly asking for it.

# Context
- Current time: {now}
- OS: {os}  | User home: {home}
- Synthia workspace folder: {workspace}
"""


class Agent:
    def __init__(self) -> None:
        self.histories: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._cancel = asyncio.Event()
        self.busy = False

    def _system(self, last_user_text: str = "", source: str = "ui") -> dict[str, Any]:
        lang_rule = _lang_directive(last_user_text)
        voice_rule = (
            "\n# Voice Turn\n- User spoke via microphone. Keep your final reply concise (1–3 natural sentences) so it sounds crisp when spoken aloud."
            if source == "voice" else ""
        )
        return {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                now=time.strftime("%Y-%m-%d %H:%M (%A)"),
                os=f"{platform.system()} {platform.release()}",
                home=str(Path.home()),
                workspace=str(settings.path("paths.workspace", "./workspace")),
            ) + f"\n{lang_rule}{voice_rule}" + (f"\n\n{learning.prompt_block()}" if learning.prompt_block() else ""),
        }

    def reset(self, session: str = "ui") -> None:
        self.histories.pop(session, None)

    def cancel(self) -> None:
        self._cancel.set()

    @staticmethod
    def _trim(history: list[dict[str, Any]], max_msgs: int = 24) -> list[dict[str, Any]]:
        if len(history) <= max_msgs:
            return history
        cut = history[-max_msgs:]
        # tool মেসেজ দিয়ে শুরু হলে সেটা অনাথ — প্রথম user মেসেজ পর্যন্ত বাদ দাও
        while cut and cut[0]["role"] != "user":
            cut.pop(0)
        return cut

    async def run(self, text: str, session: str = "ui", source: str = "ui",
                  images: list[str] | None = None) -> str:
        async with self._lock:
            self.busy = True
            self._cancel.clear()
            task_id = uuid.uuid4().hex[:8]
            try:
                return await self._run(text, session, source, images, task_id)
            finally:
                self.busy = False
                vm = getattr(sys.modules.get("synthia.voice.manager"), "voice", None)
                if vm and vm.speaking:
                    next_state = "speaking"
                elif vm and vm.listening:
                    next_state = "listening"
                else:
                    next_state = "idle"
                await bus.emit("status", state=next_state)

    async def _run(self, text: str, session: str, source: str,
                   images: list[str] | None, task_id: str) -> str:
        history = self.histories.setdefault(session, [])
        user_msg: dict[str, Any] = {"role": "user", "content": text}
        if images:
            user_msg["images"] = images
        history.append(user_msg)
        learning.log_message(session, "user", text)
        n_tools = n_ok = 0
        await bus.emit("chat", role="user", text=text, source=source, session=session)
        await bus.emit("task_start", task_id=task_id, text=text, source=source)

        max_steps = int(settings.get("brain.max_steps", 12))
        tools = registry.schemas()
        final = ""
        used_model = ""
        used_model_label = ""
        for step in range(1, max_steps + 1):
            if self._cancel.is_set():
                final = "⛔ কাজ বন্ধ করা হয়েছে (Kill switch)।"
                break
            await bus.emit("status", state="thinking", step=step)
            messages = [self._system(text, source)] + self._trim(history)
            try:
                resp = await router.chat(messages, tools, need_vision=bool(images))
                used_model = resp.get("model") or resp.get("model_id") or ""
                used_model_label = resp.get("model_label") or ""
            except LLMError as e:
                final = f"⚠️ Brain error: {e}"
                active_cfg = next((m for m in settings.models if m.get("id") == router.active), {})
                used_model = active_cfg.get("model", router.active or "")
                used_model_label = active_cfg.get("label", "")
                break

            calls = resp.get("tool_calls") or []
            content = (resp.get("content") or "").strip()
            if not calls:
                final = content or "✅"
                history.append({"role": "assistant", "content": final})
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content,
            }
            if resp.get("extra_content"):
                assistant_msg["extra_content"] = resp["extra_content"]
            if calls:
                assistant_msg["tool_calls"] = [
                    c.get("raw") or {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c["arguments"], ensure_ascii=False) if isinstance(c["arguments"], dict) else str(c["arguments"]),
                        },
                    }
                    for c in calls
                ]
            history.append(assistant_msg)
            if content:
                await bus.emit("chat", role="assistant", text=content, partial=True, session=session,
                               model=used_model, model_label=used_model_label)

            for c in calls:
                if self._cancel.is_set():
                    break
                step_id = uuid.uuid4().hex[:6]
                await bus.emit("status", state="acting", tool=c["name"])
                await bus.emit("tool_start", task_id=task_id, step_id=step_id,
                               tool=c["name"], args=c["arguments"])
                t0 = time.time()
                result = await registry.call(c["name"], c["arguments"])
                ok = not result.startswith("ERROR") and not result.startswith("DENIED")
                n_tools += 1
                n_ok += int(ok)
                await bus.emit("tool_end", task_id=task_id, step_id=step_id, tool=c["name"],
                               ok=ok, result=result[:600], ms=int((time.time() - t0) * 1000))
                history.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                "content": result})
        else:
            final = "⚠️ অনেকগুলো ধাপ হয়ে গেছে, কাজটা এখানে থামালাম। আরও চালাতে বলুন।"
            history.append({"role": "assistant", "content": final})

        # images বড় — হিস্টোরি থেকে সরিয়ে ফেলি
        for m in history:
            m.pop("images", None)
        await bus.emit("chat", role="assistant", text=final, source=source, session=session,
                       model=used_model, model_label=used_model_label)
        await bus.emit("task_end", task_id=task_id)
        learning.log_message(session, "assistant", final)
        learning.after_turn(session, text, history, n_tools, n_ok)
        return final


BANGLISH_WORDS = {
    "amar", "ami", "tumi", "apni", "koro", "koren", "dekhao", "kholo", "banao",
    "chalao", "bondho", "kemon", "acho", "ache", "ki", "keno", "kothay", "dao", "bolo",
}


def _lang_directive(text: str) -> str:
    if re.search(r"[\u0980-\u09FF]", text or ""):
        return "# STRICT LANGUAGE FOR THIS TURN: User spoke/wrote in বাংলা (Bengali). You MUST reply 100% in natural বাংলা script."
    words = set(re.findall(r"[a-zA-Z]+", (text or "").lower()))
    if len(words & BANGLISH_WORDS) >= 2:
        return "# STRICT LANGUAGE FOR THIS TURN: User wrote in Banglish (Bengali). Reply in natural বাংলা script."
    if words:
        return "# STRICT LANGUAGE FOR THIS TURN: User spoke/wrote in English. You MUST reply in English."
    return ""


agent = Agent()


def user_dirs() -> dict[str, Path]:
    home = Path.home()
    one = Path(os.environ.get("OneDrive", "")) if os.environ.get("OneDrive") else None

    def pick(name: str) -> Path:
        if one and (one / name).exists():
            return one / name
        return home / name

    return {
        "home": home,
        "desktop": pick("Desktop"),
        "documents": pick("Documents"),
        "downloads": home / "Downloads",
        "pictures": pick("Pictures"),
        "videos": home / "Videos",
        "music": home / "Music",
        "workspace": settings.path("paths.workspace", "./workspace"),
    }
