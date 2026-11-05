"""Safety Gate - ঝুঁকিপূর্ণ কাজের আগে মানুষের (আপনার) অনুমতি নেওয়া।

নিয়ম (খুবই স্ট্রিক্ট):
  * risk="destructive" (ডিলিট, ওভাররাইট, শেল কমান্ড) -> সবসময় অনুমতি লাগবে।
    কোনো মোড, কোনো সেটিং, কোনো AI নির্দেশ এটা বন্ধ করতে পারবে না।
  * অনুমতি আসতে পারে শুধু মানুষের চ্যানেল থেকে: Desktop UI / Telegram / Discord।
  * নির্দিষ্ট সময়ে উত্তর না এলে -> স্বয়ংক্রিয়ভাবে বাতিল (DENY)।
  * প্রতিটি অনুমতি একবারই ব্যবহারযোগ্য, শুধু সেই নির্দিষ্ট কাজের জন্য।
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import ROOT, settings
from .events import bus


@dataclass
class ConfirmRequest:
    id: str
    tool: str
    title: str
    details: dict[str, Any]
    created: float = field(default_factory=time.time)
    future: asyncio.Future | None = None


class SafetyGate:
    def __init__(self) -> None:
        self._pending: dict[str, ConfirmRequest] = {}
        self._log_path = ROOT / "logs" / "safety_audit.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, record: dict[str, Any]) -> None:
        record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @property
    def pending(self) -> list[dict[str, Any]]:
        return [
            {"id": r.id, "tool": r.tool, "title": r.title, "details": r.details}
            for r in self._pending.values()
        ]

    async def request(self, tool: str, title: str, details: dict[str, Any]) -> bool:
        """অনুমতি চাওয়া। True = অনুমোদিত, False = বাতিল।"""
        loop = asyncio.get_running_loop()
        req = ConfirmRequest(
            id=uuid.uuid4().hex[:10], tool=tool, title=title, details=details,
            future=loop.create_future(),
        )
        self._pending[req.id] = req
        timeout = float(settings.get("safety.confirm_timeout_sec", 180))
        self._audit({"event": "requested", "id": req.id, "tool": tool, "details": details})
        await bus.emit(
            "confirm_request", id=req.id, tool=tool, title=title,
            details=details, timeout=timeout,
        )
        try:
            approved = await asyncio.wait_for(req.future, timeout=timeout)
        except asyncio.TimeoutError:
            approved = False
            self._audit({"event": "timeout", "id": req.id})
        finally:
            self._pending.pop(req.id, None)
        await bus.emit("confirm_resolved", id=req.id, approved=bool(approved))
        return bool(approved)

    def resolve(self, req_id: str, approved: bool, channel: str) -> bool:
        """মানুষের চ্যানেল (ui/telegram/discord) থেকে উত্তর।"""
        req = self._pending.get(req_id)
        if not req or not req.future or req.future.done():
            return False
        self._audit({"event": "approved" if approved else "denied", "id": req_id, "channel": channel})
        req.future.set_result(bool(approved))
        return True

    def deny_all(self, channel: str = "kill_switch") -> None:
        for rid in list(self._pending):
            self.resolve(rid, False, channel)


def describe_paths(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            try:
                n = sum(1 for _ in pp.rglob("*"))
            except Exception:
                n = -1
            out.append(f"📁 {pp}  ({n} items inside)" if n >= 0 else f"📁 {pp}")
        elif pp.exists():
            out.append(f"📄 {pp}  ({pp.stat().st_size:,} bytes)")
        else:
            out.append(f"❓ {pp}  (not found)")
    return out


safety = SafetyGate()
