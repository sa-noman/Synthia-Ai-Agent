"""Agent Execution History & Tool Logging Store.

Maintains in-memory task traces and persistent append-only logs in synthia_data/task_history.jsonl.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import ROOT


@dataclass
class ToolExecutionRecord:
    step_id: str
    tool: str
    args: dict[str, Any]
    result: str = ""
    ok: bool = True
    ms: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0


@dataclass
class TaskRecord:
    task_id: str
    prompt: str
    source: str = "ui"
    session: str = "ui"
    model: str = ""
    status: str = "running"   # "running", "completed", "error", "cancelled"
    start_time: float = field(default_factory=time.time)
    start_iso: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: float = 0.0
    duration_ms: int = 0
    response: str = ""
    error: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskHistoryStore:
    def __init__(self, max_recent: int = 100) -> None:
        self.max_recent = max_recent
        self._recent: deque[TaskRecord] = deque(maxlen=max_recent)
        self._active: dict[str, TaskRecord] = {}
        self._log_path = ROOT / "synthia_data" / "task_history.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_recent()

    def _load_recent(self) -> None:
        if not self._log_path.exists():
            return
        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-self.max_recent:]:
                try:
                    data = json.loads(line)
                    record = TaskRecord(**data)
                    self._recent.append(record)
                except Exception:
                    pass
        except Exception:
            pass

    def start_task(self, task_id: str, prompt: str, source: str = "ui",
                   session: str = "ui", model: str = "") -> TaskRecord:
        record = TaskRecord(
            task_id=task_id,
            prompt=prompt,
            source=source,
            session=session,
            model=model,
            status="running",
        )
        self._active[task_id] = record
        self._recent.append(record)
        return record

    def log_tool_start(self, task_id: str, step_id: str, tool: str, args: dict[str, Any]) -> None:
        record = self._active.get(task_id)
        if not record:
            return
        t_call = {
            "step_id": step_id,
            "tool": tool,
            "args": args,
            "start_time": time.time(),
            "status": "running",
            "result": "",
            "ok": True,
            "ms": 0,
        }
        record.tool_calls.append(t_call)

    def log_tool_end(self, task_id: str, step_id: str, tool: str, ok: bool, result: str, ms: int) -> None:
        record = self._active.get(task_id)
        if not record:
            return
        for tc in record.tool_calls:
            if tc.get("step_id") == step_id:
                tc["ok"] = ok
                tc["result"] = result[:1500]
                tc["ms"] = ms
                tc["status"] = "ok" if ok else "error"
                break

    def finish_task(self, task_id: str, response: str, status: str = "completed",
                    error: str | None = None) -> None:
        record = self._active.pop(task_id, None)
        if not record:
            for r in self._recent:
                if r.task_id == task_id:
                    record = r
                    break
        if not record:
            return

        record.end_time = time.time()
        record.duration_ms = int((record.end_time - record.start_time) * 1000)
        record.response = response
        record.status = status
        record.error = error

        # Persist to JSONL file
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        recs = list(self._recent)
        recs.reverse()
        return [r.to_dict() for r in recs[:limit]]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        for r in self._recent:
            if r.task_id == task_id:
                return r.to_dict()
        return None


task_history = TaskHistoryStore()
