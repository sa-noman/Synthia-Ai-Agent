"""Model Router - কোন মডেল দিয়ে চিন্তা করবে তা ঠিক করে।

* auto মোড  : নেট থাকলে priority অনুযায়ী ক্লাউড API চেষ্টা করে; একটার লিমিট শেষ হলে
              সেটাকে কিছুক্ষণ "cooldown"-এ রেখে পরেরটায় যায়; নেট না থাকলে লোকাল (Ollama)।
* manual মোড: আপনি যে মডেল বেছে দেবেন শুধু সেটাই চলবে।
"""
from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

from ...config import settings
from ..events import bus
from .providers import PROVIDERS, BaseProvider, LLMError


class ModelRouter:
    def __init__(self) -> None:
        self.mode: str = settings.get("brain.mode", "auto")
        self.manual_model: str = settings.get("brain.manual_model", "local-gemma4")
        self.cooldown: dict[str, float] = {}
        self.active: str | None = None
        self._online: tuple[float, bool] = (0.0, False)

    # ---------- মডেল তালিকা ----------
    def _cfg(self, mid: str) -> dict[str, Any] | None:
        return next((m for m in settings.models if m["id"] == mid), None)

    @staticmethod
    def _is_local(cfg: dict[str, Any]) -> bool:
        return cfg.get("provider") == "ollama"

    def _available(self, cfg: dict[str, Any]) -> bool:
        return self._is_local(cfg) or bool(settings.env(cfg.get("api_key_env")))

    def list_models(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "id": m["id"], "label": m.get("label", m["id"]), "model": m["model"],
                "local": self._is_local(m), "available": self._available(m),
                "vision": bool(m.get("vision")), "priority": m.get("priority", 50),
                "cooldown": max(0, int(self.cooldown.get(m["id"], 0) - now)),
            }
            for m in sorted(settings.models, key=lambda x: x.get("priority", 50))
        ]

    def state(self) -> dict[str, Any]:
        return {"mode": self.mode, "manual_model": self.manual_model,
                "active": self.active, "online": self._online[1], "models": self.list_models()}

    def set_mode(self, mode: str, model_id: str | None = None) -> None:
        if mode not in ("auto", "manual"):
            raise ValueError("mode must be auto or manual")
        self.mode = mode
        if model_id:
            if not self._cfg(model_id):
                raise ValueError(f"unknown model {model_id}")
            self.manual_model = model_id

    # ---------- নেট আছে কি না ----------
    async def is_online(self) -> bool:
        ts, val = self._online
        if time.time() - ts < 30:
            return val

        def _probe() -> bool:
            for host in (("1.1.1.1", 443), ("8.8.8.8", 53)):
                try:
                    with socket.create_connection(host, timeout=1.5):
                        return True
                except OSError:
                    continue
            return False

        val = await asyncio.to_thread(_probe)
        self._online = (time.time(), val)
        return val

    # ---------- চেষ্টা করার ক্রম ----------
    async def _candidates(self) -> list[dict[str, Any]]:
        if self.mode == "manual":
            cfg = self._cfg(self.manual_model)
            return [cfg] if cfg else []
        online = await self.is_online()
        now = time.time()
        out = []
        for m in sorted(settings.models, key=lambda x: x.get("priority", 50)):
            if not self._available(m):
                continue
            if not self._is_local(m) and (not online or self.cooldown.get(m["id"], 0) > now):
                continue
            out.append(m)
        return out

    def _provider(self, cfg: dict[str, Any]) -> BaseProvider:
        cls = PROVIDERS[cfg["provider"]]
        return cls(cfg, settings.env(cfg.get("api_key_env")))

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   need_vision: bool = False) -> dict[str, Any]:
        temperature = float(settings.get("brain.temperature", 0.3))
        candidates = await self._candidates()
        if need_vision and self.mode == "auto":
            candidates = [c for c in candidates if c.get("vision")] or candidates
        if not candidates:
            raise LLMError("কোনো মডেল পাওয়া যাচ্ছে না। Ollama চালু আছে কিনা দেখুন বা API key দিন।")
        errors = []
        for cfg in candidates:
            try:
                if self.active != cfg["id"]:
                    self.active = cfg["id"]
                    await bus.emit("model_active", id=cfg["id"], label=cfg.get("label", cfg["id"]))
                result = await self._provider(cfg).chat(messages, tools, temperature)
                result["model_id"] = cfg["id"]
                return result
            except LLMError as e:
                errors.append(f"{cfg['id']}: {e}")
                if e.rate_limited:
                    self.cooldown[cfg["id"]] = time.time() + (e.retry_after or 90)
                elif e.network and not self._is_local(cfg):
                    self.cooldown[cfg["id"]] = time.time() + 30
                await bus.emit("signal", level="warn", title="model_switch",
                               text=f"{cfg.get('label')} ব্যর্থ: {e} → পরের মডেলে যাচ্ছি")
                if self.mode == "manual":
                    break
        raise LLMError("সব মডেল ব্যর্থ:\n" + "\n".join(errors))


router = ModelRouter()
