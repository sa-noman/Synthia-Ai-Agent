"""Discord Bot Channel Adapter - Pure websockets + httpx implementation (Zero heavy libraries).

Supports:
1. Discord Gateway v10 WebSocket connection for real-time inbound events.
2. Heartbeat management and reconnects.
3. Strict User ID allowlist verification.
4. Agent command execution and status reporting.
5. Message splitting for Discord 2000 character limits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import textwrap
from typing import Any

import httpx
import websockets

from ..config import settings
from ..core.events import bus
from ..core.safety import safety

logger = logging.getLogger(__name__)


class DiscordChannel:
    def __init__(self) -> None:
        self.bot_token: str = ""
        self.allowed_users: set[str] = set()
        self.bot_username: str = ""
        self.status: str = "disconnected"
        self._stop_event = asyncio.Event()
        self._gateway_task: asyncio.Task | None = None
        self._ws: Any = None
        self._seq: int | None = None
        self._safety_sub = None
        self.reload_config()

    def reload_config(self) -> None:
        self.bot_token = settings.env("DISCORD_BOT_TOKEN") or str(settings.get("channels.discord.token", "")).strip()
        raw_allowed = settings.env("DISCORD_ALLOWED_USERS") or str(settings.get("channels.discord.allowed_users", "")).strip()
        self.allowed_users = set()
        for part in raw_allowed.split(","):
            part = part.strip()
            if part:
                self.allowed_users.add(part)
        if not self.bot_token:
            self.status = "unconfigured"

    def state(self) -> dict[str, Any]:
        return {
            "channel": "discord",
            "status": self.status,
            "bot_username": self.bot_username,
            "configured": bool(self.bot_token),
            "allowed_users_count": len(self.allowed_users),
        }

    async def start(self) -> None:
        self.reload_config()
        if not self.bot_token:
            self.status = "unconfigured"
            return
        if self._gateway_task and not self._gateway_task.done():
            return

        self._stop_event.clear()
        self.status = "connecting"
        await bus.emit("signal", level="info", title="discord", text="Discord সংযোগ শুরু হচ্ছে...")

        if not self._safety_sub:
            self._safety_sub = self._on_bus_event
            bus.subscribe(self._safety_sub)

        self._gateway_task = asyncio.create_task(self._gateway_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._gateway_task:
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except (asyncio.CancelledError, Exception):
                pass
            self._gateway_task = None
        self.status = "disconnected"
        await bus.emit("signal", level="info", title="discord", text="Discord সংযোগ বন্ধ")

    async def _on_bus_event(self, ev: dict[str, Any]) -> None:
        if ev.get("type") == "confirm_request" and self.status == "connected":
            req_id = ev.get("id")
            tool = ev.get("tool")
            title = ev.get("title")
            details = ev.get("details", {})
            # If channels or users are configured, notify them
            pass

    async def send_message(self, channel_id: str, content: str) -> bool:
        if not self.bot_token or not channel_id:
            return False
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }
        chunks = textwrap.wrap(content, width=1950, break_long_words=True, replace_whitespace=False) or [content]
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
            for chunk in chunks:
                try:
                    r = await c.post(url, json={"content": chunk}, headers=headers)
                    if r.status_code >= 300:
                        logger.warning(f"Discord send error {r.status_code}: {r.text}")
                except Exception as e:
                    logger.warning(f"Discord send failed: {e}")
                    return False
        return True

    async def _gateway_loop(self) -> None:
        gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"
        headers = {"Authorization": f"Bot {self.bot_token}"}

        # 1. Verify token via /users/@me
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as c:
                r_me = await c.get("https://discord.com/api/v10/users/@me", headers=headers)
                if r_me.status_code != 200:
                    self.status = "error"
                    await bus.emit("signal", level="error", title="discord", text=f"টোকেন ভুল (HTTP {r_me.status_code})")
                    return
                me = r_me.json()
                self.bot_username = f"{me.get('username')}#{me.get('discriminator', '0')}"
        except Exception as e:
            self.status = "error"
            await bus.emit("signal", level="error", title="discord", text=f"সংযোগ সমস্যা: {e}")
            return

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(gateway_url, max_size=16 * 1024 * 1024) as ws:
                    self._ws = ws
                    # Wait for Op 10 Hello
                    hello_raw = await ws.recv()
                    hello = json.loads(hello_raw)
                    heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0

                    # Start background heartbeat task
                    hb_task = asyncio.create_task(self._heartbeat(ws, heartbeat_interval))

                    # Send Op 2 Identify
                    # Intents: Guilds (1) + Guild Messages (512) + Direct Messages (4096) + Message Content (32768) = 37377
                    identify = {
                        "op": 2,
                        "d": {
                            "token": self.bot_token,
                            "intents": 37377,
                            "properties": {"os": "windows", "browser": "synthia", "device": "synthia"},
                        },
                    }
                    await ws.send(json.dumps(identify))
                    self.status = "connected"
                    await bus.emit("signal", level="ok", title="discord", text=f"Discord সংযুক্ত: {self.bot_username}")

                    try:
                        async for msg_raw in ws:
                            data = json.loads(msg_raw)
                            op = data.get("op")
                            if op == 0:  # Dispatch event
                                self._seq = data.get("s")
                                t = data.get("t")
                                if t == "MESSAGE_CREATE":
                                    await self._handle_message(data.get("d", {}))
                            elif op == 7:  # Reconnect
                                break
                            elif op == 9:  # Invalid session
                                await asyncio.sleep(2.0)
                                break
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Discord gateway connection error: {e}")
                self.status = "error"
                await asyncio.sleep(5.0)

    async def _heartbeat(self, ws: Any, interval: float) -> None:
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(interval)
                await ws.send(json.dumps({"op": 1, "d": self._seq}))
        except (asyncio.CancelledError, Exception):
            pass

    async def _handle_message(self, d: dict[str, Any]) -> None:
        author = d.get("author", {})
        if author.get("bot"):
            return

        author_id = str(author.get("id"))
        channel_id = str(d.get("channel_id"))
        content = (d.get("content") or "").strip()
        if not content:
            return

        # Security check: User must be in allowlist
        if author_id not in self.allowed_users:
            await bus.emit("signal", level="warn", title="discord_auth",
                           text=f"অননুমোদিত Discord বার্তা: User {author_id} ({author.get('username')})")
            await self.send_message(
                channel_id,
                f"⛔ **Unauthorized:** Your Discord User ID (`{author_id}`) is not in Synthia's authorization allowlist."
            )
            return

        # Commands
        if content in ("!status", "/status"):
            from ..core.monitoring import get_system_telemetry
            tele = get_system_telemetry()
            gpu_str = f"{tele['gpu']['name']} ({tele['gpu']['temp_c']}°C)" if tele.get("gpu") else "N/A"
            status_text = (
                f"🖥️ **Synthia System Status**\n"
                f"• **CPU:** `{tele['cpu_pct']}%`\n"
                f"• **RAM:** `{tele['ram']['used_gb']} GB / {tele['ram']['total_gb']} GB`\n"
                f"• **GPU:** `{gpu_str}`\n"
                f"• **Uptime:** `{tele['uptime_h']} hours`"
            )
            await self.send_message(channel_id, status_text)
            return

        if content in ("!stop", "/stop"):
            from ..server import kill_switch
            kill_switch()
            await self.send_message(channel_id, "⛔ Emergency Stop activated. All current tasks cancelled.")
            return

        if content.startswith("!approve "):
            req_id = content.split(" ", 1)[1].strip()
            safety.resolve(req_id, True, channel="discord")
            await self.send_message(channel_id, f"✔ Approved request `{req_id}`.")
            return

        if content.startswith("!deny "):
            req_id = content.split(" ", 1)[1].strip()
            safety.resolve(req_id, False, channel="discord")
            await self.send_message(channel_id, f"✖ Denied request `{req_id}`.")
            return

        # Run agent task
        await bus.emit("signal", level="info", title="discord_cmd", text=f"Discord কমান্ড: {content[:60]}")
        await self.send_message(channel_id, "⏳ Synthia is processing your request...")

        from ..core.agent import agent
        try:
            res = await agent.run(content, session=f"discord_{channel_id}", source="discord")
            await self.send_message(channel_id, res)
        except Exception as e:
            await self.send_message(channel_id, f"⚠️ Error: {e}")


discord_channel = DiscordChannel()
