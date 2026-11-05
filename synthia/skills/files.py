"""Files Skill - ফাইল খোঁজা, পড়া, লেখা, গোছানো, খোলা ও (অনুমতিসহ) ডিলিট।"""
from __future__ import annotations

import fnmatch
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from send2trash import send2trash

from ..core.agent import user_dirs
from ..core.safety import describe_paths, safety
from ..core.tools import DESTRUCTIVE, SENSITIVE, tool

SKIP_DIRS = {"appdata", "node_modules", ".git", "$recycle.bin", "windows", "program files",
             "program files (x86)", "programdata", "__pycache__", ".venv", "venv",
             "system volume information", "msocache"}

PROTECTED = [Path(p).resolve() for p in (
    os.environ.get("SystemRoot", r"C:\Windows"), r"C:\Program Files", r"C:\Program Files (x86)",
    r"C:\ProgramData", str(Path.home()), str(Path.home() / "AppData"),
)]


def resolve(p: str) -> Path:
    """'downloads', 'desktop/notes.txt', '~/x', '%USERPROFILE%' সব বুঝে আসল পাথ বানায়।"""
    p = os.path.expandvars(os.path.expanduser((p or "").strip().strip('"')))
    dirs = user_dirs()
    norm = p.replace("\\", "/")
    head, _, rest = norm.partition("/")
    key = head.lower().rstrip(":")
    if key in dirs and not Path(p).is_absolute():
        return (dirs[key] / rest).resolve() if rest else dirs[key].resolve()
    path = Path(p)
    if not path.is_absolute():
        path = dirs["workspace"] / path
    return path.resolve()


def _is_protected(path: Path) -> bool:
    if path.parent == path:  # drive root e.g. C:\ or D:\
        return True
    return any(path == pr for pr in PROTECTED) or path in user_dirs().values()


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@tool("list_directory", "List files and folders inside a directory. Use shortcuts: desktop, downloads, "
      "documents, pictures, videos, music, workspace, or a full path.",
      {"path": {"type": "string", "description": "folder path or shortcut"},
       "pattern": {"type": "string", "description": "optional filter like *.pdf"},
       "sort": {"type": "string", "enum": ["name", "newest", "largest"], "description": "sort order"}},
      required=["path"], category="files")
def list_directory(path: str, pattern: str = "*", sort: str = "name") -> str:
    d = resolve(path)
    if not d.exists():
        return f"ERROR: folder not found: {d}"
    if not d.is_dir():
        return f"ERROR: not a folder: {d}"
    items = []
    for e in os.scandir(d):
        if not fnmatch.fnmatch(e.name.lower(), (pattern or "*").lower()):
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        items.append((e.name, e.is_dir(), st.st_size, st.st_mtime))
    key = {"newest": lambda x: -x[3], "largest": lambda x: -x[2]}.get(sort, lambda x: (not x[1], x[0].lower()))
    items.sort(key=key)
    lines = [f"📂 {d}  ({len(items)} items)"]
    for name, is_dir, size, mtime in items[:150]:
        when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{'📁' if is_dir else '📄'} {name}{'' if is_dir else '  ' + _human(size)}  [{when}]")
    if len(items) > 150:
        lines.append(f"... and {len(items) - 150} more")
    return "\n".join(lines)


@tool("search_files", "Search files/folders by name (partial match) under a folder, recursively.",
      {"query": {"type": "string", "description": "part of file name, e.g. 'invoice' or '*.mp4'"},
       "root": {"type": "string", "description": "where to search (default: home). e.g. D:/ or downloads"},
       "limit": {"type": "integer", "description": "max results (default 30)"}},
      required=["query"], category="files")
def search_files(query: str, root: str = "home", limit: int = 30) -> str:
    base = resolve(root)
    q = query.lower().strip()
    use_glob = any(ch in q for ch in "*?")
    results: list[str] = []
    deadline = time.time() + 20
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [x for x in dirnames if x.lower() not in SKIP_DIRS and not x.startswith(".")]
        for name in dirnames + filenames:
            n = name.lower()
            if (fnmatch.fnmatch(n, q) if use_glob else q in n):
                results.append(str(Path(dirpath) / name))
                if len(results) >= limit:
                    break
        if len(results) >= limit or time.time() > deadline:
            break
    if not results:
        return f"No matches for '{query}' under {base}"
    note = " (search stopped early: time limit)" if time.time() > deadline else ""
    return f"Found {len(results)} result(s) under {base}{note}:\n" + "\n".join(results)


@tool("read_file", "Read a text file's content (code, txt, md, csv, json, etc).",
      {"path": {"type": "string"}, "max_chars": {"type": "integer", "description": "default 8000"}},
      required=["path"], category="files")
def read_file(path: str, max_chars: int = 8000) -> str:
    f = resolve(path)
    if not f.is_file():
        return f"ERROR: file not found: {f}"
    data = f.read_text(encoding="utf-8", errors="replace")
    return data[:max_chars] + ("\n...[truncated]" if len(data) > max_chars else "")


@tool("write_file", "Create a new text file (code, notes, scripts). Overwriting an existing file needs user approval.",
      {"path": {"type": "string", "description": "file path; relative paths go into workspace"},
       "content": {"type": "string"},
       "overwrite": {"type": "boolean", "description": "true to replace an existing file"}},
      required=["path", "content"], risk=SENSITIVE, category="files")
async def write_file(path: str, content: str, overwrite: bool = False) -> str:
    f = resolve(path)
    if f.exists():
        if not overwrite:
            return f"ERROR: file already exists: {f}. Use a new name or overwrite=true."
        ok = await safety.request("write_file", "ফাইল ওভাররাইট (পুরনো কনটেন্ট মুছে যাবে)",
                                  {"paths": describe_paths([str(f)])})
        if not ok:
            return "DENIED: user did not approve overwriting this file."
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} chars to {f}"


@tool("create_folder", "Create a new folder (and parents).", {"path": {"type": "string"}},
      required=["path"], category="files")
def create_folder(path: str) -> str:
    d = resolve(path)
    d.mkdir(parents=True, exist_ok=True)
    return f"OK: folder ready: {d}"


async def _transfer(src: str, dst: str, move: bool) -> str:
    s, d = resolve(src), resolve(dst)
    if not s.exists():
        return f"ERROR: source not found: {s}"
    if d.is_dir():
        d = d / s.name
    if d.exists():
        ok = await safety.request("move_path" if move else "copy_path",
                                  "গন্তব্যে একই নামের ফাইল আছে — ওভাররাইট হবে",
                                  {"source": str(s), "will_replace": describe_paths([str(d)])})
        if not ok:
            return "DENIED: user did not approve replacing the existing item."
        send2trash(str(d))
    d.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(s), str(d))
    elif s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return f"OK: {'moved' if move else 'copied'} {s} -> {d}"


@tool("move_path", "Move or rename a file/folder.",
      {"source": {"type": "string"}, "destination": {"type": "string", "description": "new path or target folder"}},
      required=["source", "destination"], risk=SENSITIVE, category="files")
async def move_path(source: str, destination: str) -> str:
    return await _transfer(source, destination, move=True)


@tool("copy_path", "Copy a file/folder.",
      {"source": {"type": "string"}, "destination": {"type": "string"}},
      required=["source", "destination"], category="files")
async def copy_path(source: str, destination: str) -> str:
    return await _transfer(source, destination, move=False)


@tool("open_path", "Open a file or folder with its default Windows app (e.g. open a video, PDF, or folder in Explorer).",
      {"path": {"type": "string"}}, required=["path"], category="files")
def open_path(path: str) -> str:
    p = resolve(path)
    if not p.exists():
        return f"ERROR: not found: {p}"
    os.startfile(str(p))  # type: ignore[attr-defined]
    return f"OK: opened {p}"


@tool("delete_paths", "Delete files/folders (moves them to Recycle Bin). ALWAYS asks the user for approval first.",
      {"paths": {"type": "array", "items": {"type": "string"}, "description": "list of paths to delete"}},
      required=["paths"], risk=DESTRUCTIVE, category="files")
async def delete_paths(paths: list[str]) -> str:
    if isinstance(paths, str):
        paths = [paths]
    resolved = [resolve(p) for p in paths]
    blocked = [str(p) for p in resolved if _is_protected(p)]
    if blocked:
        return f"ERROR: refusing to delete protected system/user root folders: {blocked}"
    missing = [str(p) for p in resolved if not p.exists()]
    targets = [p for p in resolved if p.exists()]
    if not targets:
        return f"ERROR: nothing to delete, not found: {missing}"
    # 🔒 STRICT: মানুষের অনুমতি ছাড়া কখনো না
    ok = await safety.request("delete_paths", f"🗑️ {len(targets)}টি আইটেম ডিলিট (Recycle Bin-এ যাবে)",
                              {"paths": describe_paths([str(t) for t in targets])})
    if not ok:
        return "DENIED: user did NOT approve deletion. Nothing was deleted."
    done = []
    for t in targets:
        send2trash(str(t))
        done.append(str(t))
    msg = "OK: moved to Recycle Bin:\n" + "\n".join(done)
    if missing:
        msg += f"\n(not found: {missing})"
    return msg


@tool("file_info", "Get details of a file/folder (size, dates, item count).",
      {"path": {"type": "string"}}, required=["path"], category="files")
def file_info(path: str) -> str:
    p = resolve(path)
    if not p.exists():
        return f"ERROR: not found: {p}"
    st = p.stat()
    info = {
        "path": str(p), "type": "folder" if p.is_dir() else "file",
        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "created": datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M"),
    }
    if p.is_dir():
        total, count = 0, 0
        for f in p.rglob("*"):
            if f.is_file():
                count += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
            if count > 20000:
                break
        info.update(files=count, total_size=_human(total))
    else:
        info["size"] = _human(st.st_size)
    return info
