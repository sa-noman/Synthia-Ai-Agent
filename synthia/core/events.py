"""Event Bus - Synthia-র সব ঘটনা (চ্যাট, টুল, টেলিমেট্রি) UI / Telegram / Discord-এ পাঠায়।"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

Listener = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def emit(self, type_: str, **data: Any) -> None:
        event = {"type": type_, "ts": time.time(), **data}
        dead: list[Listener] = []
        for listener in list(self._listeners):
            try:
                await listener(event)
            except Exception:
                dead.append(listener)
        for d in dead:
            self.unsubscribe(d)

    def emit_nowait(self, type_: str, **data: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(type_, **data))
        except RuntimeError:
            pass


bus = EventBus()
