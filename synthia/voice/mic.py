"""Windows Native Microphone Recorder (winmm.dll) — 16kHz 16-bit Mono PCM রেকর্ডার,
অডিও নরমালাইজার এবং কঠোর Abort সাপোর্ট (মাইক অফ করামাত্র হার্ডওয়্যার বন্ধ ও বাফার বাতিল)।"""
from __future__ import annotations

import array
import ctypes
import io
import math
import threading
import time
import wave
from typing import Callable

SAMPLE_RATE = 16000
CHANNELS = 1
BITS = 16
CHUNK_MS = 80
CHUNK_BYTES = int(SAMPLE_RATE * (BITS // 8) * CHANNELS * (CHUNK_MS / 1000))  # 2560 bytes (80ms)
NUM_BUFFERS = 8
WHDR_DONE = 0x00000001
WAVE_MAPPER = ctypes.c_uint(-1)


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", ctypes.c_uint16),
        ("nChannels", ctypes.c_uint16),
        ("nSamplesPerSec", ctypes.c_uint32),
        ("nAvgBytesPerSec", ctypes.c_uint32),
        ("nBlockAlign", ctypes.c_uint16),
        ("wBitsPerSample", ctypes.c_uint16),
        ("cbSize", ctypes.c_uint16),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint32),
        ("dwBytesRecorded", ctypes.c_uint32),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.c_uint32),
        ("dwLoops", ctypes.c_uint32),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


def has_microphone() -> bool:
    try:
        return ctypes.windll.winmm.waveInGetNumDevs() > 0
    except Exception:  # noqa: BLE001
        return False


def _rms_norm(pcm_bytes: bytes) -> float:
    if len(pcm_bytes) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if not samples:
        return 0.0
    acc = sum(s * s for s in samples)
    return min(1.0, (math.sqrt(acc / len(samples)) / 32768.0))


def _soft_limit(val: float) -> int:
    sign = -1 if val < 0 else 1
    av = abs(val)
    if av <= 26000.0:
        return int(val)
    compressed = 26000.0 + 6767.0 * math.tanh((av - 26000.0) / 6767.0)
    return sign * min(32767, int(compressed))


def normalize_pcm(pcm: bytes) -> bytes:
    """মাইক্রোফোনের হালকা বা আস্তে বলা বাংলা/ইংরেজি বাক্যকে পরিষ্কার ভলিউমে নরমালাইজ করে।
    সিঙ্গেল-স্যাম্পল পপ/ক্লিক যেন পুরো বাক্যের ভলিউম কমিয়ে না দেয় সেজন্য 98th-percentile ও soft-limiter ব্যবহার করে।
    """
    if len(pcm) < 4:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return pcm
    mean = int(sum(samples) / len(samples))
    active = sorted(abs(s - mean) for s in samples if abs(s - mean) > 90)
    if len(active) < 80:
        return pcm
    p98 = active[min(len(active) - 1, int(len(active) * 0.98))]
    if p98 < 110:
        return pcm
    gain = min(12.0, max(0.75, 22000.0 / max(p98, 1)))
    if 0.90 <= gain <= 1.15 and abs(mean) < 35:
        return pcm
    out = array.array("h", (_soft_limit((s - mean) * gain) for s in samples))
    return out.tobytes()


def pcm_to_wav(pcm: bytes) -> bytes:
    pad = b"\x00\x00" * int(SAMPLE_RATE * 0.18)  # 180ms lead-in/out যেন প্রথম ও শেষ শব্দ কেটে না যায়
    norm = normalize_pcm(pcm)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BITS // 8)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pad + norm + pad)
    return bio.getvalue()


def record_utterance(
    stop_event: threading.Event,
    abort_event: threading.Event | None = None,
    on_level: Callable[[float, bool], None] | None = None,
    *,
    wait_speech_sec: float = 8.0,
    silence_after_speech_sec: float = 1.45,
    max_duration_sec: float = 35.0,
) -> bytes | None:
    """একটি ভয়েস কমান্ড রেকর্ড করে WAV রিটার্ন করে।
    abort_event সেট হলে সাথে সাথে হার্ডওয়্যার বন্ধ করে None রিটার্ন করে (কিছুই প্রসেস হবে না)।
    """
    if abort_event and abort_event.is_set():
        return None

    winmm = ctypes.windll.winmm
    if winmm.waveInGetNumDevs() <= 0:
        raise RuntimeError("পিসিতে কোনো সচল মাইক্রোফোন পাওয়া যায়নি।")

    wfx = WAVEFORMATEX(1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * 2, 2, BITS, 0)
    hwi = ctypes.c_void_p()
    rc = winmm.waveInOpen(ctypes.byref(hwi), WAVE_MAPPER, ctypes.byref(wfx), 0, 0, 0)
    if rc != 0:
        raise RuntimeError(f"মাইক্রোফোন খোলা যায়নি (error {rc})। উইন্ডোজের Mic Privacy চেক করুন।")

    buffers = [ctypes.create_string_buffer(CHUNK_BYTES) for _ in range(NUM_BUFFERS)]
    headers = [
        WAVEHDR(ctypes.cast(b, ctypes.c_void_p), CHUNK_BYTES, 0, 0, 0, 0, None, 0)
        for b in buffers
    ]

    for hdr in headers:
        winmm.waveInPrepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.waveInAddBuffer(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))

    winmm.waveInStart(hwi)

    preroll: list[bytes] = []
    captured: list[bytes] = []
    speaking = False
    speech_chunks = 0
    voiced_chunks = 0
    silence_chunks = 0
    noise_floor = 0.0055
    idx = 0
    t_start = time.monotonic()

    try:
        while not stop_event.is_set():
            if abort_event and abort_event.is_set():
                return None

            elapsed = time.monotonic() - t_start
            if elapsed > max_duration_sec:
                break
            if not speaking and elapsed > wait_speech_sec:
                break

            hdr = headers[idx]
            if not (hdr.dwFlags & WHDR_DONE):
                time.sleep(0.015)
                continue

            raw = buffers[idx].raw[: hdr.dwBytesRecorded]
            winmm.waveInUnprepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
            hdr.dwFlags = 0
            hdr.dwBytesRecorded = 0
            winmm.waveInPrepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
            winmm.waveInAddBuffer(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
            idx = (idx + 1) % NUM_BUFFERS

            if not raw:
                continue

            rms = _rms_norm(raw)
            if not speaking:
                noise_floor = 0.88 * noise_floor + 0.12 * min(rms, 0.030)
            onset_thr = max(0.0095, min(0.045, noise_floor * 2.35))
            sustain_thr = max(0.0055, onset_thr * 0.56)
            is_voice = rms >= (sustain_thr if speaking else onset_thr)

            if on_level:
                on_level(min(1.0, rms * 13.0), speaking or is_voice)

            if not speaking:
                preroll.append(raw)
                if len(preroll) > 8:  # ~640ms প্রি-রোল যেন বাংলা বাক্যের শুরুর নরম শব্দ কেটে না যায়
                    preroll.pop(0)
                if is_voice:
                    speech_chunks += 1
                    if speech_chunks >= 2:
                        speaking = True
                        voiced_chunks = speech_chunks
                        captured.extend(preroll)
                        preroll.clear()
                        silence_chunks = 0
                else:
                    speech_chunks = 0
            else:
                captured.append(raw)
                if is_voice:
                    voiced_chunks += 1
                    silence_chunks = 0
                else:
                    silence_chunks += 1
                    if silence_chunks * (CHUNK_MS / 1000.0) >= silence_after_speech_sec:
                        break
    finally:
        winmm.waveInReset(hwi)
        for hdr in headers:
            winmm.waveInUnprepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.waveInClose(hwi)

    if abort_event and abort_event.is_set():
        return None
    if not captured or voiced_chunks < 4:
        return None
    # শেষের অতিরিক্ত নীরবতা হালকা ছেঁটে ৩০০ms স্বাভাবিক টেইল রাখি
    if silence_chunks > 4 and len(captured) > silence_chunks:
        captured = captured[: len(captured) - (silence_chunks - 4)]
    return pcm_to_wav(b"".join(captured))
