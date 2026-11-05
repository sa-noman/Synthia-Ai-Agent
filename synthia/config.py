"""Synthia - সেটিংস লোডার (settings.yaml, models.yaml, .env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.data = _load_yaml("settings.yaml")
        self.models: list[dict[str, Any]] = _load_yaml("models.yaml").get("models", [])

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str, default: str) -> Path:
        p = Path(self.get(dotted, default))
        if not p.is_absolute():
            p = ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def env(name: str | None) -> str:
        if not name:
            return ""
        return os.getenv(name, "").strip()


settings = Settings()
