"""System Skill - অ্যাপ খোলা/বন্ধ, পিসির অবস্থা, ভলিউম/মিডিয়া কন্ট্রোল, (অনুমতিসহ) কমান্ড চালানো।"""
from __future__ import annotations

import ctypes
import difflib
import os
import subprocess
import time
from pathlib import Path

import psutil

from ..core.safety import safety
from ..core.tools import DESTRUCTIVE, SENSITIVE, tool

# সাধারণ অ্যাপের শর্টকাট (বাংলা নামসহ)
APP_ALIASES = {
    "chrome": "chrome", "google chrome": "chrome", "ক্রোম": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "notepad": "notepad", "নোটপ্যাড": "notepad",
    "calculator": "calc", "calc": "calc", "ক্যালকুলেটর": "calc",
    "explorer": "explorer", "file explorer": "explorer", "ফাইল এক্সপ্লোরার": "explorer",
    "cmd": "cmd", "command prompt": "cmd",
    "powershell": "powershell", "terminal": "wt",
    "settings": "ms-settings:", "সেটিংস": "ms-settings:",
    "task manager": "taskmgr", "paint": "mspaint",
    "vscode": "code", "vs code": "code", "visual studio code": "code",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "camera": "microsoft.windows.camera:", "store": "ms-windows-store:",
    "snipping tool": "snippingtool", "control panel": "control",
}

START_MENU_DIRS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
    Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
    Path.home() / "Desktop",
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
]


def _shortcuts() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for d in START_MENU_DIRS:
        if d.exists():
            for f in d.rglob("*"):
                if f.suffix.lower() in (".lnk", ".url", ".exe"):
                    out.setdefault(f.stem.lower(), f)
    return out


@tool("open_app", "Open an application by name (e.g. chrome, notepad, vs code, spotify, photoshop, settings).",
      {"name": {"type": "string", "description": "app name"}}, required=["name"], category="system")
def open_app(name: str) -> str:
    key = name.lower().strip()
    if key in APP_ALIASES:
        target = APP_ALIASES[key]
        try:
            if target.endswith(":"):
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(f'start "" {target}', shell=True)
            return f"OK: opened {name}"
        except Exception as e:  # noqa: BLE001
            return f"ERROR: could not open {name}: {e}"
    shortcuts = _shortcuts()
    match = shortcuts.get(key)
    if not match:
        contains = [k for k in shortcuts if key in k]
        close = contains or difflib.get_close_matches(key, list(shortcuts), n=1, cutoff=0.6)
        if close:
            match = shortcuts[sorted(close, key=len)[0]]
    if match:
        os.startfile(str(match))  # type: ignore[attr-defined]
        return f"OK: opened {match.stem}"
    try:
        subprocess.Popen(f'start "" "{name}"', shell=True)
        return f"Tried to start '{name}' via Windows (no shortcut found; may fail silently)."
    except Exception as e:  # noqa: BLE001
        return f"ERROR: app '{name}' not found: {e}"


@tool("list_running_apps", "List running applications with memory usage (top 25).", category="system")
def list_running_apps() -> str:
    procs: dict[str, float] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            n = p.info["name"] or "?"
            procs[n] = procs.get(n, 0) + p.info["memory_info"].rss / 1e6
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
    top = sorted(procs.items(), key=lambda x: -x[1])[:25]
    return "\n".join(f"{n}: {mb:.0f} MB" for n, mb in top)


@tool("close_app", "Close a running application by process name (e.g. chrome, notepad). Needs user approval "
      "because unsaved work may be lost.",
      {"name": {"type": "string"}}, required=["name"], risk=SENSITIVE, category="system")
async def close_app(name: str) -> str:
    key = name.lower().replace(".exe", "").strip()
    key = APP_ALIASES.get(key, key)
    targets = [p for p in psutil.process_iter(["name", "pid"])
               if (p.info["name"] or "").lower().replace(".exe", "") == key]
    if not targets:
        return f"ERROR: no running process named {name}"
    ok = await safety.request("close_app", f"অ্যাপ বন্ধ: {name} (সেভ না করা কাজ হারাতে পারে)",
                              {"processes": [f"{p.info['name']} (pid {p.info['pid']})" for p in targets[:10]]})
    if not ok:
        return "DENIED: user did not approve closing the app."
    for p in targets:
        try:
            p.terminate()
        except psutil.Error:
            pass
    return f"OK: closed {len(targets)} process(es) of {name}"


def _gpu() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, util, used, total, temp = [x.strip() for x in out.stdout.strip().split(",")]
        return {"name": name, "util": int(util), "vram_used_mb": int(used),
                "vram_total_mb": int(total), "temp_c": int(temp)}
    except Exception:  # noqa: BLE001
        return None


def telemetry() -> dict:
    vm = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({"drive": part.mountpoint, "free_gb": round(u.free / 1e9), "total_gb": round(u.total / 1e9),
                          "pct": u.percent})
        except OSError:
            continue
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram_used_gb": round(vm.used / 1e9, 1), "ram_total_gb": round(vm.total / 1e9, 1), "ram_pct": vm.percent,
        "disks": disks, "gpu": _gpu(), "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


@tool("system_status", "Get PC status: CPU, RAM, GPU (VRAM, temperature), disk space, uptime.", category="system")
def system_status() -> dict:
    psutil.cpu_percent(interval=0.3)
    return telemetry()


# ---------- ভলিউম ও মিডিয়া কী ----------
VK = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD,
      "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _press(vk: int, times: int = 1) -> None:
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


@tool("media_control", "Control volume and media playback (works with YouTube, Spotify, etc).",
      {"action": {"type": "string", "enum": list(VK.keys())},
       "steps": {"type": "integer", "description": "for volume up/down: how many steps (each ~2%). default 5"}},
      required=["action"], category="system")
def media_control(action: str, steps: int = 5) -> str:
    if action not in VK:
        return f"ERROR: unknown action {action}"
    _press(VK[action], steps if action.startswith("volume") else 1)
    return f"OK: {action}"


@tool("run_command", "Run a PowerShell command on the PC. ALWAYS requires user approval. "
      "Use only when no other tool can do the job.",
      {"command": {"type": "string"}, "cwd": {"type": "string", "description": "working folder (optional)"}},
      required=["command"], risk=DESTRUCTIVE, category="system")
async def run_command(command: str, cwd: str = "") -> str:
    ok = await safety.request("run_command", "⚙️ PowerShell কমান্ড চালানো",
                              {"command": command, "cwd": cwd or str(Path.home())})
    if not ok:
        return "DENIED: user did not approve running this command."

    def _run() -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True,
                           text=True, timeout=120, cwd=cwd or None, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return f"exit={r.returncode}\n{r.stdout[-6000:]}\n{r.stderr[-2000:]}".strip()

    import asyncio
    try:
        return await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out (120s)"


@tool("lock_pc", "Lock the Windows screen.", category="system")
def lock_pc() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "OK: locked"
