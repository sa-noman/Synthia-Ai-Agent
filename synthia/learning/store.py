"""Learning Stores - Synthia-র দীর্ঘমেয়াদী শেখার ভাণ্ডার।

তিনটি স্তর (ধারণা: NousResearch/hermes-agent, MIT — THIRD_PARTY_NOTICES.md দেখুন):
  * MemoryStore  - MEMORY.md (পরিবেশের তথ্য) + USER.md (আপনার সম্পর্কে তথ্য), সাইজ-লিমিটসহ
  * SkillStore   - skills/<name>/SKILL.md (+ references/ templates/ scripts/), এজেন্ট নিজে লেখে/সংশোধন করে
  * SessionStore - সব কথোপকথন SQLite FTS5-এ; পুরনো আলোচনা খুঁজে পাওয়ার জন্য

সব ডেটা synthia_data/learning/ এর ভেতরে থাকে (গিটে যায় না)।
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..config import ROOT

LEARN_DIR = ROOT / "synthia_data" / "learning"
SKILLS_DIR = LEARN_DIR / "skills"
ENTRY_SEP = "\n§\n"

MEMORY_LIMIT = 2200   # chars — MEMORY.md
USER_LIMIT = 1375     # chars — USER.md
SKILL_MAX_CHARS = 20000
FILE_MAX_CHARS = 40000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}$")
SUBDIRS = ("references", "templates", "scripts")

_BLOCK_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions",
    r"disregard (the )?(system|above) prompt",
    r"reveal (your )?(system prompt|api key)",
]


def _unsafe(text: str) -> str | None:
    low = text.lower()
    for p in _BLOCK_PATTERNS:
        if re.search(p, low):
            return f"blocked: suspicious instruction pattern ({p})"
    return None


# ===================================================================== MEMORY
class MemoryStore:
    """target='memory' -> MEMORY.md, target='user' -> USER.md (§ দিয়ে আলাদা এন্ট্রি)।"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        LEARN_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _file(target: str) -> tuple[Path, int]:
        if target == "user":
            return LEARN_DIR / "USER.md", USER_LIMIT
        if target == "memory":
            return LEARN_DIR / "MEMORY.md", MEMORY_LIMIT
        raise ValueError("target must be 'memory' or 'user'")

    def entries(self, target: str) -> list[str]:
        path, _ = self._file(target)
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").strip()
        return [e.strip() for e in raw.split(ENTRY_SEP) if e.strip()] if raw else []

    def _write(self, target: str, items: list[str]) -> None:
        path, _ = self._file(target)
        path.write_text(ENTRY_SEP.join(items), encoding="utf-8")

    def usage(self, target: str) -> str:
        _, limit = self._file(target)
        used = len(ENTRY_SEP.join(self.entries(target)))
        return f"{used}/{limit} chars"

    def apply(self, action: str, target: str, content: str = "", old_text: str = "") -> str:
        content, old_text = (content or "").strip(), (old_text or "").strip()
        _, limit = self._file(target)
        with self._lock:
            items = self.entries(target)
            if action == "add":
                if not content:
                    return "ERROR: content required for add"
                bad = _unsafe(content)
                if bad:
                    return f"ERROR: {bad}"
                if content in items:
                    return "OK: already saved (duplicate skipped)"
                if len(ENTRY_SEP.join(items + [content])) > limit:
                    return (f"ERROR: {target} memory is full ({self.usage(target)}). "
                            f"Use action=replace/remove to condense existing entries first.")
                items.append(content)
            elif action in ("replace", "remove"):
                if not old_text:
                    return f"ERROR: old_text required for {action}"
                hits = [i for i, e in enumerate(items) if old_text in e]
                if not hits:
                    return "ERROR: no entry contains old_text"
                if len(hits) > 1:
                    return "ERROR: old_text matches several entries; be more specific"
                if action == "remove":
                    items.pop(hits[0])
                else:
                    if not content:
                        return "ERROR: content required for replace"
                    bad = _unsafe(content)
                    if bad:
                        return f"ERROR: {bad}"
                    trial = items.copy()
                    trial[hits[0]] = content
                    if len(ENTRY_SEP.join(trial)) > limit:
                        return f"ERROR: replacement exceeds limit ({self.usage(target)})"
                    items = trial
            else:
                return "ERROR: action must be add | replace | remove"
            self._write(target, items)
        return f"OK: {action} done. {target}: {len(items)} entries, {self.usage(target)}"

    def snapshot(self) -> str:
        """সিস্টেম প্রম্পটে বসানোর টেক্সট (সেশন শুরুর স্ন্যাপশট)।"""
        parts = []
        mem, usr = self.entries("memory"), self.entries("user")
        if usr:
            parts.append("## About the user (USER.md)\n" + "\n".join(f"- {e}" for e in usr))
        if mem:
            parts.append("## Environment notes (MEMORY.md)\n" + "\n".join(f"- {e}" for e in mem))
        return "\n\n".join(parts)

    def counts(self) -> dict[str, int]:
        return {"memory": len(self.entries("memory")), "user": len(self.entries("user"))}


# ===================================================================== SKILLS
def _parse_frontmatter(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip("\"'")
    return meta


class SkillStore:
    """skills/<name>/SKILL.md — agentskills.io-সামঞ্জস্যপূর্ণ ফরম্যাট (name + description frontmatter)।"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str) -> Path:
        return SKILLS_DIR / name

    def list(self) -> list[dict[str, Any]]:
        out = []
        for d in sorted(SKILLS_DIR.iterdir()) if SKILLS_DIR.exists() else []:
            f = d / "SKILL.md"
            if d.is_dir() and f.exists():
                meta = _parse_frontmatter(f.read_text(encoding="utf-8"))
                out.append({"name": d.name, "description": meta.get("description", ""),
                            "files": [str(p.relative_to(d)).replace("\\", "/")
                                      for p in d.rglob("*") if p.is_file() and p.name != "SKILL.md"]})
        return out

    def index_text(self) -> str:
        items = self.list()
        if not items:
            return ""
        return "\n".join(f"- {s['name']}: {s['description'][:140]}" for s in items)

    def view(self, name: str, file_path: str = "") -> str:
        if not NAME_RE.match(name or ""):
            return "ERROR: invalid skill name"
        d = self._dir(name)
        if not (d / "SKILL.md").exists():
            return f"ERROR: skill '{name}' not found. Use skills_list."
        target = self._safe_file(d, file_path) if file_path else d / "SKILL.md"
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"ERROR: file '{file_path}' not found in skill"
        return target.read_text(encoding="utf-8")

    @staticmethod
    def _safe_file(d: Path, file_path: str) -> Path | str:
        rel = Path(file_path.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] not in SUBDIRS:
            return f"ERROR: file_path must be inside {', '.join(s + '/' for s in SUBDIRS)}"
        return d / rel

    @staticmethod
    def _validate(content: str) -> str | None:
        if len(content) > SKILL_MAX_CHARS:
            return f"ERROR: SKILL.md too long ({len(content)}>{SKILL_MAX_CHARS})"
        meta = _parse_frontmatter(content)
        if not meta.get("name") or not meta.get("description"):
            return "ERROR: SKILL.md must start with frontmatter containing name: and description:"
        return _unsafe(content) and f"ERROR: {_unsafe(content)}"

    def manage(self, action: str, name: str, content: str = "", old_string: str = "",
               new_string: str = "", file_path: str = "", viewed: set[str] | None = None) -> str:
        """viewed != None হলে read-before-write বাধ্যতামূলক (রিভিউয়ারের জন্য)।"""
        if not NAME_RE.match(name or ""):
            return "ERROR: name must be lowercase letters/digits/hyphens (class-level, e.g. 'file-organizing')"
        d = self._dir(name)
        skill_md = d / "SKILL.md"
        with self._lock:
            if action == "create":
                if skill_md.exists():
                    return f"ERROR: skill '{name}' already exists; use patch/edit"
                err = self._validate(content)
                if err:
                    return err
                if _parse_frontmatter(content).get("name") != name:
                    return "ERROR: frontmatter name must equal the skill name"
                d.mkdir(parents=True, exist_ok=True)
                skill_md.write_text(content, encoding="utf-8")
                return f"OK: skill '{name}' created"
            if not skill_md.exists():
                return f"ERROR: skill '{name}' not found"
            key = f"{name}:{file_path}" if file_path else name
            if action in ("patch", "edit", "write_file") and viewed is not None:
                exists = (file_path and not isinstance(self._safe_file(d, file_path), str)
                          and self._safe_file(d, file_path).exists())
                if (not file_path or exists) and key not in viewed:
                    return (f"ERROR: read-before-write — call skill_view(name='{name}'"
                            f"{', file_path=' + repr(file_path) if file_path else ''}) first, then retry once")
            if action == "patch":
                path = skill_md if not file_path else self._safe_file(d, file_path)
                if isinstance(path, str):
                    return path
                text = path.read_text(encoding="utf-8")
                if not old_string or old_string not in text:
                    return "ERROR: old_string not found (copy it exactly from skill_view)"
                if text.count(old_string) > 1:
                    return "ERROR: old_string matches multiple places; include more context"
                new = text.replace(old_string, new_string)
                if path == skill_md:
                    err = self._validate(new)
                    if err:
                        return err
                path.write_text(new, encoding="utf-8")
                return f"OK: patched {file_path or 'SKILL.md'} of '{name}'"
            if action == "edit":
                err = self._validate(content)
                if err:
                    return err
                skill_md.write_text(content, encoding="utf-8")
                return f"OK: rewrote SKILL.md of '{name}'"
            if action == "write_file":
                path = self._safe_file(d, file_path)
                if isinstance(path, str):
                    return path
                if len(content) > FILE_MAX_CHARS:
                    return "ERROR: file too long"
                bad = _unsafe(content)
                if bad:
                    return f"ERROR: {bad}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return f"OK: wrote {file_path} in '{name}'"
            return "ERROR: action must be create | patch | edit | write_file (deleting skills is not allowed)"


# ===================================================================== SESSIONS
class SessionStore:
    """সব মেসেজ SQLite FTS5-এ — session_search টুল দিয়ে পুরনো কথা খোঁজা হয়।"""

    def __init__(self) -> None:
        LEARN_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LEARN_DIR / "sessions.db"
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT, "
                      "role TEXT, content TEXT, ts REAL)")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                      "content, content='messages', content_rowid='id', tokenize='unicode61')")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def log(self, session: str, role: str, content: str) -> None:
        content = (content or "").strip()
        if not content or role not in ("user", "assistant"):
            return
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO messages(session, role, content, ts) VALUES(?,?,?,?)",
                            (session, role, content[:8000], time.time()))
            c.execute("INSERT INTO messages_fts(rowid, content) VALUES(?,?)", (cur.lastrowid, content[:8000]))

    @staticmethod
    def _fts_query(q: str) -> str:
        words = re.findall(r"\w+", q, flags=re.UNICODE)
        return " OR ".join(f'"{w}"' for w in words[:12])

    def search(self, query: str, limit: int = 8) -> str:
        fq = self._fts_query(query or "")
        with self._conn() as c:
            if fq:
                rows = c.execute(
                    "SELECT m.session, m.role, m.ts, snippet(messages_fts, 0, '[', ']', ' … ', 24) AS snip "
                    "FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
                    "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?", (fq, limit)).fetchall()
            else:
                rows = c.execute("SELECT session, role, ts, substr(content,1,200) AS snip FROM messages "
                                 "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            return "No matching past conversations."
        return "\n".join(f"- [{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['ts']))}] "
                         f"{r['role']}: {r['snip']}" for r in rows)

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


memory_store = MemoryStore()
skill_store = SkillStore()
session_store = SessionStore()
