"""Tool Registry - Synthia-র "হাত"। প্রতিটি স্কিল এখানে টুল রেজিস্টার করে।

নতুন টুল যোগ করার উদাহরণ (synthia/skills/ ফোল্ডারের যেকোনো ফাইলে):

    from synthia.core.tools import tool

    @tool("say_hello", "Say hello to someone",
          {"name": {"type": "string", "description": "person name"}},
          required=["name"])
    def say_hello(name: str) -> str:
        return f"Hello {name}"
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import pkgutil
import traceback
from dataclasses import dataclass
from typing import Any, Callable

SAFE = "safe"                # সরাসরি চলবে
SENSITIVE = "sensitive"      # সরাসরি চলবে, কিন্তু লগে হাইলাইট হবে
DESTRUCTIVE = "destructive"  # ডিলিট/ওভাররাইট/শেল -> টুলের ভেতরেই অনুমতি নেওয়া বাধ্যতামূলক


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str]
    handler: Callable[..., Any]
    risk: str = SAFE
    category: str = "general"

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        self.tools[t.name] = t

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self.tools.values()]

    def by_category(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for t in self.tools.values():
            out.setdefault(t.category, []).append(t.name)
        return out

    async def call(self, name: str, args: dict[str, Any] | str | None) -> str:
        t = self.tools.get(name)
        if not t:
            return f"ERROR: unknown tool '{name}'. Available: {', '.join(self.tools)}"
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                return f"ERROR: arguments for {name} are not valid JSON: {args[:200]}"
        args = args or {}
        # অজানা প্যারামিটার বাদ দেওয়া (ছোট মডেল মাঝে মাঝে বানিয়ে ফেলে)
        sig = inspect.signature(t.handler)
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            args = {k: v for k, v in args.items() if k in sig.parameters}
        missing = [r for r in t.required if r not in args]
        if missing:
            return f"ERROR: missing required argument(s) for {name}: {missing}"
        try:
            if inspect.iscoroutinefunction(t.handler):
                result = await t.handler(**args)
            else:
                result = await asyncio.to_thread(t.handler, **args)
        except Exception as e:  # noqa: BLE001
            return f"ERROR while running {name}: {e}\n{traceback.format_exc(limit=2)}"
        if isinstance(result, (dict, list)):
            result = json.dumps(result, ensure_ascii=False, indent=1, default=str)
        result = str(result)
        if len(result) > 12000:
            result = result[:12000] + "\n...[truncated]"
        return result


registry = ToolRegistry()


def tool(name: str, description: str, parameters: dict[str, Any] | None = None,
         required: list[str] | None = None, risk: str = SAFE, category: str = "general"):
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(Tool(name, description, parameters or {}, required or [], fn, risk, category))
        return fn
    return deco


def load_skills() -> None:
    """synthia/skills/ ফোল্ডারের সব স্কিল অটোমেটিক লোড করে।"""
    from .. import skills
    for mod in pkgutil.iter_modules(skills.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{skills.__name__}.{mod.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[skills] failed to load {mod.name}: {e}")
