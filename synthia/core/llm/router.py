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
        self.preferred_model: str | None = None
        self.fallback_on_limit: bool = True
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

    @classmethod
    def _provider_name(cls, cfg: dict[str, Any]) -> str:
        if cfg.get("provider_name"):
            return str(cfg["provider_name"]).strip()
        if cls._is_local(cfg):
            return "Ollama (Local)"
        lbl = cfg.get("label", "")
        if "(" in lbl and ")" in lbl:
            return lbl.split("(")[-1].split(")")[0].strip()
        return "Custom Provider"

    def list_models(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "id": m["id"],
                "label": m.get("label", m["id"]),
                "model": m["model"],
                "provider": m.get("provider", "openai_compat"),
                "provider_name": self._provider_name(m),
                "base_url": m.get("base_url", ""),
                "api_key_env": m.get("api_key_env", ""),
                "has_key": bool(settings.env(m.get("api_key_env"))),
                "key_masked": settings.mask_env(m.get("api_key_env")),
                "local": self._is_local(m),
                "available": self._available(m),
                "vision": bool(m.get("vision")),
                "priority": int(m.get("priority", 50)),
                "cooldown": max(0, int(self.cooldown.get(m["id"], 0) - now)),
                "preferred": m["id"] == self.preferred_model,
            }
            for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50)))
        ]

    def state(self) -> dict[str, Any]:
        models = self.list_models()
        if not self.active:
            avail = [m for m in models if m["available"]]
            if avail:
                self.active = avail[0]["id"]
            elif models:
                self.active = models[0]["id"]
        active_m = next((m for m in models if m["id"] == self.active), None)
        active_provider = active_m["provider_name"] if active_m else ""
        return {
            "mode": self.mode,
            "manual_model": self.manual_model,
            "preferred_model": self.preferred_model,
            "fallback_on_limit": self.fallback_on_limit,
            "active": self.active,
            "active_provider": active_provider,
            "online": self._online[1],
            "models": models,
        }

    def set_mode(self, mode: str, model_id: str | None = None, fallback_on_limit: bool | None = None) -> None:
        if mode not in ("auto", "manual"):
            raise ValueError("mode must be auto or manual")
        self.mode = mode
        if fallback_on_limit is not None:
            self.fallback_on_limit = bool(fallback_on_limit)
        if model_id:
            cfg = self._cfg(model_id)
            if not cfg:
                raise ValueError(f"unknown model {model_id}")
            self.manual_model = model_id
            self.preferred_model = model_id
            self.active = model_id
            self.cooldown.pop(model_id, None)

    def reset_cooldowns(self) -> None:
        self.cooldown.clear()

    def save_api_key(self, env_key: str, api_key: str, model_id: str | None = None) -> None:
        settings.set_env(env_key, api_key)
        for m in settings.models:
            if m.get("api_key_env") == env_key:
                self.cooldown.pop(m["id"], None)
        if model_id and api_key.strip():
            cfg = self._cfg(model_id)
            if cfg:
                self.preferred_model = model_id
                self.manual_model = model_id
                self.active = model_id

    def update_model(self, model_id: str, updates: dict[str, Any]) -> None:
        cfg = self._cfg(model_id)
        if not cfg:
            raise ValueError(f"Model '{model_id}' not found")
        if "label" in updates and str(updates["label"]).strip():
            cfg["label"] = str(updates["label"]).strip()
        if "model" in updates and str(updates["model"]).strip():
            cfg["model"] = str(updates["model"]).strip()
        if "base_url" in updates and str(updates["base_url"]).strip():
            cfg["base_url"] = str(updates["base_url"]).strip()
        if "priority" in updates:
            cfg["priority"] = int(updates["priority"])
        if "vision" in updates:
            cfg["vision"] = bool(updates["vision"])
        settings.save_models(settings.models)

    def add_custom_model(self, data: dict[str, Any]) -> dict[str, Any]:
        import re
        label = str(data.get("label") or "").strip()
        model_name = str(data.get("model") or "").strip()
        base_url = str(data.get("base_url") or "").strip()
        provider_name = str(data.get("provider_name") or "").strip()
        provider = "ollama" if data.get("provider") == "ollama" else "openai_compat"
        if not label or not model_name or not base_url:
            raise ValueError("Label, Model ID এবং Base URL দেওয়া আবশ্যক")
        raw_id = str(data.get("id") or label).lower()
        mid = re.sub(r"[^a-z0-9]+", "-", raw_id).strip("-") or f"custom-{int(time.time())}"
        if self._cfg(mid):
            mid = f"{mid}-{int(time.time()) % 1000}"

        new_m: dict[str, Any] = {
            "id": mid,
            "label": label,
            "provider_name": provider_name or label,
            "provider": provider,
            "base_url": base_url,
            "model": model_name,
            "vision": bool(data.get("vision", False)),
            "priority": int(data.get("priority", 45)),
        }
        if provider != "ollama":
            env_key = str(data.get("api_key_env") or "").strip().upper()
            if not env_key:
                env_key = re.sub(r"[^A-Z0-9]+", "_", mid.upper()) + "_API_KEY"
            new_m["api_key_env"] = env_key
            api_key_val = str(data.get("api_key") or "").strip()
            if api_key_val:
                settings.set_env(env_key, api_key_val)
        settings.models.append(new_m)
        settings.save_models(settings.models)
        return new_m

    def delete_model(self, model_id: str) -> None:
        if len(settings.models) <= 1:
            raise ValueError("অন্তত ১টি মডেল থাকতে হবে")
        settings.models = [m for m in settings.models if m["id"] != model_id]
        settings.save_models(settings.models)
        if self.active == model_id:
            self.active = None
        if self.preferred_model == model_id:
            self.preferred_model = None

    async def test_model(self, model_id: str) -> dict[str, Any]:
        cfg = self._cfg(model_id)
        if not cfg:
            return {"ok": False, "error": f"Model '{model_id}' পাওয়া যায়নি"}
        if not self._available(cfg):
            return {"ok": False, "error": f"আগে {cfg.get('api_key_env', 'API Key')} সেভ করুন"}
        t0 = time.time()
        try:
            res = await self._provider(cfg).chat(
                [{"role": "user", "content": "Reply with one word: READY"}],
                tools=None,
                temperature=0.1,
            )
            ms = int((time.time() - t0) * 1000)
            self.cooldown.pop(model_id, None)
            return {"ok": True, "ms": ms, "reply": (res.get("content") or "READY").strip()[:80]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

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
        online = await self.is_online()
        now = time.time()

        # সব সচল মডেলের তালিকা (priority অনুযায়ী)
        pool: list[dict[str, Any]] = []
        for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50))):
            if not self._available(m):
                continue
            if not self._is_local(m) and (not online or self.cooldown.get(m["id"], 0) > now):
                continue
            pool.append(m)

        # যদি সব ক্লাউড মডেল cooldown-এ থাকে কিন্তু ইউজারের key আছে এবং অনলাইন, তবে cooldown উপেক্ষা করে শেষ চেষ্টা হিসেবে যোগ করি
        if not pool and online:
            for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50))):
                if self._available(m):
                    pool.append(m)

        if self.mode == "manual":
            cfg = self._cfg(self.manual_model)
            if not cfg:
                return pool
            if not self.fallback_on_limit:
                return [cfg]
            # ইউজারের সিলেক্ট করা মডেল সবার আগে, কিন্তু সেটার লিমিট শেষ হলে বাকি মডেলগুলোতে অটো সুইচ করবে!
            rest = [m for m in pool if m["id"] != cfg["id"]]
            return ([cfg] if self._available(cfg) else []) + rest

        # Auto মোড: ইউজারের পছন্দের (preferred) মডেলটি (যদি cooldown-এ না থাকে) সবার আগে রাখি, তারপর priority অনুযায়ী বাকিগুলো
        if self.preferred_model:
            pref = next((m for m in pool if m["id"] == self.preferred_model), None)
            if pref:
                pool = [pref] + [m for m in pool if m["id"] != self.preferred_model]
        return pool

    def _provider(self, cfg: dict[str, Any]) -> BaseProvider:
        cls = PROVIDERS[cfg["provider"]]
        return cls(cfg, settings.env(cfg.get("api_key_env")))

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   need_vision: bool = False) -> dict[str, Any]:
        temperature = float(settings.get("brain.temperature", 0.3))
        candidates = await self._candidates()
        if need_vision:
            vis = [c for c in candidates if c.get("vision")]
            if vis:
                candidates = vis + [c for c in candidates if not c.get("vision")]
        if not candidates:
            raise LLMError("কোনো মডেল পাওয়া যাচ্ছে না। Models & Keys থেকে API key যোগ করুন অথবা Ollama চালু করুন।")
        errors = []
        for idx, cfg in enumerate(candidates):
            try:
                if self.active != cfg["id"]:
                    self.active = cfg["id"]
                    await bus.emit("model_active", id=cfg["id"], label=cfg.get("label", cfg["id"]))
                    await bus.emit("brain_state", **self.state())
                result = await self._provider(cfg).chat(messages, tools, temperature)
                result["model_id"] = cfg["id"]
                result["model"] = cfg.get("model", cfg["id"])
                result["model_label"] = cfg.get("label", cfg["id"])
                return result
            except LLMError as e:
                errors.append(f"{cfg.get('label', cfg['id'])}: {e}")
                if e.rate_limited:
                    self.cooldown[cfg["id"]] = time.time() + (e.retry_after or 90)
                elif not self._is_local(cfg):
                    self.cooldown[cfg["id"]] = time.time() + (30 if e.network else 60)
                next_cfg = candidates[idx + 1] if idx + 1 < len(candidates) else None
                if next_cfg:
                    await bus.emit(
                        "signal",
                        level="warn",
                        title="auto_switch",
                        text=f"⚡ {cfg.get('label')} লিমিট/ত্রুটি ({e}) → অটো সুইচ: {next_cfg.get('label')}",
                    )
                else:
                    await bus.emit("signal", level="error", title="model_fail", text=f"{cfg.get('label')} ব্যর্থ: {e}")
                await bus.emit("brain_state", **self.state())
                if self.mode == "manual" and not self.fallback_on_limit:
                    break
        raise LLMError("সব মডেল ব্যর্থ:\n" + "\n".join(errors))


router = ModelRouter()
