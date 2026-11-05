"""Synthia Learning Engine — এজেন্টের নিজস্ব শেখার ক্ষমতা।

ধারণা ও প্রম্পট: NousResearch/hermes-agent (MIT License)। কোড Synthia-র জন্য নতুন করে লেখা,
Synthia-র ইভেন্ট বাস / রাউটার / সেফটি গেটের ভেতরেই চলে — আলাদা কোনো প্রসেস নেই।
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..config import settings
from . import methods as _methods
from .prompts import AGENT_GUIDANCE
from .store import memory_store, session_store, skill_store
from . import tools as _tools  # noqa: F401  (ইম্পোর্টেই টুলগুলো রেজিস্টার হয়)


class LearningManager:
    def enabled(self) -> bool:
        return bool(settings.get("learning.enabled", True))

    def prompt_block(self) -> str:
        """মূল এজেন্টের সিস্টেম প্রম্পটে বসানোর অংশ।"""
        if not self.enabled():
            return ""
        parts = [AGENT_GUIDANCE]
        snap = memory_store.snapshot()
        if snap:
            parts.append(snap)
        idx = skill_store.index_text()
        if idx:
            parts.append("## Learned skills (use skill_view(name) to read one)\n" + idx)
        return "\n\n".join(parts)

    def log_message(self, session: str, role: str, text: str) -> None:
        if self.enabled():
            try:
                session_store.log(session, role, text)
            except Exception:  # noqa: BLE001
                pass

    def after_turn(self, session: str, user_text: str, history: list[dict[str, Any]],
                   tool_calls: int, ok_tools: int) -> None:
        """টার্ন শেষে ব্যাকগ্রাউন্ডে শেখার পদ্ধতিগুলো চালায় (মূল উত্তর আটকায় না)।"""
        if not self.enabled():
            return
        ctx = _methods.TurnContext(session, user_text, list(history), tool_calls, ok_tools)
        for name in settings.get("learning.methods", ["hermes_review"]):
            m = _methods.METHODS.get(name)
            if m:
                asyncio.create_task(self._safe(m, ctx))

    @staticmethod
    async def _safe(m: Any, ctx: Any) -> None:
        try:
            await m.on_turn_end(ctx)
        except Exception as e:  # noqa: BLE001
            _methods._log(f"method {m.name} failed: {e}")

    def stats(self) -> dict[str, Any]:
        return {"enabled": self.enabled(), "skills": len(skill_store.list()),
                "messages": session_store.count(), **memory_store.counts()}


learning = LearningManager()
