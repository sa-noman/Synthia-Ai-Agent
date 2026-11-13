"""Remote Skill - Telegram & Discord Channel Control & Notifications.

Integrates remote bot status and notification tools into Synthia's tool registry.
"""
from __future__ import annotations

from ..channels.manager import channel_manager
from ..core.tools import SAFE, SENSITIVE, tool


@tool("remote_status", "Check the connection status of Telegram and Discord remote bots.",
      category="remote")
def remote_status() -> dict:
    return channel_manager.state()


@tool("send_remote_notification", "Send a status notification message to authorized Telegram or Discord users.",
      {"channel": {"type": "string", "enum": ["telegram", "discord", "all"], "description": "Target channel"},
       "message": {"type": "string", "description": "Notification text to send"}},
      required=["channel", "message"], category="remote")
async def send_remote_notification(channel: str, message: str) -> str:
    channel = channel.lower()
    sent = []

    if channel in ("telegram", "all"):
        tg = channel_manager.telegram
        if tg.status == "connected" and tg.allowed_users:
            for uid in tg.allowed_users:
                ok = await tg.send_message(uid, f"📢 Synthia Notification:\n{message}")
                if ok:
                    sent.append(f"Telegram user {uid}")
        elif not tg.allowed_users:
            sent.append("Telegram (no allowed users configured)")
        else:
            sent.append(f"Telegram ({tg.status})")

    if channel in ("discord", "all"):
        dc = channel_manager.discord
        if dc.status == "connected":
            sent.append(f"Discord ({dc.bot_username})")
        else:
            sent.append(f"Discord ({dc.status})")

    return f"Notification dispatch summary: {', '.join(sent)}"
