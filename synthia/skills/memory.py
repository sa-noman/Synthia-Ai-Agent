"""Memory Skill - আপনার পছন্দ, তথ্য ও নোট মনে রাখা (লোকাল JSON)।"""
from __future__ import annotations

import json
import time

from ..config import ROOT
from ..core.tools import tool

MEM_FILE = ROOT / "synthia_data" / "memory.json"


def _load() -> list[dict]:
    if MEM_FILE.exists():
        try:
            return json.loads(MEM_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save(items: list[dict]) -> None:
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


@tool("remember", "Save a fact/preference about the user for the future (e.g. 'User likes lo-fi music').",
      {"note": {"type": "string"}}, required=["note"], category="memory")
def remember(note: str) -> str:
    items = _load()
    items.append({"note": note, "ts": time.strftime("%Y-%m-%d %H:%M")})
    _save(items)
    return f"OK: remembered ({len(items)} notes total)"


@tool("recall", "Search saved memory notes. Leave query empty to list recent notes.",
      {"query": {"type": "string"}}, category="memory")
def recall(query: str = "") -> str:
    items = _load()
    q = query.lower().strip()
    hits = [i for i in items if q in i["note"].lower()] if q else items[-20:]
    return "\n".join(f"- [{i['ts']}] {i['note']}" for i in hits) or "No memory found."


def memory_count() -> int:
    return len(_load())
