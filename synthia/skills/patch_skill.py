"""Patch & File Editing Skill - OpenJarvis architectural pattern adapted for Synthia.

Enables precise, line-targeted code and text editing without requiring models to
rewrite massive files from scratch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings
from ..core.safety import safety
from ..core.tools import DESTRUCTIVE, SENSITIVE, tool
from .files import resolve

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


def _parse_hunks(patch_text: str) -> list[_Hunk]:
    hunks: list[_Hunk] = []
    current: _Hunk | None = None

    for raw in patch_text.splitlines():
        line = raw.rstrip("\r\n")
        m = _HUNK_HEADER_RE.match(line)
        if m:
            current = _Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2)) if m.group(2) is not None else 1,
                new_start=int(m.group(3)),
                new_count=int(m.group(4)) if m.group(4) is not None else 1,
            )
            hunks.append(current)
            continue
        if current is not None:
            if line.startswith((" ", "+", "-")):
                current.lines.append(line)
            elif line == "":
                current.lines.append(" ")
    return hunks


def _apply_hunks_to_lines(lines: list[str], hunks: list[_Hunk]) -> tuple[bool, list[str], str]:
    output = list(lines)
    # Apply hunks in reverse line order to preserve line offsets
    sorted_hunks = sorted(hunks, key=lambda h: h.old_start, reverse=True)

    for h in sorted_hunks:
        start_idx = max(0, h.old_start - 1)
        expected_context: list[str] = []
        replacement: list[str] = []

        for hl in h.lines:
            prefix = hl[:1]
            content = hl[1:]
            if prefix == " ":
                expected_context.append(content)
                replacement.append(content)
            elif prefix == "-":
                expected_context.append(content)
            elif prefix == "+":
                replacement.append(content)

        # Context match check
        slice_end = start_idx + len(expected_context)
        actual = output[start_idx:slice_end]
        if actual != expected_context:
            # Fuzzy match around target index
            matched = False
            for offset in range(-3, 4):
                try_start = start_idx + offset
                if try_start >= 0 and output[try_start:try_start + len(expected_context)] == expected_context:
                    start_idx = try_start
                    slice_end = start_idx + len(expected_context)
                    matched = True
                    break
            if not matched:
                return False, lines, f"Hunk at line {h.old_start} failed to match target context."

        output[start_idx:slice_end] = replacement

    return True, output, "OK"


@tool("edit_file", "Edit an existing file by replacing an exact target block of text with a replacement string.",
      {"path": {"type": "string", "description": "Path or shortcut to the file to edit"},
       "target": {"type": "string", "description": "The exact character sequence to replace"},
       "replacement": {"type": "string", "description": "The new content to put in place of target"},
       "replace_all": {"type": "boolean", "description": "Replace all occurrences (default False)"}},
      required=["path", "target", "replacement"], category="files")
async def edit_file(path: str, target: str, replacement: str, replace_all: bool = False) -> str:
    p = resolve(path)
    if not p.exists():
        return f"ERROR: File not found: {p}"
    if not p.is_file():
        return f"ERROR: Path is not a file: {p}"

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"ERROR: File '{p.name}' is binary or cannot be decoded as UTF-8."

    occurrences = content.count(target)
    if occurrences == 0:
        # Context hints: find closest line
        first_line = target.splitlines()[0] if target.splitlines() else target[:40]
        return (
            f"ERROR: Target string was not found in {p.name}.\n"
            f"Search attempted for: '{first_line[:60]}...'\n"
            f"Check whitespace or call read_file to see exact file contents."
        )

    if occurrences > 1 and not replace_all:
        return (
            f"ERROR: Target string appears {occurrences} times in {p.name}. "
            f"Provide more surrounding context to match a unique location, or set replace_all=True."
        )

    # If modifying a file outside workspace, check safety approval
    ws = settings.path("paths.workspace", "./workspace")
    if not str(p).startswith(str(ws)):
        preview = f"--- Original\n+++ Replacement\n- {target[:150]}\n+ {replacement[:150]}"
        ok = await safety.request(
            "edit_file",
            f"📝 ফাইল পরিবর্তন: {p.name}",
            {"path": str(p), "diff_preview": preview},
        )
        if not ok:
            return "DENIED: User did not approve editing this file."

    new_content = content.replace(target, replacement) if replace_all else content.replace(target, replacement, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"OK: Successfully updated {p.name} ({occurrences} occurrence(s) replaced)."


@tool("apply_patch", "Apply a unified diff patch to a target file.",
      {"path": {"type": "string", "description": "Target file path or shortcut"},
       "patch": {"type": "string", "description": "Unified diff text with @@ hunk headers"}},
      required=["path", "patch"], category="files")
async def apply_patch(path: str, patch: str) -> str:
    p = resolve(path)
    if not p.exists():
        return f"ERROR: File not found: {p}"

    hunks = _parse_hunks(patch)
    if not hunks:
        return "ERROR: No valid hunks (@@ ... @@) detected in patch."

    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return f"ERROR reading {p.name}: {e}"

    ws = settings.path("paths.workspace", "./workspace")
    if not str(p).startswith(str(ws)):
        ok = await safety.request(
            "apply_patch",
            f"🧩 প্যাচ প্রয়োগ: {p.name}",
            {"path": str(p), "hunk_count": len(hunks)},
        )
        if not ok:
            return "DENIED: User did not approve applying patch."

    success, new_lines, reason = _apply_hunks_to_lines(lines, hunks)
    if not success:
        return f"ERROR applying patch: {reason}"

    p.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    return f"OK: Successfully applied {len(hunks)} hunk(s) to {p.name}."
