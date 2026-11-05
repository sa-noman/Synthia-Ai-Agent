"""Synthia Server - FastAPI + WebSocket. UI, Telegram, Discord সবাই এর সাথে কথা বলে।"""
from __future__ import annotations

import asyncio
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import ROOT
from .core.agent import agent
from .core.events import bus
from .core.llm.router import router
from .core.safety import safety
from .core.tools import load_skills, registry
from .desktop import ICON_PATH, install_shortcuts, is_startup_enabled, set_startup, shell
from .voice.manager import voice

UI_DIR = Path(__file__).parent / "ui"


def _load_or_create_token() -> str:
    """লোকাল টোকেন ফাইলে সংরক্ষণ করে যেন রিস্টার্ট দিলেও খোলা UI ট্যাব কখনো বিচ্ছিন্ন না হয়।"""
    tf = ROOT / "synthia_data" / ".access_token"
    try:
        if tf.exists():
            tok = tf.read_text(encoding="utf-8").strip()
            if len(tok) >= 24:
                return tok
        tf.parent.mkdir(parents=True, exist_ok=True)
        tok = secrets.token_urlsafe(24)
        tf.write_text(tok, encoding="utf-8")
        return tok
    except Exception:  # noqa: BLE001
        return secrets.token_urlsafe(24)


# লোকাল অ্যাক্সেস টোকেন + Origin গার্ড — বাইরের কোনো ওয়েবসাইট কমান্ড দিতে পারবে না
ACCESS_TOKEN = _load_or_create_token()
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]", "testserver")


def _is_local_request(host: str | None, origin: str | None) -> bool:
    h = (host or "").split(":")[0].strip().lower()
    if h and h not in _LOCAL_HOSTS:
        return False
    if origin and origin != "null":
        orig = origin.lower()
        if not any(orig.startswith(f"http://{lh}") or orig.startswith(f"https://{lh}") for lh in _LOCAL_HOSTS):
            return False
    return True

load_skills()


class Hub:
    """সব খোলা UI কানেকশনে ইভেন্ট পাঠায়।"""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()
bus.subscribe(hub.broadcast)


async def _telemetry_loop() -> None:
    from .skills.system import telemetry
    psutil.cpu_percent(interval=None)
    tick = 0
    while True:
        await asyncio.sleep(2)
        if not hub.clients:
            continue
        data = await asyncio.to_thread(telemetry)
        tick += 1
        if tick % 15 == 1:
            data["online"] = await router.is_online()
        await bus.emit("telemetry", **data)


MAIN_LOOP: asyncio.AbstractEventLoop | None = None


async def _warm_local_model() -> None:
    """অ্যাপ চালুর সাথে সাথেই ব্যাকগ্রাউন্ডে লোকাল Ollama মডেলটি GPU VRAM-এ লোড করে রাখে,
    যেন প্রথম ভয়েস বা চ্যাট কমান্ডেই ইনস্ট্যান্ট (১ সেকেন্ডে) উত্তর পাওয়া যায়।"""
    import httpx
    from .config import settings

    local_cfg = next((m for m in settings.models if m.get("provider") == "ollama"), None)
    if not local_cfg:
        return
    base_url = local_cfg.get("base_url", "http://127.0.0.1:11434").rstrip("/")
    body = {
        "model": local_cfg["model"],
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {"num_ctx": int(local_cfg.get("num_ctx", 8192)), "num_predict": 1},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=3)) as c:
            await c.post(f"{base_url}/api/chat", json=body)
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    task = asyncio.create_task(_telemetry_loop())
    asyncio.create_task(_warm_local_model())
    yield
    task.cancel()


app = FastAPI(title="Synthia", version=__version__, lifespan=lifespan)
app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


def _check(token: str | None) -> None:
    if not token or not secrets.compare_digest(token, ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="invalid token")


def state() -> dict[str, Any]:
    from .skills.memory import _load, memory_count
    return {
        "version": __version__,
        "brain": router.state(),
        "skills": registry.by_category(),
        "tool_count": len(registry.tools),
        "memory_count": memory_count(),
        "memories": _load()[-50:],
        "pending_confirms": safety.pending,
        "busy": agent.busy,
        "startup_enabled": is_startup_enabled(),
        "voice": voice.state(),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(ICON_PATH)


@app.post("/api/show")
async def api_show(token: str) -> JSONResponse:
    _check(token)
    await asyncio.to_thread(shell.show_window)
    return JSONResponse({"ok": True})


@app.get("/api/bootstrap")
async def api_bootstrap(request: Request) -> JSONResponse:
    """শুধুমাত্র লোকালহোস্ট UI-কে সক্রিয় টোকেন দেয় (বাইরের ওয়েবসাইট ব্লকড)।"""
    if not _is_local_request(request.headers.get("host"), request.headers.get("origin")):
        raise HTTPException(status_code=403, detail="forbidden origin")
    return JSONResponse({"token": ACCESS_TOKEN})


@app.get("/api/state")
async def api_state(token: str) -> JSONResponse:
    _check(token)
    return JSONResponse(state())


@app.post("/api/command")
async def api_command(request: Request) -> JSONResponse:
    """Telegram / Discord / Antigravity (MCP) থেকে কমান্ড।"""
    body = await request.json()
    _check(body.get("token"))
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    reply = await agent.run(text, session=body.get("session", "api"), source=body.get("source", "api"))
    return JSONResponse({"reply": reply})


async def handle_ws_message(msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    if kind == "command":
        text = (msg.get("text") or "").strip()
        if text:
            # ব্যাকগ্রাউন্ডে চালাই, যাতে কাজ চলাকালীনও অনুমতি (confirm) বাটন কাজ করে
            asyncio.create_task(agent.run(text, session="ui", source="ui", images=msg.get("images")))
    elif kind == "confirm":
        safety.resolve(str(msg.get("id")), bool(msg.get("approved")), channel="ui")
    elif kind == "set_model":
        try:
            router.set_mode(msg.get("mode", "auto"), msg.get("model_id"))
        except ValueError as e:
            await bus.emit("signal", level="error", title="model", text=str(e))
        await bus.emit("brain_state", **router.state())
    elif kind == "cancel":
        kill_switch()
    elif kind == "reset":
        agent.reset("ui")
        await bus.emit("signal", level="info", title="reset", text="নতুন কথোপকথন শুরু")
    elif kind == "state":
        await bus.emit("state", **state())
    elif kind == "install_shortcuts":
        created = await asyncio.to_thread(install_shortcuts, True, True)
        await bus.emit("signal", level="ok", title="shortcuts",
                       text=f"শর্টকাট তৈরি হয়েছে ({len(created)}টি)")
    elif kind == "set_startup":
        on = await asyncio.to_thread(set_startup, bool(msg.get("enabled")))
        await bus.emit("state", **state())
        await bus.emit("signal", level="ok", title="startup",
                       text="Windows Auto-start চালু" if on else "Windows Auto-start বন্ধ")
    elif kind == "quit_app":
        threading.Thread(target=shell.quit_app, daemon=True).start()
    elif kind == "voice_toggle":
        await voice.toggle_mic()
    elif kind == "voice_set":
        await voice.set_mic(bool(msg.get("enabled")))
    elif kind == "voice_always":
        await voice.set_mic(bool(msg.get("enabled")))
    elif kind == "voice_listen_toggle":
        if voice.listening:
            await voice.stop_listening(commit=True)
        else:
            await voice.start_listening(force_mic_on=bool(msg.get("force", False)))
    elif kind == "voice_listen":
        await voice.start_listening(force_mic_on=bool(msg.get("force", False)))
    elif kind == "voice_stop_listen":
        await voice.stop_listening(commit=bool(msg.get("commit", True)))
    elif kind == "voice_persona":
        await voice.set_persona(str(msg.get("persona", "female")))
    elif kind == "voice_mute":
        await voice.set_muted(bool(msg.get("muted")))
    elif kind == "audio_done":
        voice.notify_audio_done()


def kill_switch() -> None:
    agent.cancel()
    safety.deny_all("kill_switch")
    bus.emit_nowait("signal", level="error", title="kill_switch", text="⛔ সব কাজ বন্ধ করা হলো")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not _is_local_request(ws.headers.get("host"), ws.headers.get("origin")):
        await ws.close(code=4403)
        return
    if ws.query_params.get("token") != ACCESS_TOKEN:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_json({"type": "state", **state()})
    try:
        while True:
            msg = await ws.receive_json()
            try:
                await handle_ws_message(msg)
            except Exception as e:  # noqa: BLE001
                await bus.emit("signal", level="error", title="core", text=str(e)[:120])
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        hub.clients.discard(ws)
