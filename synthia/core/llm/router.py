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

DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "id": "gemini-flash",
        "label": "Gemini 3.5 Flash (Google AI Studio)",
        "provider_name": "Google AI Studio",
        "provider": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.5-flash",
        "api_key_env": "GEMINI_API_KEY",
        "vision": True,
        "priority": 10,
    },
    {
        "id": "gemini-38-flash",
        "label": "Gemini 3.8 Flash (Google AI Studio)",
        "provider_name": "Google AI Studio",
        "provider": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",
        "api_key_env": "GEMINI_API_KEY",
        "vision": True,
        "priority": 12,
    },
    {
        "id": "gemini-31-pro",
        "label": "Gemini 3.1 Pro (Google AI Studio)",
        "provider_name": "Google AI Studio",
        "provider": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.1-pro-preview",
        "api_key_env": "GEMINI_API_KEY",
        "vision": True,
        "priority": 15,
    },
    {
        "id": "openrouter-nemotron",
        "label": "Nemotron 3.5 Lightning (OpenRouter Free)",
        "provider_name": "OpenRouter",
        "provider": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3.5-lightning:free",
        "api_key_env": "OPENROUTER_API_KEY",
        "priority": 20,
    },
    {
        "id": "openrouter-gemma",
        "label": "Gemma 4 31B (OpenRouter Free)",
        "provider_name": "OpenRouter",
        "provider": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemma-4-31b-it:free",
        "api_key_env": "OPENROUTER_API_KEY",
        "priority": 22,
    },
    {
        "id": "openrouter-lfm",
        "label": "LFM 2.5 (OpenRouter Free)",
        "provider_name": "OpenRouter",
        "provider": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "liquid/lfm-2.5-2.6b:free",
        "api_key_env": "OPENROUTER_API_KEY",
        "priority": 24,
    },
    {
        "id": "groq-llama",
        "label": "Llama 3.3 70B (Groq)",
        "provider_name": "Groq",
        "provider": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
        "priority": 30,
    },
    {
        "id": "cerebras-llama",
        "label": "Llama 3.3 70B (Cerebras)",
        "provider_name": "Cerebras",
        "provider": "openai_compat",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "api_key_env": "CEREBRAS_API_KEY",
        "priority": 40,
    },
    {
        "id": "mistral-small",
        "label": "Mistral Small (Mistral AI)",
        "provider_name": "Mistral AI",
        "provider": "openai_compat",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "api_key_env": "MISTRAL_API_KEY",
        "priority": 50,
    },
    {
        "id": "nvidia-nim",
        "label": "Llama 3.3 70B (NVIDIA NIM)",
        "provider_name": "NVIDIA NIM",
        "provider": "openai_compat",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "api_key_env": "NVIDIA_API_KEY",
        "priority": 70,
    },
    {
        "id": "local-qwen",
        "label": "Qwen 2.5 7B (Local · Best Offline Bangla)",
        "provider_name": "Ollama (Local)",
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen2.5:7b",
        "vision": False,
        "priority": 90,
        "num_ctx": 8192,
    },
    {
        "id": "local-gemma4",
        "label": "Gemma 4 E4B (Local)",
        "provider_name": "Ollama (Local)",
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "gemma4:e4b",
        "vision": True,
        "priority": 100,
        "num_ctx": 8192,
    },
]
DEFAULT_MODELS_MAP: dict[str, dict[str, Any]] = {m["id"]: m for m in DEFAULT_MODELS}


class ModelRouter:
    def __init__(self) -> None:
        self.mode: str = settings.get("brain.mode", "auto")
        if self.mode not in ("auto", "manual"):
            self.mode = "auto"
        self.manual_model: str = settings.get("brain.manual_model", "gemini-flash")
        has_saved = bool(self.manual_model and self._cfg(self.manual_model))
        if not has_saved:
            fallback_m = next((m for m in settings.models if self._available(m)), None) or (settings.models[0] if settings.models else None)
            if fallback_m:
                self.manual_model = fallback_m["id"]
                has_saved = True
        self.preferred_model: str | None = None
        self.fallback_on_limit: bool = self.mode == "auto"
        self.cooldown: dict[str, float] = {}
        if self.mode == "auto":
            avail_auto = next(
                (m for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50))) if self._available(m)),
                None,
            )
            self.active: str | None = avail_auto["id"] if avail_auto else (self.manual_model if has_saved else None)
        else:
            self.active = self.manual_model if has_saved else None
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

    def sync_ollama_models(self) -> bool:
        """লোকাল Ollama-তে নতুন কোনো মডেল ডাউনলোড হলে তা স্বয়ংক্রিয়ভাবে তালিকায় যুক্ত করে।"""
        import json
        import urllib.request
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "Synthia"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = [m.get("name") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return False

        changed = False
        deleted_Local = {m.get("model") for m in getattr(settings, "deleted_models", []) if m.get("provider") == "ollama"}
        known = {m.get("model") for m in settings.models if m.get("provider") == "ollama"} | deleted_Local
        for name in installed:
            bare = name.replace(":latest", "")
            if name in known or bare in known:
                continue
            mid = "local-" + name.replace(":", "-").replace(".", "")
            label = f"{name.capitalize()} (Local Ollama)"
            if "qwen" in name.lower():
                tag = name.split(":")[-1] if ":" in name else "7B"
                label = f"Qwen 2.5 {tag.upper()} (Local · Best Offline Bangla)"
            settings.models.append({
                "id": mid,
                "label": label,
                "provider_name": "Ollama (Local)",
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model": name,
                "vision": False,
                "priority": 90,
                "num_ctx": 8192,
            })
            known.add(name)
            changed = True
        if changed:
            settings.save_models(settings.models)
        return changed

    def list_models(self) -> list[dict[str, Any]]:
        now = time.time()
        if now - getattr(self, "_last_ollama_sync", 0) > 10:
            self._last_ollama_sync = now
            try:
                self.sync_ollama_models()
            except Exception:
                pass
        return [
            {
                "id": m["id"],
                "label": m.get("label", m["id"]),
                "model": m["model"],
                "provider": m.get("provider", "openai_compat"),
                "provider_name": self._provider_name(m),
                "base_url": m.get("base_url", ""),
                "api_key_env": m.get("api_key_env", ""),
                "api_key_val": settings.env(m.get("api_key_env")),
                "has_key": bool(settings.env(m.get("api_key_env"))),
                "key_masked": settings.mask_env(m.get("api_key_env")),
                "local": self._is_local(m),
                "available": self._available(m),
                "vision": bool(m.get("vision")),
                "priority": int(m.get("priority", 50)),
                "cooldown": max(0, int(self.cooldown.get(m["id"], 0) - now)),
                "preferred": m["id"] == self.preferred_model,
                "is_default": m["id"] in DEFAULT_MODELS_MAP,
            }
            for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50)))
        ]

    def list_deleted_models(self) -> list[dict[str, Any]]:
        active_ids = {m["id"] for m in settings.models}
        deleted_map: dict[str, dict[str, Any]] = {}
        for dm in getattr(settings, "deleted_models", []):
            mid = dm.get("id")
            if mid and mid not in active_ids:
                deleted_map[mid] = dm
        for dm in DEFAULT_MODELS:
            mid = dm["id"]
            if mid not in active_ids and mid not in deleted_map:
                deleted_map[mid] = dict(dm)
        return [
            {
                "id": m["id"],
                "label": m.get("label", m["id"]),
                "model": m.get("model", ""),
                "provider": m.get("provider", "openai_compat"),
                "provider_name": self._provider_name(m),
                "base_url": m.get("base_url", ""),
                "api_key_env": m.get("api_key_env", ""),
                "priority": int(m.get("priority", 50)),
                "is_default": m["id"] in DEFAULT_MODELS_MAP,
            }
            for m in sorted(deleted_map.values(), key=lambda x: int(x.get("priority", 50)))
        ]

    def state(self) -> dict[str, Any]:
        models = self.list_models()
        if self.mode == "manual" and any(m["id"] == self.manual_model for m in models):
            self.active = self.manual_model
        elif self.preferred_model and any(m["id"] == self.preferred_model for m in models) and (
            not self.active or self.active == self.preferred_model
        ):
            pref_m = next((m for m in models if m["id"] == self.preferred_model), None)
            if pref_m and pref_m["available"]:
                self.active = self.preferred_model
        if not self.active or not any(m["id"] == self.active for m in models):
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
            "fallback_on_limit": self.mode == "auto",
            "active": self.active,
            "active_provider": active_provider,
            "online": self._online[1],
            "models": models,
            "deleted_models": self.list_deleted_models(),
        }

    def set_mode(self, mode: str, model_id: str | None = None, fallback_on_limit: bool | None = None) -> None:
        if mode not in ("auto", "manual"):
            raise ValueError("mode must be auto or manual")
        self.mode = mode
        # অটো মোডে থাকলে তবেই লিমিট/এররে পরের মডেলে সুইচ হবে; ম্যানুয়াল মোডে কখনো অটো-সুইচ হবেনা
        self.fallback_on_limit = mode == "auto"
        if model_id:
            cfg = self._cfg(model_id)
            if not cfg:
                raise ValueError(f"unknown model {model_id}")
            self.manual_model = model_id
            self.preferred_model = model_id if mode == "auto" else None
            self.active = model_id
            self.cooldown.pop(model_id, None)
        elif mode == "auto":
            self.preferred_model = None
            avail = next(
                (m for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50)))
                 if self._available(m) and self.cooldown.get(m["id"], 0) <= time.time()),
                None,
            ) or next((m for m in sorted(settings.models, key=lambda x: int(x.get("priority", 50))) if self._available(m)), None)
            if avail:
                self.active = avail["id"]
        elif mode == "manual" and self.manual_model and self._cfg(self.manual_model):
            self.preferred_model = None
            self.active = self.manual_model
        settings.save_brain_config(self.mode, self.manual_model)

    def find_model(self, query: str) -> dict[str, Any] | None:
        """টেক্সট/ভয়েস কমান্ড থেকে মডেল খুঁজে বের করে (বাংলা, Banglish ও English সাপোর্টসহ)।"""
        q = (query or "").lower().strip()
        if not q:
            return None

        # সিঙ্ক করে নেই যেন নতুন Ollama মডেল থাকলে খুঁজে পায়
        try:
            self.sync_ollama_models()
        except Exception:
            pass

        models = sorted(settings.models, key=lambda x: int(x.get("priority", 50)))
        locals_ = [m for m in models if self._is_local(m)]

        # অন্য/পরের লোকাল মডেল চাওয়া হলে চলমানটি বাদ দিয়ে পরেরটিতে যাই
        if locals_ and any(k in q for k in ("অন্য লোকাল", "আরেকটা লোকাল", "পরের লোকাল", "ভিন্ন লোকাল", "other local", "next local", "switch local")):
            other = next((m for m in locals_ if m["id"] != self.active), None)
            return other or locals_[0]

        # লোকাল Qwen / Gemma এর স্পষ্ট Alias
        if any(k in q for k in ("qwen", "কুয়েন", "কোয়েন", "কোয়েন", "কিউয়েন", "কিউয়েন", "7b")):
            found = next((m for m in locals_ if "qwen" in m["id"].lower() or "qwen" in m["model"].lower()), None)
            if found:
                return found
            return next((m for m in models if "qwen" in m["id"].lower() or "qwen" in m["model"].lower()), None)

        if any(k in q for k in ("gemma", "জেমা", "গেমা", "e4b", "৪বি")):
            if "openrouter" in q or "31b" in q:
                found = self._cfg("openrouter-gemma")
                if found:
                    return found
            found = next((m for m in locals_ if "gemma" in m["id"].lower() or "gemma" in m["model"].lower()), None)
            if found:
                return found
            return next((m for m in models if "gemma" in m["id"].lower() or "gemma" in m["model"].lower()), None)

        # ক্লাউড মডেলগুলোর Alias
        if any(k in q for k in ("gemini 3.8", "gemini-3.8", "3.8", "৩.৮")):
            if m := self._cfg("gemini-38-flash"):
                return m
        if any(k in q for k in ("gemini 3.1", "gemini-3.1", "3.1", "৩.১", "gemini pro", "জেমিনি প্রো")):
            if m := self._cfg("gemini-31-pro"):
                return m
        if any(k in q for k in ("gemini 3.5", "gemini-3.5", "3.5", "৩.৫")):
            if m := self._cfg("gemini-flash"):
                return m
        if any(k in q for k in ("gemini", "google", "জেমিনি", "গুগল")):
            return self._cfg("gemini-flash") or next((m for m in models if "gemini" in m["id"].lower()), None)

        if any(k in q for k in ("gpt 4o mini", "gpt-4o-mini", "4o mini", "মিনি")):
            if m := self._cfg("github-gpt"):
                return m
        if any(k in q for k in ("gpt", "4o", "github", "জিপিটি", "গিটহাব")):
            return self._cfg("github-gpt-4o") or self._cfg("github-gpt") or next((m for m in models if "gpt" in m["id"].lower()), None)

        if any(k in q for k in ("openrouter", "nemotron", "ওপেনরাউটার")):
            return self._cfg("openrouter-nemotron") or next((m for m in models if "openrouter" in self._provider_name(m).lower()), None)
        if any(k in q for k in ("groq", "গ্রক")):
            return self._cfg("groq-llama") or next((m for m in models if "groq" in m["id"].lower()), None)
        if any(k in q for k in ("cerebras", "সেরেব্রাস")):
            return self._cfg("cerebras-llama") or next((m for m in models if "cerebras" in m["id"].lower()), None)
        if any(k in q for k in ("mistral", "মিস্ট্রাল")):
            return self._cfg("mistral-small") or next((m for m in models if "mistral" in m["id"].lower()), None)
        if any(k in q for k in ("nvidia", "nim", "এনভিডিয়া")):
            return self._cfg("nvidia-nim") or next((m for m in models if "nvidia" in m["id"].lower()), None)

        # সাধারণ লোকাল / অফলাইন রিকোয়েস্ট
        if any(k in q for k in ("local", "ollama", "লোকাল", "অফলাইন", "offline", "ওলামা")):
            cur = self._cfg(self.active or "")
            if cur and self._is_local(cur):
                return cur
            return self._cfg("local-qwen") or (locals_[0] if locals_ else None)

        # ডিরেক্ট ID / model / label সাবস্ট্রিং ম্যাচ
        for m in models:
            mid = m["id"].lower()
            mcode = m.get("model", "").lower()
            mlabel = m.get("label", "").lower()
            pname = self._provider_name(m).lower()
            if mid in q or mcode in q or (mlabel and mlabel in q) or (pname and pname in q):
                return m
        return None

    async def switch_by_command(self, query: str = "", mode: str | None = None) -> dict[str, Any]:
        """কমান্ড দিয়ে মডেল বা মোড পরিবর্তন করে এবং UI-তে লাইভ ইভেন্ট পাঠায়।"""
        target = self.find_model(query) if query.strip() else None
        if query.strip() and not target and mode not in ("auto", "manual"):
            raise ValueError(f"'{query}' নামের কোনো মডেল খুঁজে পাওয়া যায়নি")

        if mode in ("auto", "manual"):
            target_mode = mode
        elif target:
            target_mode = "manual"
        else:
            target_mode = self.mode

        target_id = target["id"] if target else (self.active or self.manual_model)
        self.set_mode(target_mode, target_id if self._cfg(target_id) else None)
        cfg = self._cfg(self.active or "") or target
        if cfg:
            await bus.emit(
                "model_active",
                id=cfg["id"],
                label=cfg.get("label", cfg["id"]),
                model=cfg.get("model", cfg["id"]),
                local=self._is_local(cfg),
                mode=self.mode,
            )
        await bus.emit("brain_state", **self.state())
        return {"ok": True, "mode": self.mode, "model": cfg}

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
                settings.save_brain_config(self.mode, self.manual_model)

    def update_model(self, model_id: str, updates: dict[str, Any]) -> None:
        import re
        cfg = self._cfg(model_id)
        if not cfg:
            raise ValueError(f"Model '{model_id}' not found")
        if "label" in updates and str(updates["label"]).strip():
            cfg["label"] = str(updates["label"]).strip()
        if "provider_name" in updates and str(updates["provider_name"]).strip():
            cfg["provider_name"] = str(updates["provider_name"]).strip()
        if "model" in updates and str(updates["model"]).strip():
            cfg["model"] = str(updates["model"]).strip()
        if "base_url" in updates and str(updates["base_url"]).strip():
            cfg["base_url"] = str(updates["base_url"]).strip()
        if "priority" in updates and updates["priority"] is not None:
            cfg["priority"] = int(updates["priority"])
        if "vision" in updates:
            cfg["vision"] = bool(updates["vision"])
        if not self._is_local(cfg):
            if "api_key_env" in updates and str(updates["api_key_env"]).strip():
                env_name = re.sub(r"[^A-Z0-9_]", "_", str(updates["api_key_env"]).strip().upper())
                if env_name:
                    cfg["api_key_env"] = env_name
            if "api_key" in updates and cfg.get("api_key_env"):
                settings.set_env(cfg["api_key_env"], str(updates["api_key"] or "").strip())
        self.cooldown.pop(model_id, None)
        settings.save_models(settings.models)

    def reset_single_default(self, model_id: str) -> None:
        if model_id not in DEFAULT_MODELS_MAP:
            raise ValueError("এটি ডিফল্ট মডেল নয়")
        default_cfg = dict(DEFAULT_MODELS_MAP[model_id])
        idx = next((i for i, m in enumerate(settings.models) if m["id"] == model_id), None)
        if idx is not None:
            settings.models[idx] = default_cfg
        else:
            settings.models.append(default_cfg)
        self.cooldown.pop(model_id, None)
        settings.save_models(settings.models)

    def add_custom_model(self, data: dict[str, Any]) -> dict[str, Any]:
        import re
        provider_name = str(data.get("provider_name") or "").strip()
        model_name = str(data.get("model") or "").strip()
        base_url = str(data.get("base_url") or "").strip()
        existing_prov = None
        if provider_name:
            existing_prov = next(
                (m for m in settings.models if (m.get("provider_name") or "").strip().lower() == provider_name.lower()),
                None,
            )
        if existing_prov:
            if not base_url:
                base_url = str(existing_prov.get("base_url") or "").strip()
            if not data.get("provider"):
                data = dict(data)
                data["provider"] = existing_prov.get("provider", "openai_compat")
            if not data.get("api_key_env") and existing_prov.get("api_key_env"):
                data = dict(data)
                data["api_key_env"] = existing_prov.get("api_key_env")
            provider_name = str(existing_prov.get("provider_name") or provider_name)

        provider = "ollama" if data.get("provider") == "ollama" else "openai_compat"
        label = str(data.get("label") or "").strip() or (f"{model_name} ({provider_name})" if provider_name else model_name)
        if not model_name or not base_url:
            raise ValueError("Model ID এবং Base URL দেওয়া আবশ্যক")
        raw_id = str(data.get("id") or f"{provider_name or label}-{model_name}").lower()
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
                env_key = re.sub(r"[^A-Z0-9]+", "_", (provider_name or mid).upper()) + "_API_KEY"
            new_m["api_key_env"] = env_key
            api_key_val = str(data.get("api_key") or "").strip()
            if api_key_val:
                settings.set_env(env_key, api_key_val)
        settings.models.append(new_m)
        settings.deleted_models = [dm for dm in getattr(settings, "deleted_models", []) if dm.get("id") != mid]
        settings.save_models(settings.models, settings.deleted_models)
        return new_m

    def delete_model(self, model_id: str) -> None:
        if len(settings.models) <= 1:
            raise ValueError("অন্তত ১টি মডেল থাকতে হবে")
        target = self._cfg(model_id)
        if not target:
            raise ValueError(f"Model '{model_id}' পাওয়া যায়নি")
        deleted_list = [dm for dm in getattr(settings, "deleted_models", []) if dm.get("id") != model_id]
        deleted_list.append(dict(target))
        settings.models = [m for m in settings.models if m["id"] != model_id]
        settings.save_models(settings.models, deleted_list)
        if self.active == model_id:
            self.active = None
        if self.preferred_model == model_id:
            self.preferred_model = None

    def delete_provider(self, provider_name: str, clear_key: bool = False) -> int:
        pname = (provider_name or "").strip()
        to_delete = [m for m in settings.models if self._provider_name(m) == pname]
        if not to_delete:
            raise ValueError(f"প্রোভাইডার '{pname}' পাওয়া যায়নি")
        if len(settings.models) - len(to_delete) < 1:
            raise ValueError("সব মডেল মুছে ফেলা যাবে না (অন্তত ১টি মডেল থাকতে হবে)")
        deleted_list = [dm for dm in getattr(settings, "deleted_models", [])]
        del_ids = {m["id"] for m in to_delete}
        deleted_list = [dm for dm in deleted_list if dm.get("id") not in del_ids]
        for m in to_delete:
            deleted_list.append(dict(m))
            if clear_key and m.get("api_key_env"):
                try:
                    settings.set_env(m["api_key_env"], "")
                except Exception:
                    pass
        settings.models = [m for m in settings.models if m["id"] not in del_ids]
        settings.save_models(settings.models, deleted_list)
        if self.active in del_ids:
            self.active = None
        if self.preferred_model in del_ids:
            self.preferred_model = None
        return len(to_delete)

    def restore_model(self, model_id: str) -> dict[str, Any]:
        if self._cfg(model_id):
            return self._cfg(model_id)  # type: ignore[return-value]
        deleted_list = getattr(settings, "deleted_models", [])
        found = next((dm for dm in deleted_list if dm.get("id") == model_id), None)
        if not found and model_id in DEFAULT_MODELS_MAP:
            found = dict(DEFAULT_MODELS_MAP[model_id])
        elif found and model_id in DEFAULT_MODELS_MAP:
            # ডিফল্ট মডেলের ক্ষেত্রে সঠিক লেটেস্ট ডিফল্ট কনফিগ রিস্টোর করি
            found = dict(DEFAULT_MODELS_MAP[model_id])
        if not found:
            raise ValueError(f"রিস্টোর করার মতো মডেল '{model_id}' পাওয়া যায়নি")
        settings.models.append(dict(found))
        new_deleted = [dm for dm in deleted_list if dm.get("id") != model_id]
        settings.save_models(settings.models, new_deleted)
        self.cooldown.pop(model_id, None)
        return found

    def restore_default_models(self) -> int:
        restored = 0
        existing_ids = {m["id"] for m in settings.models}
        for dm in DEFAULT_MODELS:
            mid = dm["id"]
            if mid not in existing_ids:
                settings.models.append(dict(dm))
                restored += 1
            else:
                # ডিফল্ট মডেলের ভাঙা URL বা model ID থাকলে ঠিক করে দেই
                cur = self._cfg(mid)
                if cur:
                    cur["base_url"] = dm["base_url"]
                    cur["model"] = dm["model"]
                    cur["provider_name"] = dm["provider_name"]
        default_ids = set(DEFAULT_MODELS_MAP.keys())
        new_deleted = [dm for dm in getattr(settings, "deleted_models", []) if dm.get("id") not in default_ids]
        settings.save_models(settings.models, new_deleted)
        self.cooldown.clear()
        return restored

    def update_provider(self, provider_name: str, updates: dict[str, Any]) -> int:
        pname = provider_name.strip()
        targets = [
            m for m in settings.models
            if (m.get("provider_name") or "").strip().lower() == pname.lower()
        ]
        if not targets:
            raise ValueError(f"প্রোভাইডার '{pname}' পাওয়া যায়নি")
        new_pname = str(updates.get("provider_name") or "").strip()
        new_base_url = str(updates.get("base_url") or "").strip()
        new_env_key = str(updates.get("api_key_env") or "").strip().upper()
        has_priority = updates.get("priority") not in (None, "")
        for m in targets:
            if new_pname:
                m["provider_name"] = new_pname
            if new_base_url:
                m["base_url"] = new_base_url
            if new_env_key and m.get("provider") != "ollama":
                m["api_key_env"] = new_env_key
            if has_priority:
                m["priority"] = int(updates["priority"])
            self.cooldown.pop(m["id"], None)
        settings.save_models(settings.models, getattr(settings, "deleted_models", []))
        return len(targets)

    def restore_provider(self, provider_name: str) -> int:
        pname = provider_name.strip()
        deleted_list = getattr(settings, "deleted_models", [])
        to_restore = [
            dm for dm in deleted_list
            if (dm.get("provider_name") or dm.get("label") or "").strip().lower() == pname.lower()
        ]
        if not to_restore:
            raise ValueError(f"রিস্টোর করার মতো প্রোভাইডার '{pname}' পাওয়া যায়নি")
        existing_ids = {m["id"] for m in settings.models}
        restored_ids: set[str] = set()
        for dm in to_restore:
            mid = dm.get("id", "")
            restored_ids.add(mid)
            self.cooldown.pop(mid, None)
            if mid not in existing_ids:
                item = dict(DEFAULT_MODELS_MAP[mid]) if mid in DEFAULT_MODELS_MAP else dict(dm)
                settings.models.append(item)
                existing_ids.add(mid)
        new_deleted = [dm for dm in deleted_list if dm.get("id") not in restored_ids]
        settings.save_models(settings.models, new_deleted)
        return len(restored_ids)

    def purge_deleted_model(self, model_id: str) -> None:
        if model_id in DEFAULT_MODELS_MAP:
            raise ValueError("বিল্ট-ইন ডিফল্ট মডেল ট্র্যাশ থেকে স্থায়ীভাবে মুছে ফেলা যায় না")
        new_deleted = [dm for dm in getattr(settings, "deleted_models", []) if dm.get("id") != model_id]
        settings.save_models(settings.models, new_deleted)

    def purge_deleted_provider(self, provider_name: str) -> int:
        pname = provider_name.strip()
        deleted_list = getattr(settings, "deleted_models", [])
        matches = [
            dm for dm in deleted_list
            if (dm.get("provider_name") or dm.get("label") or "").strip().lower() == pname.lower()
        ]
        if not matches:
            return 0
        if any(dm.get("id") in DEFAULT_MODELS_MAP for dm in matches):
            raise ValueError("বিল্ট-ইন ডিফল্ট প্রোভাইডার ট্র্যাশ থেকে স্থায়ীভাবে মুছে ফেলা যায় না")
        purge_ids = {dm.get("id") for dm in matches}
        new_deleted = [dm for dm in deleted_list if dm.get("id") not in purge_ids]
        settings.save_models(settings.models, new_deleted)
        return len(purge_ids)

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
        if self.mode == "manual":
            cfg = self._cfg(self.manual_model)
            if not cfg:
                return []
            if not self._available(cfg):
                return []
            return [cfg]

        online = await self.is_online()
        now = time.time()

        # Auto মোড: সব সচল মডেলের তালিকা (priority অনুযায়ী)
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
        if self.mode == "manual":
            cfg = self._cfg(self.manual_model)
            if not cfg:
                raise LLMError("Manual মোডে সিলেক্ট করা মডেলটি পাওয়া যায়নি। টপবার থেকে একটি মডেল সিলেক্ট করুন।")
            if not self._available(cfg):
                raise LLMError(
                    f"Manual মডেল '{cfg.get('label', cfg['id'])}'-এর API Key সেট করা নেই (অথবা Ollama বন্ধ)। "
                    "Models & Keys থেকে API Key দিন অথবা অন্য মডেল বেছে নিন।"
                )
            if not self._is_local(cfg) and not await self.is_online():
                raise LLMError(
                    f"⚠️ ইন্টারনেট সংযোগ নেই এবং Manual মোডে '{cfg.get('label', cfg['id'])}' লক করা আছে। "
                    "অটো সুইচ করা হয়নি — লোকাল মডেল বেছে নিন অথবা Auto মোডে যান।"
                )
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
                changed_active = self.active != cfg["id"]
                self.active = cfg["id"]
                await bus.emit(
                    "model_active",
                    id=cfg["id"],
                    label=cfg.get("label", cfg["id"]),
                    model=cfg.get("model", cfg["id"]),
                    local=self._is_local(cfg),
                    mode=self.mode,
                )
                if changed_active:
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
                    cd_sec = 1800 if "HTTP 404" in str(e) else (30 if e.network else 60)
                    self.cooldown[cfg["id"]] = time.time() + cd_sec

                if self.mode == "manual":
                    if e.rate_limited:
                        warn_msg = (
                            f"⚠️ {cfg.get('label', cfg['id'])} ({cfg.get('model', cfg['id'])})-এর লিমিট/কোটা শেষ হয়েছে। "
                            "Manual মোড চালু থাকায় অটোমেটিক মডেল পরিবর্তন করা হয়নি — অন্য মডেল সিলেক্ট করুন বা Auto মোডে যান।"
                        )
                        await bus.emit("signal", level="warn", title="limit_reached", text=warn_msg)
                        await bus.emit("brain_state", **self.state())
                        raise LLMError(warn_msg, rate_limited=True, retry_after=e.retry_after)
                    fail_msg = (
                        f"⚠️ Manual মডেল {cfg.get('label', cfg['id'])} ব্যর্থ হয়েছে ({e})। "
                        "Manual মোড লক থাকায় অটো সুইচ করা হয়নি।"
                    )
                    await bus.emit("signal", level="error", title="model_fail", text=fail_msg)
                    await bus.emit("brain_state", **self.state())
                    raise LLMError(fail_msg, network=e.network)

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
        raise LLMError("সব মডেল ব্যর্থ:\n" + "\n".join(errors))


router = ModelRouter()
