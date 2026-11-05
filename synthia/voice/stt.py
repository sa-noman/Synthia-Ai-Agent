"""Speech-to-Text (STT) — বাংলা ও ইংরেজি অটো-রিকগনিশন (কোনো অনুবাদ ছাড়াই যে ভাষায় বলা হয়েছে ঠিক সেই ভাষায় টেক্সট দেয়)।

গুরুত্বপূর্ণ পারফরম্যান্স নোট:
  Ollama-তে `num_ctx` সবসময় `models.yaml`-এর সমান (8192) রাখা হয়েছে, যেন ভয়েস ও চ্যাটের মাঝে
  মডেল কখনোই VRAM থেকে রিলোড না হয় — ফলে ১ সেকেন্ডের মধ্যে ইনস্ট্যান্ট রেসপন্স পাওয়া যায়!
"""
from __future__ import annotations

import base64
import re

import httpx

from ..config import settings

TRANSCRIBE_PROMPT = (
    "Task: Verbatim Speech-to-Text transcription for a Bangladeshi bilingual speaker (Bengali/বাংলা and English).\n"
    "RULES:\n"
    "- Listen to the ENTIRE audio from beginning to end and transcribe EVERY spoken word and clause completely. "
    "Never summarize, shorten, paraphrase, or omit the beginning, middle, or end of the sentence.\n"
    "- Do NOT answer or execute the request; output ONLY what the speaker said.\n"
    "- Write Bengali/Bangla speech strictly in standard বাংলা (Bengali Unicode) script with accurate spelling.\n"
    "- Write English speech in English. If the speaker mixes বাংলা and English terms (such as Synthia, YouTube, Chrome, "
    "Downloads, Desktop, Folder, File, Video, Code), write বাংলা words in বাংলা script and keep English terms natural.\n"
    "- Do NOT include any example text, quotes, markdown, or labels.\n"
    "- If the audio has NO intelligible human speech (only silence, static, clicks, or breathing), output strictly: [EMPTY]"
)

NOISE_MARKERS = {
    "[empty]", "empty", "[silence]", "(silence)", "[noise]", "[music]", "[inaudible]",
    "thank you.", "thanks for watching.", "সাবস্ক্রাইব করুন", "...", ".", "-",
}


def _collapse_repeats(text: str) -> str:
    """নয়েজের কারণে একই শব্দ বা ফ্রেজ বারবার রিপিট হলে তা পরিষ্কার করে।"""
    return re.sub(r"\b(\S+(?:\s+\S+){0,2})(?:\s+\1){4,}\b", r"\1", text)


def _clean_transcript(raw: str) -> str:
    t = (raw or "").strip()
    t = re.sub(r"^```.*?\n|\n```$", "", t, flags=re.S).strip()
    t = t.strip("\"'“”‘’ ")
    for prefix in ("transcription:", "transcript:", "output:", "audio:", "spoken:", "text:"):
        if t.lower().startswith(prefix):
            t = t[len(prefix):].strip().strip("\"'“”‘’ ")
    t = re.sub(r"\s+", " ", t).strip()
    t = _collapse_repeats(t)
    if not t or t.lower() in NOISE_MARKERS or "[empty]" in t.lower():
        return ""
    return t


async def _groq_stt(wav_bytes: bytes, api_key: str) -> str:
    files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
    data = {
        "model": "whisper-large-v3-turbo",
        "temperature": "0",
        "prompt": "বাংলা ও English মিশ্র ভয়েস কমান্ড (Synthia, YouTube, Chrome, Downloads, Desktop)।",
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=4)) as c:
        r = await c.post("https://api.groq.com/openai/v1/audio/transcriptions",
                         data=data, files=files, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Groq STT HTTP {r.status_code}")
    return _clean_transcript(r.json().get("text", ""))


async def _ollama_gemma_stt(wav_bytes: bytes) -> str:
    local_cfg = next((m for m in settings.models if m.get("provider") == "ollama"), None)
    base_url = (local_cfg or {}).get("base_url", "http://127.0.0.1:11434").rstrip("/")
    model = (local_cfg or {}).get("model", "gemma4:e4b")
    # CRITICAL: providers.py-এর সাথে হুবহু একই num_ctx রাখতে হবে যেন Ollama মডেল রিলোড না করে!
    num_ctx = int((local_cfg or {}).get("num_ctx", 8192))
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.0,
            "num_ctx": num_ctx,
            "num_predict": 512,
            "repeat_penalty": 1.12,
        },
        "messages": [
            {"role": "user", "content": TRANSCRIBE_PROMPT, "images": [b64]},
        ],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=4)) as c:
        r = await c.post(f"{base_url}/api/chat", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama audio HTTP {r.status_code}: {r.text[:200]}")
    content = (r.json().get("message") or {}).get("content", "")
    return _clean_transcript(content)


async def _gemini_stt(wav_bytes: bytes, api_key: str) -> str:
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    body = {
        "model": "gemini-2.5-flash",
        "temperature": 0.0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
            ],
        }],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=4)) as c:
        r = await c.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                         json=body, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini STT HTTP {r.status_code}")
    msg = ((r.json().get("choices") or [{}])[0]).get("message") or {}
    return _clean_transcript(msg.get("content", ""))


async def transcribe(wav_bytes: bytes) -> str:
    errors: list[str] = []

    groq_key = settings.env("GROQ_API_KEY")
    if groq_key:
        try:
            return await _groq_stt(wav_bytes, groq_key)
        except Exception as e:  # noqa: BLE001
            errors.append(f"groq: {e}")

    try:
        return await _ollama_gemma_stt(wav_bytes)
    except Exception as e:  # noqa: BLE001
        errors.append(f"ollama: {e}")

    gem_key = settings.env("GEMINI_API_KEY")
    if gem_key:
        try:
            return await _gemini_stt(wav_bytes, gem_key)
        except Exception as e:  # noqa: BLE001
            errors.append(f"gemini: {e}")

    raise RuntimeError("ভয়েস বোঝা যায়নি (" + "; ".join(errors) + ")")
