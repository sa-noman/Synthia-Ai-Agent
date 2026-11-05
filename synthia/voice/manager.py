"""Voice Manager — ইউনিফায়েড মাইক্রোফোন সুইচ (Strict ON / OFF):
  * mic_on == False হলে হার্ডওয়্যার মাইক্রোফোন সম্পূর্ণ বন্ধ এবং কোনো অডিও প্রসেস করা হয় না।
  * mic_on == True করলেই কেবল কথা শুনবে (কথা বলার সময় ইকো এড়াতে সাময়িক বিরতি দিয়ে আবার শুনবে)।
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from ..core.agent import agent
from ..core.events import bus
from .mic import has_microphone, record_utterance
from .stt import transcribe
from .tts import synthesize


class VoiceManager:
    def __init__(self) -> None:
        self.persona: str = "female"   # "female" (Synthia) | "male"
        self.muted: bool = False       # ভয়েস উত্তর চালু/বন্ধ
        self.mic_on: bool = False      # ইউনিফায়েড মাইক্রোফোন সুইচ (শুরুতে সম্পূর্ণ OFF!)
        self.listening: bool = False   # এই মুহূর্তে মাইক খোলা আছে কি না
        self.transcribing: bool = False
        self.speaking: bool = False

        self._stop_record = threading.Event()
        self._abort_record = threading.Event()
        self._audio_done = asyncio.Event()
        self._mic_task: asyncio.Task | None = None
        self._speak_task: asyncio.Task | None = None
        self._last_level_emit = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

        bus.subscribe(self._on_bus_event)

    def state(self) -> dict[str, Any]:
        return {
            "has_mic": has_microphone(),
            "persona": self.persona,
            "muted": self.muted,
            "mic_on": self.mic_on,
            "listening": self.listening,
            "transcribing": self.transcribing,
            "speaking": self.speaking,
        }

    async def broadcast_state(self) -> None:
        await bus.emit("voice_state", **self.state())

    async def _on_bus_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "chat" and ev.get("role") == "assistant" and not ev.get("partial"):
            if not self.muted and ev.get("text"):
                await self.speak(ev["text"])
        elif t == "signal" and ev.get("title") == "kill_switch":
            await self.stop_all()

    def _emit_level_threadsafe(self, level: float, is_voice: bool) -> None:
        if not self.mic_on:
            return
        now = time.monotonic()
        if now - self._last_level_emit < 0.06:
            return
        self._last_level_emit = now
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: bus.emit_nowait("voice_level", level=round(level, 3), speech=is_voice)
            )

    # ---------- কথা বলা (TTS) ----------
    async def speak(self, text: str) -> None:
        await self.stop_speaking()
        if self.muted:
            return
        self.speaking = True
        self._audio_done.clear()

        async def _job() -> None:
            await self.broadcast_state()
            await bus.emit("status", state="speaking")
            try:
                payload = await synthesize(text, self.persona)
                if payload.get("mode") == "none":
                    return
                await bus.emit("audio_play", **payload)
                timeout = min(40.0, max(4.0, len(text) * 0.11))
                try:
                    await asyncio.wait_for(self._audio_done.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                await bus.emit("audio_stop")
                raise
            except Exception as e:  # noqa: BLE001
                await bus.emit("signal", level="warn", title="tts", text=f"ভয়েস প্লে সমস্যা: {e}")
            finally:
                self.speaking = False
                await self.broadcast_state()
                if not agent.busy:
                    await bus.emit("status", state="listening" if self.listening else "idle")

        self._speak_task = asyncio.create_task(_job())

    async def stop_speaking(self) -> None:
        self._audio_done.set()
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
            try:
                await self._speak_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.speaking = False
        await bus.emit("audio_stop")

    def notify_audio_done(self) -> None:
        self._audio_done.set()

    # ---------- মাইক্রোফোন ON / OFF ও অন-ডিমান্ড লিসেনিং ----------
    async def toggle_mic(self) -> None:
        await self.set_mic(not self.mic_on)

    async def set_mic(self, enabled: bool) -> None:
        self._loop = asyncio.get_running_loop()
        want = bool(enabled)
        was_on = self.mic_on

        if not want:
            # 🔒 STRICT MIC OFF: হার্ডওয়্যার ও চলমান লিসেনিং সাথে সাথে বন্ধ
            self.mic_on = False
            self._abort_record.set()
            self._stop_record.set()
            if self._mic_task and not self._mic_task.done():
                self._mic_task.cancel()
                try:
                    await self._mic_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self.listening = False
            self.transcribing = False
            await bus.emit("voice_level", level=0.0, speech=False)
            await self.broadcast_state()
            if not agent.busy and not self.speaking:
                await bus.emit("status", state="idle")
            if was_on:
                await bus.emit("signal", level="info", title="mic", text="🔇 Mic: Off — মাইক্রোফোন বন্ধ")
            return

        # Mic ON করার সময় যদি Synthia কথা বলতে থাকে, তবে কথা থামাবে
        if self.speaking:
            await self.stop_speaking()

        self.mic_on = True
        self._abort_record.clear()
        # ⚠️ অটোমেটিক কোনো লিসেনিং শুরু হবে না!
        # কেবল ইউজার মাঝের অরব বা চ্যাট মাইকে ক্লিক করলেই শোনা শুরু হবে।
        await self.broadcast_state()
        if not agent.busy and not self.speaking:
            await bus.emit("status", state="idle")
        if not was_on:
            await bus.emit("signal", level="ok", title="mic", text="🎙️ Mic: On — কথা বলতে মাঝে বা চ্যাটের 🎙️ বাটনে ক্লিক করুন")

    async def start_listening(self, force_mic_on: bool = False) -> None:
        """মাঝখানের অরব বা চ্যাট ইন্টারফেসের মাইকে ক্লিক করলে কেবল শোনা শুরু হবে।"""
        self._loop = asyncio.get_running_loop()
        if not self.mic_on:
            if force_mic_on:
                self.mic_on = True
                await self.broadcast_state()
            else:
                await bus.emit("signal", level="warn", title="mic", text="🔇 Mic: Off — কথা বলতে আগে ওপরে Mic On করুন")
                return

        if self.listening:
            # যদি অলরেডি শুনতে থাকে, ক্লিক করলে রেকর্ডিং সম্পন্ন করে প্রসেস করবে
            await self.stop_listening(commit=True)
            return

        if self.speaking:
            await self.stop_speaking()
        if agent.busy or self.transcribing:
            return

        if self._mic_task and not self._mic_task.done():
            self._mic_task.cancel()
            try:
                await self._mic_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        self._mic_task = asyncio.create_task(self._record_one_turn())

    async def stop_listening(self, commit: bool = True) -> None:
        """চলমান রেকর্ডিং বন্ধ করে (commit=True হলে প্রসেস করবে, False হলে বাতিল করবে)।"""
        if not self.listening:
            return
        if commit:
            self._stop_record.set()
        else:
            self._abort_record.set()
            self._stop_record.set()
            if self._mic_task and not self._mic_task.done():
                self._mic_task.cancel()
            self.listening = False
            await bus.emit("voice_level", level=0.0, speech=False)
            await self.broadcast_state()
            if not agent.busy and not self.speaking:
                await bus.emit("status", state="idle")

    async def _record_one_turn(self) -> None:
        """একটি একক টার্ন রেকর্ড করে — কথা শেষ হলে প্রসেস করবে এবং থামবে (অটো-লুপ হবে না)।"""
        try:
            self._stop_record.clear()
            self._abort_record.clear()
            self.listening = True
            await self.broadcast_state()
            await bus.emit("status", state="listening")

            try:
                wav = await asyncio.to_thread(
                    record_utterance,
                    self._stop_record,
                    self._abort_record,
                    self._emit_level_threadsafe,
                    wait_speech_sec=8.0,
                    silence_after_speech_sec=1.45,
                    max_duration_sec=35.0,
                )
            except Exception as e:  # noqa: BLE001
                self.listening = False
                await self.broadcast_state()
                if not agent.busy and not self.speaking:
                    await bus.emit("status", state="idle")
                await bus.emit("signal", level="error", title="mic", text=str(e))
                return

            self.listening = False
            await bus.emit("voice_level", level=0.0, speech=False)

            if not self.mic_on or self._abort_record.is_set():
                if not agent.busy and not self.speaking:
                    await bus.emit("status", state="idle")
                return

            if not wav:
                if not agent.busy and not self.speaking:
                    await bus.emit("status", state="idle")
                return

            await self._process_wav(wav)
        except asyncio.CancelledError:
            pass
        finally:
            self.listening = False
            await bus.emit("voice_level", level=0.0, speech=False)
            await self.broadcast_state()

    async def _process_wav(self, wav: bytes) -> None:
        if not self.mic_on:
            return
        self.transcribing = True
        await self.broadcast_state()
        await bus.emit("status", state="thinking", step="কথা বোঝা হচ্ছে…")
        try:
            text = await transcribe(wav)
        except Exception as e:  # noqa: BLE001
            self.transcribing = False
            await self.broadcast_state()
            await bus.emit("status", state="idle")
            await bus.emit("signal", level="error", title="stt", text=str(e))
            return

        self.transcribing = False
        await self.broadcast_state()

        # যদি ট্রান্সক্রাইব চলাকালীন ইউজার মাইক অফ করে থাকেন, তাহলে এই মেসেজ বাতিল!
        if not self.mic_on or self._abort_record.is_set():
            if not agent.busy:
                await bus.emit("status", state="idle")
            return

        if not text:
            await bus.emit("status", state="idle")
            return

        await bus.emit("signal", level="ok", title="voice", text=text[:90])
        await agent.run(text, session="ui", source="voice")

    async def set_persona(self, persona: str) -> None:
        self.persona = "male" if persona == "male" else "female"
        await self.broadcast_state()
        label = "Synthia · Female" if self.persona == "female" else "Jarvis · Male"
        await bus.emit("signal", level="info", title="voice", text=f"ভয়েস পরিবর্তন: {label}")

    async def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if self.muted:
            await self.stop_speaking()
        await self.broadcast_state()

    async def stop_all(self) -> None:
        await self.set_mic(False)
        await self.stop_speaking()


voice = VoiceManager()
