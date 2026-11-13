"""System, GPU & Local Ollama Monitoring Engine.

Provides live hardware telemetry, GPU monitoring (NVIDIA RTX 3060 Ti via nvidia-smi / NVML patterns),
local Ollama model discovery & VRAM runtime status, and central error logging.
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

from ..config import ROOT, hidden_subprocess_kwargs, settings


class ErrorStore:
    def __init__(self, max_errors: int = 50) -> None:
        self._errors: deque[dict[str, Any]] = deque(maxlen=max_errors)
        self._log_path = ROOT / "logs" / "system_errors.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, title: str, message: str, component: str = "general", level: str = "error") -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "component": component,
            "title": title,
            "message": str(message)[:500],
        }
        self._errors.append(entry)
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                import json
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def list_errors(self, limit: int = 25) -> list[dict[str, Any]]:
        errs = list(self._errors)
        errs.reverse()
        return errs[:limit]


errors = ErrorStore()


async def get_ollama_info() -> dict[str, Any]:
    """Queries local Ollama instance for installed models and models currently loaded in VRAM."""
    base_url = "http://127.0.0.1:11434"
    out: dict[str, Any] = {
        "online": False,
        "base_url": base_url,
        "models": [],
        "running": [],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.5)) as c:
            # 1. Query installed models
            r_tags = await c.get(f"{base_url}/api/tags")
            if r_tags.status_code == 200:
                out["online"] = True
                raw_models = r_tags.json().get("models") or []
                for m in raw_models:
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024 ** 3), 2)
                    details = m.get("details", {})
                    out["models"].append({
                        "name": m.get("name"),
                        "size_gb": size_gb,
                        "modified_at": m.get("modified_at", "")[:19],
                        "parameter_size": details.get("parameter_size", ""),
                        "quantization_level": details.get("quantization_level", ""),
                        "family": details.get("family", ""),
                    })

            # 2. Query running models in VRAM
            try:
                r_ps = await c.get(f"{base_url}/api/ps")
                if r_ps.status_code == 200:
                    raw_ps = r_ps.json().get("models") or []
                    for rm in raw_ps:
                        vram_bytes = rm.get("size_vram", rm.get("size", 0))
                        out["running"].append({
                            "name": rm.get("name"),
                            "size_vram_gb": round(vram_bytes / (1024 ** 3), 2),
                            "expires_at": rm.get("expires_at", "")[:19],
                        })
            except Exception:
                pass
    except Exception:
        out["online"] = False

    return out


def get_gpu_metrics() -> dict[str, Any] | None:
    """Reads NVIDIA GPU telemetry (RTX 3060 Ti) via nvidia-smi with zero external dependencies."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            **hidden_subprocess_kwargs(),
        )
        if out.returncode != 0:
            return None
        parts = [x.strip() for x in out.stdout.strip().split(",")]
        if len(parts) >= 5:
            name = parts[0]
            util = int(parts[1]) if parts[1].isdigit() else 0
            used_mb = int(parts[2]) if parts[2].isdigit() else 0
            total_mb = int(parts[3]) if parts[3].isdigit() else 0
            temp_c = int(parts[4]) if parts[4].isdigit() else 0
            power_w = float(parts[5]) if len(parts) > 5 and parts[5].replace('.', '', 1).isdigit() else 0.0
            return {
                "name": name,
                "util_pct": util,
                "vram_used_mb": used_mb,
                "vram_total_mb": total_mb,
                "vram_pct": round((used_mb / total_mb * 100), 1) if total_mb else 0,
                "temp_c": temp_c,
                "power_watts": power_w,
            }
    except Exception:
        pass
    return None


def get_system_telemetry() -> dict[str, Any]:
    """Captures CPU, RAM, Disk, GPU, and OS performance metrics."""
    vm = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({
                "drive": part.mountpoint,
                "free_gb": round(u.free / 1e9, 1),
                "total_gb": round(u.total / 1e9, 1),
                "pct": u.percent,
            })
        except OSError:
            continue

    return {
        "timestamp": datetime.now().isoformat(),
        "cpu_pct": psutil.cpu_percent(interval=None),
        "cpu_cores": {"physical": psutil.cpu_count(logical=False), "logical": psutil.cpu_count(logical=True)},
        "ram": {
            "used_gb": round(vm.used / 1e9, 1),
            "total_gb": round(vm.total / 1e9, 1),
            "pct": vm.percent,
            "free_gb": round(vm.available / 1e9, 1),
        },
        "disks": disks,
        "gpu": get_gpu_metrics(),
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


async def get_diagnostics() -> dict[str, Any]:
    """Consolidated diagnostic report for dashboard monitoring."""
    telemetry = get_system_telemetry()
    ollama = await get_ollama_info()
    return {
        "system": telemetry,
        "ollama": ollama,
        "recent_errors": errors.list_errors(10),
    }
