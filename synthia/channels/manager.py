"""Remote Channel Manager - Coordinates Telegram & Discord bridges.

Allows independent starting, stopping, and status reporting of remote channels.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .discord_channel import discord_channel
from .telegram_channel import telegram_channel


class ChannelManager:
    def __init__(self) -> None:
        self.telegram = telegram_channel
        self.discord = discord_channel

    def state(self) -> dict[str, Any]:
        return {
            "telegram": self.telegram.state(),
            "discord": self.discord.state(),
        }

    async def start_all(self) -> None:
        """Starts configured channels automatically if tokens are present."""
        tasks = []
        if self.telegram.bot_token:
            tasks.append(self.telegram.start())
        if self.discord.bot_token:
            tasks.append(self.discord.start())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        await asyncio.gather(
            self.telegram.stop(),
            self.discord.stop(),
            return_exceptions=True,
        )

    async def toggle_channel(self, name: str, enable: bool) -> dict[str, Any]:
        ch = self.telegram if name == "telegram" else (self.discord if name == "discord" else None)
        if not ch:
            return {"ok": False, "error": f"Unknown channel '{name}'"}

        if enable:
            await ch.start()
        else:
            await ch.stop()
        return {"ok": True, "state": ch.state()}


channel_manager = ChannelManager()
