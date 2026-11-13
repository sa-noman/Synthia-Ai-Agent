"""Telegram Bot Channel Adapter - Pure httpx implementation (Zero heavy dependencies).

Supports:
1. Long-polling via getUpdates without public webhook/IP requirement.
2. Strict Chat ID allowlist authentication.
3. Command execution via Synthia Agent.
4. Interactive SafetyGate approvals via Inline Keyboards.
5. Message splitting for Telegram 4096 char limits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import textwrap
from typing import Any

import httpx

from ..config import settings
from ..core.events import bus
from ..core.safety import safety

logger = logging.getLogger(__name__)


class TelegramChannel:
    def __init__(self) -> None:
        self.bot_token: str = ""
        self.allowed_users: set[int] = set()
        self.bot_username: str = ""
        self.status: str = "disconnected"  # "connected", "connecting", "disconnected", "unconfigured", "error"
        self._stop_event = asyncio.Event()
        self._poll_task: asyncio.Task | None = None
        self._last_update_id = 0
        self._safety_sub = None
        self.reload_config()

    def reload_config(self) -> None:
        self.bot_token = settings.env("TELEGRAM_BOT_TOKEN") or str(settings.get("channels.telegram.token", "")).strip()
        raw_allowed = settings.env("TELEGRAM_ALLOWED_USERS") or str(settings.get("channels.telegram.allowed_users", "")).strip()
        self.allowed_users = set()
        for part in raw_allowed.split(","):
            part = part.strip()
            if part.isdigit():
                self.allowed_users.add(int(part))
        if not self.bot_token:
            self.status = "unconfigured"

    def state(self) -> dict[str, Any]:
        return {
            "channel": "telegram",
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
        if self._poll_task and not self._poll_task.done():
            return

        self._stop_event.clear()
        self.status = "connecting"
        await bus.emit("signal", level="info", title="telegram", text="Telegram সংযোগ শুরু হচ্ছে...")

        # Subscribe to safety confirm requests to forward them to Telegram
        if not self._safety_sub:
            self._safety_sub = self._on_bus_event
            bus.subscribe(self._safety_sub)

        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        self.status = "disconnected"
        await bus.emit("signal", level="info", title="telegram", text="Telegram সংযোগ বন্ধ")

    async def _on_bus_event(self, ev: dict[str, Any]) -> None:
        if ev.get("type") == "confirm_request" and self.status == "connected":
            req_id = ev.get("id")
            tool = ev.get("tool")
            title = ev.get("title")
            details = ev.get("details", {})
            for uid in self.allowed_users:
                await self.send_approval_request(uid, req_id, tool, title, details)

    async def send_message(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> bool:
        if not self.bot_token:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        chunks = textwrap.wrap(text, width=4000, break_long_words=True, replace_whitespace=False) or [text]
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
            for idx, chunk in enumerate(chunks):
                payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
                if idx == len(chunks) - 1 and reply_markup:
                    payload["reply_markup"] = reply_markup
                try:
                    r = await c.post(url, json=payload)
                    if r.status_code != 200:
                        logger.warning(f"Telegram send error {r.status_code}: {r.text}")
                except Exception as e:
                    logger.warning(f"Telegram send failed: {e}")
                    return False
        return True

    async def send_approval_request(self, chat_id: int, req_id: str, tool: str, title: str, details: dict[str, Any]) -> None:
        text = (
            f"🔒 *অনুমতি প্রয়োজন (Synthia Safety Gate)*\n\n"
            f"📌 *কাজ:* {title}\n"
            f"🛠️ *টুল:* `{tool}`\n"
            f"📋 *বিবরণ:* `{json.dumps(details, ensure_ascii=False)[:300]}`\n\n"
            f"আপনি কি এই কাজটি চালানোর অনুমতি দিচ্ছেন?"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✔ হ্যাঁ, অনুমোদন দিলাম", "callback_data": f"approve:{req_id}"},
                    {"text": "✖ না, বাতিল", "callback_data": f"deny:{req_id}"},
                ]
            ]
        }
        await self.send_message(chat_id, text, reply_markup=reply_markup)

    async def _poll_loop(self) -> None:
        base_url = f"https://api.telegram.org/bot{self.bot_token}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=6.0)) as c:
            # 1. Verify token & getMe
            try:
                r_me = await c.get(f"{base_url}/getMe")
                if r_me.status_code != 200:
                    self.status = "error"
                    await bus.emit("signal", level="error", title="telegram", text=f"টোকেন ভুল (HTTP {r_me.status_code})")
                    return
                me = r_me.json().get("result", {})
                self.bot_username = me.get("username", "")
                self.status = "connected"
                await bus.emit("signal", level="ok", title="telegram", text=f"Telegram সংযুক্ত: @{self.bot_username}")
            except Exception as e:
                self.status = "error"
                await bus.emit("signal", level="error", title="telegram", text=f"Telegram কানেক্ট ব্যর্থ: {e}")
                return

            # 2. Main long-polling loop
            while not self._stop_event.is_set():
                try:
                    params = {"offset": self._last_update_id + 1, "timeout": 25}
                    r = await c.get(f"{base_url}/getUpdates", params=params)
                    if r.status_code == 200:
                        updates = r.json().get("result", [])
                        for u in updates:
                            self._last_update_id = max(self._last_update_id, u["update_id"])
                            await self._handle_update(c, base_url, u)
                    elif r.status_code in (401, 404):
                        self.status = "error"
                        await bus.emit("signal", level="error", title="telegram", text="Telegram টোকেন বাতিল হয়েছে")
                        break
                    else:
                        await asyncio.sleep(3.0)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Telegram poll exception: {e}")
                    await asyncio.sleep(3.0)

    async def _handle_update(self, client: httpx.AsyncClient, base_url: str, update: dict[str, Any]) -> None:
        # Handle Inline Button Callback
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb["id"]
            user_id = cb.get("from", {}).get("id")
            data = cb.get("data", "")
            if user_id not in self.allowed_users:
                await client.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "অননুমোদিত!", "show_alert": True})
                return

            if data.startswith("approve:"):
                req_id = data.split(":", 1)[1]
                safety.resolve(req_id, True, channel="telegram")
                await client.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "অনুমোদন সম্পন্ন ✔"})
            elif data.startswith("deny:"):
                req_id = data.split(":", 1)[1]
                safety.resolve(req_id, False, channel="telegram")
                await client.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "বাতিল করা হয়েছে ✖"})
            return

        msg = update.get("message")
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        user_id = msg.get("from", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not text:
            return

        # Security check: User must be in allowlist
        if user_id not in self.allowed_users:
            await bus.emit("signal", level="warn", title="telegram_auth",
                           text=f"অননুমোদিত বার্তা: User {user_id} (@{msg.get('from', {}).get('username')})")
            await self.send_message(
                chat_id,
                f"⛔ অননুমোদিত অ্যাক্সেস।\nআপনার User ID: `{user_id}` Synthia-র অনুমোদন তালিকায় যুক্ত নেই।"
            )
            return

        # Built-in Telegram Commands
        if text == "/start":
            reply = (
                f"👋 হ্যালো! আমি **Synthia** — আপনার পার্সোনাল এআই কমান্ড ব্রিজ।\n\n"
                f"পিসি নিয়ন্ত্রণ বা যেকোনো কাজের নির্দেশ বাংলায় বা ইংরেজিতে লিখুন।\n\n"
                f"কমান্ডসমূহ:\n"
                f"• `/status` - পিসির সিপিইউ, র্যাম ও মডেল অবস্থা\n"
                f"• `/stop` - চলমান কাজ বন্ধ (Emergency Kill Switch)\n"
                f"• `/models` - উপলব্ধ এআই মডেলের তালিকা"
            )
            await self.send_message(chat_id, reply)
            return

        if text == "/status":
            from ..core.monitoring import get_system_telemetry
            tele = get_system_telemetry()
            gpu_str = f"{tele['gpu']['name']} ({tele['gpu']['temp_c']}°C)" if tele.get("gpu") else "N/A"
            status_text = (
                f"🖥️ *Synthia সিস্টেম স্ট্যাটাস:*\n\n"
                f"• CPU: `{tele['cpu_pct']}%`\n"
                f"• RAM: `{tele['ram']['used_gb']} GB / {tele['ram']['total_gb']} GB ({tele['ram']['pct']}%)`\n"
                f"• GPU: `{gpu_str}`\n"
                f"• আপটাইম: `{tele['uptime_h']} ঘণ্টা`"
            )
            await self.send_message(chat_id, status_text)
            return

        if text in ("/stop", "/cancel"):
            from ..server import kill_switch
            kill_switch()
            await self.send_message(chat_id, "⛔ Kill switch সক্রিয় করা হয়েছে। সব চলমান কাজ বন্ধ।")
            return

        # Agent execution
        await bus.emit("signal", level="info", title="telegram_cmd", text=f"টিলেগ্রাম কমান্ড: {text[:60]}")
        await self.send_message(chat_id, "⏳ কাজ শুরু করছি...")

        from ..core.agent import agent
        try:
            res = await agent.run(text, session=f"telegram_{chat_id}", source="telegram")
            await self.send_message(chat_id, res)
        except Exception as e:
            await self.send_message(chat_id, f"⚠️ ত্রুটি: {e}")


telegram_channel = TelegramChannel()
