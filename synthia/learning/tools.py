"""Learning Tools - এজেন্টের হাতে মেমোরি, স্কিল ও পুরনো-কথা-খোঁজার টুল।

মূল এজেন্ট এবং ব্যাকগ্রাউন্ড রিভিউয়ার দুজনেই এই টুলগুলো ব্যবহার করে।
"""
from __future__ import annotations

from typing import Any

from ..core.tools import tool
from .store import memory_store, session_store, skill_store

REVIEW_TOOLS = ("memory", "skills_list", "skill_view", "skill_manage")


@tool("memory",
      "Save durable notes. target='user' = who the user is (preferences, style, personal facts they "
      "stated); target='memory' = facts about the environment (paths, quirks, conventions). "
      "action: add | replace | remove (replace/remove need old_text = unique snippet of the entry).",
      {"action": {"type": "string", "enum": ["add", "replace", "remove"]},
       "target": {"type": "string", "enum": ["memory", "user"]},
       "content": {"type": "string"}, "old_text": {"type": "string"}},
      required=["action", "target"], category="learning")
def memory(action: str, target: str, content: str = "", old_text: str = "") -> str:
    return memory_store.apply(action, target, content, old_text)


@tool("skills_list", "List all learned skills (name + one-line description).", {}, category="learning")
def skills_list() -> str:
    return skill_store.index_text() or "No skills yet."


_VIEWED: set[str] = set()   # মূল এজেন্টের সেশনের জন্য (রিভিউয়ার নিজের সেট ব্যবহার করে)


@tool("skill_view",
      "Read a skill's full SKILL.md (or a supporting file via file_path like 'references/x.md'). "
      "Always do this before following or editing a skill.",
      {"name": {"type": "string"}, "file_path": {"type": "string"}},
      required=["name"], category="learning")
def skill_view(name: str, file_path: str = "") -> str:
    return skill_store.view(name, file_path)


@tool("skill_manage",
      "Create or improve a skill (a reusable procedure for a CLASS of tasks, written for this user). "
      "action: create (content = full SKILL.md starting with '---\\nname: <name>\\ndescription: <one line>\\n---') | "
      "patch (old_string -> new_string) | edit (rewrite SKILL.md) | write_file (file_path under "
      "references/, templates/ or scripts/). Deleting is not allowed.",
      {"action": {"type": "string", "enum": ["create", "patch", "edit", "write_file"]},
       "name": {"type": "string"}, "content": {"type": "string"},
       "old_string": {"type": "string"}, "new_string": {"type": "string"},
       "file_path": {"type": "string"}},
      required=["action", "name"], category="learning")
def skill_manage(action: str, name: str, content: str = "", old_string: str = "",
                 new_string: str = "", file_path: str = "") -> str:
    return skill_store.manage(action, name, content, old_string, new_string, file_path, viewed=None)


@tool("session_search",
      "Search ALL past conversations (full-text). Use when the user refers to something discussed "
      "before ('last week', 'remember when…'). Empty query = most recent messages.",
      {"query": {"type": "string"}}, category="learning")
def session_search(query: str = "") -> str:
    return session_store.search(query)


def dispatch_review(name: str, args: dict[str, Any], viewed: set[str]) -> str:
    """রিভিউয়ারের টুল-কল: read-before-write চালু।"""
    if name not in REVIEW_TOOLS:
        return f"ERROR: tool '{name}' is not available during review"
    args = args or {}
    if name == "memory":
        return memory_store.apply(args.get("action", ""), args.get("target", ""),
                                  args.get("content", ""), args.get("old_text", ""))
    if name == "skills_list":
        return skill_store.index_text() or "No skills yet."
    if name == "skill_view":
        res = skill_store.view(args.get("name", ""), args.get("file_path", "") or "")
        if not res.startswith("ERROR"):
            fp = args.get("file_path") or ""
            viewed.add(f"{args.get('name')}:{fp}" if fp else str(args.get("name")))
        return res
    return skill_store.manage(args.get("action", ""), args.get("name", ""), args.get("content", ""),
                              args.get("old_string", ""), args.get("new_string", ""),
                              args.get("file_path", "") or "", viewed=viewed)
