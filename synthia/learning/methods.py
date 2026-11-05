"""Learning Methods - প্লাগেবল শেখার পদ্ধতি।

এখন আছে: HermesReviewMethod (Hermes-এর "closed learning loop": কাজ শেষে ব্যাকগ্রাউন্ডে রিভিউ →
মেমোরি/স্কিল আপডেট)। ভবিষ্যতে OpenClaw বা অন্য কোনো পদ্ধতি শেখাতে চাইলে:

    class MyMethod(LearningMethod):
        name = "my_method"
        async def on_turn_end(self, ctx): ...

    register_method(MyMethod())

তারপর config/settings.yaml-এর learning.methods তালিকায় নামটা যোগ করলেই চালু।
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import ROOT, settings
from ..core.events import bus
from ..core.llm.providers import LLMError
from ..core.llm.router import router
from ..core.tools import registry
from . import prompts
from .store import skill_store
from .tools import REVIEW_TOOLS, dispatch_review

LOG_FILE = ROOT / "logs" / "learning.log"

# ইউজার স্পষ্টভাবে কিছু শেখাতে/সংশোধন করতে চাইলে সাথে সাথে রিভিউ চালু হবে
EXPLICIT_SIGNAL = re.compile(
    r"(মনে রাখ|মনে রেখ|সবসময়|সব সময়|আর কখনো|আর কক্ষনো|এভাবে না|ভুল করেছ|ভুল হয়েছ|"
    r"remember|always|from now on|never do|stop doing|don't do that|that's wrong|too long|too verbose)",
    re.IGNORECASE)


@dataclass
class TurnContext:
    session: str
    user_text: str
    history: list[dict[str, Any]]          # এই সেশনের পুরো হিস্টোরি
    tool_calls: int                        # এই টার্নে কতগুলো টুল চলেছে
    ok_tools: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class LearningMethod:
    name = "base"

    async def on_turn_end(self, ctx: TurnContext) -> None:  # noqa: D401
        raise NotImplementedError


METHODS: dict[str, LearningMethod] = {}


def register_method(m: LearningMethod) -> None:
    METHODS[m.name] = m


def _log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def digest(history: list[dict[str, Any]], tail: int = 24, cap: int = 1500) -> str:
    """হিস্টোরিকে রিভিউয়ারের জন্য পড়ার-যোগ্য ট্রান্সক্রিপ্টে রূপান্তর।"""
    lines: list[str] = []
    for m in history[-tail:]:
        role = m.get("role")
        text = str(m.get("content") or "").strip()
        if role == "user" and text:
            lines.append(f"[USER] {text[:cap]}")
        elif role == "assistant":
            for c in m.get("tool_calls") or []:
                fn = c.get("function", {})
                lines.append(f"[AGENT CALLS] {fn.get('name')}({str(fn.get('arguments'))[:200]})")
            if text:
                lines.append(f"[AGENT] {text[:cap]}")
        elif role == "tool":
            lines.append(f"[TOOL RESULT {m.get('name')}] {text[:300]}")
    return "\n".join(lines)


class HermesReviewMethod(LearningMethod):
    """Hermes-এর background review: ট্রান্সক্রিপ্ট পড়ে মেমোরি + স্কিল আপডেট করে।"""
    name = "hermes_review"

    def __init__(self) -> None:
        self.turns_since_memory = 0
        self.tools_since_skill = 0
        self.running = False

    def _cfg(self, key: str, default: Any) -> Any:
        return settings.get(f"learning.{key}", default)

    async def on_turn_end(self, ctx: TurnContext) -> None:
        self.turns_since_memory += 1
        self.tools_since_skill += ctx.tool_calls
        explicit = bool(EXPLICIT_SIGNAL.search(ctx.user_text or ""))
        do_memory = explicit or self.turns_since_memory >= int(self._cfg("memory_interval", 6))
        do_skill = explicit or self.tools_since_skill >= int(self._cfg("skill_interval", 6))
        if not (do_memory or do_skill) or self.running:
            return
        if do_memory:
            self.turns_since_memory = 0
        if do_skill:
            self.tools_since_skill = 0
        self.running = True
        try:
            await self._review(ctx, do_skill)
        finally:
            self.running = False

    async def _review(self, ctx: TurnContext, with_skills: bool) -> None:
        from ..core.agent import agent  # দেরিতে ইম্পোর্ট (circular এড়াতে)
        transcript = digest(ctx.history)
        if not transcript:
            return
        prompt = prompts.COMBINED_REVIEW_PROMPT if with_skills else prompts.MEMORY_ONLY_PROMPT
        allowed = REVIEW_TOOLS if with_skills else ("memory",)
        schemas = [t for t in registry.schemas() if t["function"]["name"] in allowed]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompts.REVIEWER_SYSTEM},
            {"role": "user", "content": f"--- CONVERSATION TRANSCRIPT ---\n{transcript}\n--- END ---\n\n{prompt}"},
        ]
        viewed: set[str] = set()
        actions: list[str] = []
        await bus.emit("learning", state="reviewing")
        for _ in range(int(self._cfg("review_max_steps", 8))):
            if agent.busy:  # ইউজার নতুন কাজ দিলে রিভিউ থামাও (লোকাল GPU ফাঁকা রাখতে)
                _log("review aborted: agent busy")
                await bus.emit("learning", state="idle")
                return
            try:
                resp = await router.chat(messages, schemas)
            except LLMError as e:
                _log(f"review LLM error: {e}")
                break
            calls = resp.get("tool_calls") or []
            content = (resp.get("content") or "").strip()
            if not calls:
                if content and "nothing to save" not in content.lower():
                    actions.append(content[:200])
                break
            messages.append({
                "role": "assistant", "content": content,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"],
                                             "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                               for c in calls]})
            for c in calls:
                args = c["arguments"] if isinstance(c["arguments"], dict) else {}
                result = dispatch_review(c["name"], args, viewed)
                if result.startswith("OK"):
                    actions.append(f"{c['name']}:{args.get('action', '')} {args.get('name') or args.get('target') or ''} — {result[:80]}")
                messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": result})
        if actions:
            summary = "; ".join(actions)
            _log(f"session={ctx.session} learned: {summary}")
            await bus.emit("learning", state="learned", text=summary[:400],
                           skills=len(skill_store.list()))
        else:
            _log(f"session={ctx.session} nothing to save")
        await bus.emit("learning", state="idle")


register_method(HermesReviewMethod())
