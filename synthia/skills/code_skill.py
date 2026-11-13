"""Code Skill - Python Script Execution & Math Engine.

Adapted from OpenJarvis code_interpreter with defense-in-depth:
1. AST validation: Safe mathematical, data, and text processing runs instantly.
2. Full scripts with filesystem/network access require explicit user approval via SafetyGate.
3. Isolated execution in subprocess with timeout controls.
"""
from __future__ import annotations

import ast
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..config import ROOT, settings
from ..core.agent import user_dirs
from ..core.safety import safety
from ..core.tools import DESTRUCTIVE, SAFE, SENSITIVE, tool

_SAFE_IMPORTS = frozenset({
    "math", "json", "time", "datetime", "random", "re",
    "string", "collections", "itertools", "hashlib", "statistics", "decimal",
})

_BLOCKED_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input",
    "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr",
})


def _is_ast_safe(code: str) -> tuple[bool, str]:
    """Checks whether the code contains only safe imports and operations."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base not in _SAFE_IMPORTS:
                    return False, f"Import '{alias.name}' requires user approval."
        elif isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[0]
            if base not in _SAFE_IMPORTS or any(a.name == "*" for a in node.names):
                return False, f"Import from '{node.module}' requires user approval."
        elif isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES or (node.id.startswith("__") and node.id.endswith("__")):
                return False, f"Identifier '{node.id}' requires user approval."
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return False, f"Private attribute '{node.attr}' access requires user approval."

    return True, "OK"


@tool("execute_python", "Execute Python code and return stdout/results. Safe math/data scripts run immediately; "
      "scripts accessing files or system libraries require user confirmation.",
      {"code": {"type": "string", "description": "Python code to execute (use print() to output results)"},
       "timeout_sec": {"type": "integer", "description": "Maximum execution time in seconds (default 30)"}},
      required=["code"], category="system")
async def execute_python(code: str, timeout_sec: int = 30) -> str:
    code = (code or "").strip()
    if not code:
        return "ERROR: No Python code provided."

    is_safe, reason = _is_ast_safe(code)
    timeout = max(5, min(120, timeout_sec or 30))

    if not is_safe:
        # Needs user approval
        preview = code if len(code) <= 300 else code[:297] + "..."
        ok = await safety.request(
            "execute_python",
            "🐍 Python স্ক্রিপ্ট চালানো (সিস্টেম/ফাইল অ্যাক্সেস)",
            {"reason": reason, "code_preview": preview},
        )
        if not ok:
            return "DENIED: User did not approve running this Python script."

    # Choose python executable: use .venv python if available so installed packages work
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    py_exec = str(venv_py) if venv_py.exists() else sys.executable
    ws = settings.path("paths.workspace", "./workspace")

    def _run() -> str:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        t0 = time.time()
        try:
            cmd = [py_exec, "-c", code]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(ws),
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()

            out_parts = []
            if stdout:
                out_parts.append(stdout)
            if stderr:
                out_parts.append(f"[stderr]\n{stderr}")
            if not out_parts:
                out_parts.append("(Script completed with no printed output. Use print() to see values.)")

            status = f"exit_code={res.returncode} ({elapsed_ms}ms)"
            return f"{status}\n" + "\n".join(out_parts)
        except subprocess.TimeoutExpired:
            return f"ERROR: Python execution timed out after {timeout}s."
        except Exception as e:
            return f"ERROR: Subprocess execution failed: {e}"

    import asyncio
    return await asyncio.to_thread(_run)


_MATH_SAFE_NAMES = {
    k: getattr(math, k) for k in dir(math) if not k.startswith("_")
}
_MATH_SAFE_NAMES.update({"abs": abs, "round": round, "min": min, "max": max})


@tool("evaluate_math", "Evaluate a safe mathematical expression (e.g. 'sqrt(144) + 2**8 * sin(pi/4)').",
      {"expression": {"type": "string", "description": "Mathematical expression to evaluate"}},
      required=["expression"], category="system")
def evaluate_math(expression: str) -> str:
    expr = (expression or "").strip()
    if not expr:
        return "ERROR: Empty expression"

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"ERROR: Invalid math expression: {e}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.operator, ast.unaryop, ast.expr_context)):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MATH_SAFE_NAMES:
            continue
        if isinstance(node, ast.Name) and node.id in _MATH_SAFE_NAMES:
            continue
        return f"ERROR: Expression contains disallowed node or identifier: {type(node).__name__}"

    try:
        result = eval(compile(tree, "<math>", "eval"), {"__builtins__": None}, _MATH_SAFE_NAMES)
        return f"Result: {result}"
    except Exception as e:
        return f"ERROR evaluating math expression: {e}"

