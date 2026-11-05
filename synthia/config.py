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
        load_dotenv(ROOT / ".env", override=True)
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

    @classmethod
    def mask_env(cls, name: str | None) -> str:
        val = cls.env(name)
        if not val:
            return ""
        if len(val) <= 8:
            return val[:2] + "••••"
        return f"{val[:4]}••••{val[-4:]}"

    @staticmethod
    def set_env(name: str, value: str) -> None:
        name = (name or "").strip()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("Invalid env key name")
        value = (value or "").strip()
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)

        env_path = ROOT / ".env"
        example_path = ROOT / ".env.example"
        if not env_path.exists() and example_path.exists():
            lines = example_path.read_text(encoding="utf-8").splitlines()
        elif env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        prefix = f"{name}="
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if line.strip().startswith(prefix) or line.strip().startswith(f"{name} ="):
                new_lines.append(f"{name}={value}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"{name}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def save_models(self, models_list: list[dict[str, Any]]) -> None:
        path = CONFIG_DIR / "models.yaml"
        header = (
            "# ==========================================================\n"
            "#  Synthia - মডেল তালিকা (Brain)\n"
            "#  UI বা এই ফাইল থেকে মডেল এবং priority কাস্টমাইজ করা যাবে।\n"
            "# ==========================================================\n"
        )
        content = yaml.safe_dump({"models": models_list}, allow_unicode=True, sort_keys=False)
        path.write_text(header + content, encoding="utf-8")
        self.models = models_list


settings = Settings()
