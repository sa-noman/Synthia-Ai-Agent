"""Voice Skill — কথার মাধ্যমেই ভয়েস পার্সোনা (Female/Male) বা মিউট পরিবর্তন।"""
from __future__ import annotations

from ..core.tools import tool
from ..voice.manager import voice


@tool("set_voice_options", "Change Synthia's spoken voice gender ('female' or 'male') or mute/unmute voice output.",
      {"persona": {"type": "string", "enum": ["female", "male"], "description": "female (Synthia) or male"},
       "muted": {"type": "boolean", "description": "true to mute voice replies, false to unmute"}},
      category="voice")
async def set_voice_options(persona: str = "", muted: bool | None = None) -> str:
    if persona in ("female", "male"):
        await voice.set_persona(persona)
    if muted is not None:
        await voice.set_muted(bool(muted))
    return f"OK: persona={voice.persona}, muted={voice.muted}"
