"""Text-to-Speech (TTS) — বাংলা ও ইংরেজিতে ন্যাচারাল ভয়েস (Female: Synthia / Male)।

৩-স্তরের ফলব্যাক (যেন কখনো ভয়েস বন্ধ না হয়):
  1. Microsoft Edge Neural TTS (Nabanita ♀ / Pradeep ♂ বাংলা, Aria ♀ / Guy ♂ ইংরেজি)
  2. Google Translate TTS MP3 (কোনো টোকেন ছাড়াই অনলাইন বাংলা ও ইংরেজি ভয়েস)
  3. অফলাইন মোড: Browser speechSynthesis / Windows SAPI (Zira ♀ / David ♂)
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
import subprocess
import sys
import time
import urllib.parse
import uuid

import httpx

VOICES = {
    ("bn", "female"): "bn-BD-NabanitaNeural",
    ("bn", "male"): "bn-BD-PradeepNeural",
    ("en", "female"): "en-US-AriaNeural",
    ("en", "male"): "en-US-GuyNeural",
}

_edge_install_attempted = False


def has_bangla(text: str) -> bool:
    return bool(re.search(r"[\u0980-\u09FF]", text))


def clean_for_speech(text: str, max_chars: int = 420) -> str:
    """কোড ব্লক, লিংক, মার্কডাউন ও লম্বা পাথ বাদ দিয়ে শুনতে স্বাভাবিক বাক্য তৈরি করে।"""
    s = re.sub(r"```[\s\S]*?```", " কোড চ্যাটে দেওয়া হয়েছে। ", text or "")
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"https?://\S+", " লিংক ", s)
    s = re.sub(r"[A-Za-z]:\\[^\s\n]+", " ফাইল ", s)
    s = re.sub(r"[`*_#~>|]", " ", s)
    # ইমোজি ও অতিরিক্ত চিহ্ন হালকা করি
    s = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_chars:
        cut = s[:max_chars]
        last_stop = max(cut.rfind("।"), cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        s = cut[: last_stop + 1] if last_stop > 80 else cut + "..."
    return s


def _ensure_edge_tts_bg() -> None:
    """অনলাইনে থাকলে ব্যাকগ্রাউন্ডে একবার ছোট্ট edge-tts প্যাকেজটি সেটআপ করে নেয়।"""
    global _edge_install_attempted
    if _edge_install_attempted:
        return
    _edge_install_attempted = True
    try:
        import edge_tts  # noqa: F401
        return
    except ImportError:
        pass

    def _install() -> None:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "edge-tts>=7.0"],
                timeout=45,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:  # noqa: BLE001
            pass

    import threading
    threading.Thread(target=_install, daemon=True, name="synthia-edgetts-init").start()


async def _edge_library_tts(text: str, voice: str) -> bytes:
    import edge_tts  # type: ignore[import-not-found]
    import edge_tts.communicate as ec  # type: ignore[import-not-found]
    from edge_tts.drm import DRM  # type: ignore[import-not-found]

    # পিসির ঘড়িতে সময়ের পার্থক্য (clock skew) থাকলেও যেন X-Timestamp সঠিক UTC পাঠায়
    if not getattr(ec, "_synthia_skew_patched", False):
        ec.date_to_string = lambda: time.strftime(
            "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
            time.gmtime(DRM.get_unix_timestamp()),
        )
        ec._synthia_skew_patched = True

    comm = edge_tts.Communicate(text, voice, rate="+3%")
    chunks: list[bytes] = []
    async for item in comm.stream():
        if item.get("type") == "audio" and item.get("data"):
            chunks.append(item["data"])
    if not chunks:
        raise RuntimeError("empty audio from edge_tts")
    return b"".join(chunks)


async def _edge_ws_tts(text: str, voice: str) -> bytes:
    """edge_tts লাইব্রেরি না থাকলেও সরাসরি websockets দিয়ে Edge Neural TTS কল করে।"""
    import websockets

    token = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
    ver = "143.0.3650.75"
    ticks = int(time.time()) + 11644473600
    ticks -= ticks % 300
    sec_gec = hashlib.sha256(f"{ticks * 10_000_000}{token}".encode("ascii")).hexdigest().upper()
    conn_id = uuid.uuid4().hex
    url = (
        "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
        f"?TrustedClientToken={token}&ConnectionId={conn_id}"
        f"&Sec-MS-GEC={sec_gec}&Sec-MS-GEC-Version=1-{ver}"
    )
    headers = {
        "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      f"(KHTML, like Gecko) Chrome/{ver} Safari/537.36 Edg/{ver}",
    }
    lang = "bn-BD" if voice.startswith("bn-") else "en-US"
    req_id = uuid.uuid4().hex
    cfg_msg = (
        f"X-Timestamp:{time.strftime('%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)')}\r\n"
        "Content-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false",'
        '"wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}'
    )
    ssml = (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{lang}'>"
        f"<voice name='{voice}'><prosody pitch='+0Hz' rate='+4%'>{html.escape(text)}</prosody></voice></speak>"
    )
    ssml_msg = (
        f"X-RequestId:{req_id}\r\nContent-Type:application/ssml+xml\r\n"
        f"X-Timestamp:{time.strftime('%a %b %d %Y %H:%M:%S GMT+0000')}Z\r\nPath:ssml\r\n\r\n{ssml}"
    )

    audio = bytearray()
    async with websockets.connect(url, additional_headers=headers, open_timeout=6, close_timeout=2) as ws:
        await ws.send(cfg_msg)
        await ws.send(ssml_msg)
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=12)
            if isinstance(msg, bytes):
                if len(msg) > 2:
                    hdr_len = int.from_bytes(msg[:2], "big")
                    audio.extend(msg[2 + hdr_len:])
            elif isinstance(msg, str) and "Path:turn.end" in msg:
                break
    if not audio:
        raise RuntimeError("empty audio from Edge WS")
    return bytes(audio)


def _split_chunks(text: str, limit: int = 175) -> list[str]:
    parts = re.split(r"(?<=[।.!?])\s+", text)
    out: list[str] = []
    cur = ""
    for p in parts:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + " " + p).strip()
        else:
            if cur:
                out.append(cur)
            while len(p) > limit:
                out.append(p[:limit])
                p = p[limit:]
            cur = p
    if cur:
        out.append(cur)
    return out


async def _google_tts(text: str, lang: str) -> bytes:
    """কোনো API key বা টোকেন ছাড়াই অনলাইন বাংলা/ইংরেজি MP3 ভয়েস।"""
    tl = "bn" if lang == "bn" else "en"
    audio = bytearray()
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=4), headers=headers) as c:
        for chunk in _split_chunks(text):
            q = urllib.parse.quote(chunk)
            url = f"https://translate.googleapis.com/translate_tts?ie=UTF-8&client=tw-ob&tl={tl}&q={q}"
            r = await c.get(url)
            if r.status_code != 200 or not r.content:
                raise RuntimeError(f"Google TTS HTTP {r.status_code}")
            audio.extend(r.content)
    return bytes(audio)


def speak_sapi_blocking(text: str, persona: str = "female") -> None:
    """সম্পূর্ণ অফলাইন ব্যাকআপ: Windows বিল্ট-ইন SAPI (Zira Female / David Male)।"""
    try:
        import clr  # noqa: F401
        from System import Activator, Type
        from System.Reflection import BindingFlags

        t = Type.GetTypeFromProgID("SAPI.SpVoice")
        v = Activator.CreateInstance(t)
        vt = v.GetType()
        voices = vt.InvokeMember("GetVoices", BindingFlags.InvokeMethod, None, v, None)
        cnt = voices.GetType().InvokeMember("Count", BindingFlags.GetProperty, None, voices, None)
        want = "zira" if persona == "female" else "david"
        for i in range(int(cnt)):
            item = voices.GetType().InvokeMember("Item", BindingFlags.InvokeMethod, None, voices, [i])
            desc = str(item.GetType().InvokeMember("GetDescription", BindingFlags.InvokeMethod, None, item, None))
            if want in desc.lower():
                vt.InvokeMember("Voice", BindingFlags.SetProperty, None, v, [item])
                break
        vt.InvokeMember("Speak", BindingFlags.InvokeMethod, None, v, [text, 0])
    except Exception:  # noqa: BLE001
        pass


async def synthesize(text: str, persona: str = "female") -> dict:
    """ভয়েস অডিও তৈরি করে। রিটার্ন:
       {"mode": "mp3", "audio_b64": str, "rate": float} অথবা
       {"mode": "offline", "text": str, "lang": str, "persona": str}
    """
    import base64

    clean = clean_for_speech(text)
    if not clean:
        return {"mode": "none"}

    persona = "male" if persona == "male" else "female"
    lang = "bn" if has_bangla(clean) else "en"
    voice = VOICES[(lang, persona)]
    _ensure_edge_tts_bg()

    # ১. edge_tts লাইব্রেরি (যদি ইনস্টল থাকে)
    try:
        mp3 = await _edge_library_tts(clean, voice)
        return {"mode": "mp3", "audio_b64": base64.b64encode(mp3).decode("ascii"), "rate": 1.0}
    except Exception:  # noqa: BLE001
        pass

    # ২. বিল্ট-ইন Edge Neural WebSocket
    try:
        mp3 = await _edge_ws_tts(clean, voice)
        return {"mode": "mp3", "audio_b64": base64.b64encode(mp3).decode("ascii"), "rate": 1.0}
    except Exception:  # noqa: BLE001
        pass

    # ৩. Google Translate TTS MP3 ফলব্যাক
    try:
        mp3 = await _google_tts(clean, lang)
        rate = 0.92 if persona == "male" else 1.02
        return {"mode": "mp3", "audio_b64": base64.b64encode(mp3).decode("ascii"), "rate": rate}
    except Exception:  # noqa: BLE001
        pass

    # ৪. ১০০% অফলাইন ফলব্যাক
    return {
        "mode": "offline",
        "text": clean,
        "lang": "bn-BD" if lang == "bn" else "en-US",
        "persona": persona,
    }
