# SYNTHIA Recovery & Development Progress

Last Updated: 2026-11-05 (Resumed & Completed from Conversation `240a468c-6625-433a-92d1-a197bc6fb898`)

## 1. Initial Recovery Audit Summary

- **Python AST Syntax Check:** `25/25` Python files valid (`0` syntax errors).
- **Backup Preserved:** `backups/backup_20261105_0250/` intact.
- **Offline-First Verified:** Local Ollama `0.40.14` (`127.0.0.1:11434`) running `gemma4:e4b` with native `completion`, `vision`, `audio`, `tools`, and `thinking` capabilities. Zero cloud keys required (`.env` not needed for local Brain or STT).
- **Previously Completed Work Preserved:**
  - `synthia/desktop.py` & `synthia/main.py`: Thread-safe `init_clr()` (`pythonnet` / WinForms Tray + shortcuts).
  - `synthia/server.py`: Persistent `synthia_data/.access_token`, `GET /api/bootstrap` localhost token recovery, `_warm_local_model()` VRAM preloader (`num_ctx=8192`, `keep_alive=30m`), `memories` in `state()`, unified `voice_toggle` / `voice_set`.
  - `synthia/core/agent.py`: `_lang_directive()` (Bangla/Banglish -> বাংলা script, English -> English), concise voice replies, and `speaking`/`listening`/`idle` race fix.
  - `synthia/voice/manager.py`: Unified `mic_on` hardware switch (starts `False`), strict hardware/buffer abort on Mic Off, synchronous `self.speaking = True` before TTS task spawn.
  - `synthia/ui/`: Original `v0.1.0` Command Bridge UI restored with draggable splitters and moderately enlarged left/right stage boxes.

---

## 2. Completed Fixes in This Session

### A. Accurate Full-Sentence Bengali & Bilingual Speech-to-Text (`mic.py`, `stt.py`, `manager.py`)
- [x] **Dual-Threshold Hysteresis VAD (`synthia/voice/mic.py`):** Added separate speech onset (`max(0.0095, noise_floor * 2.35)`) and sustain (`max(0.0055, onset * 0.56)`) thresholds so soft Bangla openings, mid-sentence syllables, and quieter sentence-final verbs (`করে দাও`, `খুলে দাও`, `দেখাও`) are never dropped as silence.
- [x] **Complete-Sentence Pause Tolerance & Boundary Padding (`synthia/voice/mic.py`, `synthia/voice/manager.py`):** Increased `silence_after_speech_sec` from `0.85s` to `1.45s` (`max_duration_sec=35.0s`), expanded preroll to `640ms` (`8` chunks), added `180ms` lead-in/lead-out WAV padding in `pcm_to_wav()`, and required `voiced_chunks >= 4` (`~320ms`) to reject stray desk clicks.
- [x] **98th-Percentile + Soft-Limiter Gain Normalization (`synthia/voice/mic.py`):** Replaced single-sample `max()` peak normalization (where a single mic click or `প/ফ/ভ` plosive starved the rest of a quiet Bangla sentence of gain) with DC removal + 98th-percentile active-speech gain (`up to 12x`) + `tanh` soft-knee limiting above `26000`.
- [x] **Eliminated Prompt Hallucination & Enforced Verbatim Full-Sentence Bangla (`synthia/voice/stt.py`):** Removed literal Bangla/English example phrases from `TRANSCRIBE_PROMPT` (which previously caused `gemma4:e4b` to hallucinate `'আমার ডাউনলোড ফোল্ডার খোলো'` on silent audio), added explicit start-to-finish full-sentence transcription rules, added `repeat_penalty=1.12` + `num_predict=512` (keeping `num_ctx=8192` so VRAM never reloads), and added `_collapse_repeats()` in `_clean_transcript()`.

### B. Original v0.1.0 UI Restoration + Enlarged Left/Right Boxes + Resizable Splitters (`style.css`, `core.js`, `app.js`, `index.html`)
- [x] **Restored Crisp `13px` Sizing + 3-Mode Theme Switcher (`synthia/ui/style.css`, `synthia/ui/index.html`, `synthia/ui/app.js`, `synthia/ui/core.js`):** Reverted oversized `calc(100vw / 80)` scaling back to crisp `13px` typography, restored the original dark-teal default palette (`3D Neon`: `--bg: #04080c`, `--teal: #2ef2d0`), and restored the 3-mode topbar theme switcher (`3D Neon` | `Aurora` | `Paper`) persisted in `localStorage` (`synthia.theme`).
- [x] **Natural Bangladeshi Neural Voices Activated (`synthia/voice/tts.py`):** Fixed `edge_tts.communicate.date_to_string()` clock-skew bug (`DRM.get_unix_timestamp()`) so natural Bangladeshi voices **`bn-BD-NabanitaNeural`** (Female · Synthia) and **`bn-BD-PradeepNeural`** (Male) synthesize cleanly at primary priority instead of falling back to robotic Google Translate TTS, while preserving Google TTS & offline Windows SAPI fallbacks.
- [x] **Restored Original 3D Glowing Particle Orb + Listening & Speaking Waves (`synthia/ui/core.js`, `synthia/ui/app.js`):** Restored the original 1100-point golden-spiral glowing sphere, dual tilted elliptical orbit rings, perspective floor grid, and sonar rings from `v0.1.0`, AND added live audio-reactive `drawListeningWaves()` (floating multi-layered sine voice waves while listening) and `drawSpeakingWaves()` (21-bar symmetric glowing speaker equalizer + acoustic sound arcs while speaking), plus `ResizeObserver` / `window.Core.resize` for smooth splitter resizing.
- [x] **Moderately Larger & Cleaner Left (4) & Right (7) Stage Boxes (`synthia/ui/style.css`, `synthia/ui/app.js`):** Enlarged ONLY the left 4 cards (`.cards-left`: `256px`, `.card`: `padding: 15px 16px`, `min-height: 70px`, `36px` icon box, `14px` title) and right 7 Squad cards (`File`, `System`, `Browser`, `Research`, `Voice`, `Studio`, `Remote` — `Smriti` omitted; `.cards-right`: `240px`, `28px` icon box, `13px` title + clear subtitles), with instant initial `renderSquad()` on frame 1 and original curved dashed connector paths.
- [x] **Retained Draggable Splitters & Unified Voice Controls (`synthia/ui/app.js`):** Preserved all drag-to-resize splitters (`colLeft`, `colRight`, `leftTop`, `leftBot`, `centerMid`, `rightComposer`, `stageLeft`, `stageRight`, and `[data-card-split]` handles) persisted under `synthia.layout.v3` (with double-click & `⊞` layout reset), `/api/bootstrap` WebSocket token recovery, and unified `mic_on` voice state without touching backend voice modules.

---

## 3. Verification Tests Executed

- [x] **Python AST Check:** `25/25` `.py` files passed (`0` syntax errors).
- [x] **UI Selector, Splitter & Visual Render Audit:** All DOM IDs and `8` splitter keys verified (`0` missing selectors); rendered live app in headless Microsoft Edge (`WebView2`/Chromium) at both `1920×1080` and `2560×1440` confirming crisp `13px` layout, original glowing particle orb, and moderately enlarged left/right boxes.
- [x] **Audio Normalization Test:** Quiet speech (`1100` amp) with a `29000` mic pop normalized to `13440` (`>10x` boost) without hard clipping.
- [x] **Silent WAV Anti-Hallucination Test:** `1.0s` silent WAV through `transcribe()` returned `''` (fixed prior `'আমার ডাউনলোড ফোল্ডার খোলো'` hallucination).
- [x] **Full-Sentence Local `gemma4:e4b` Bangla & Mixed STT Tests:** Multi-clause pure Bangla and mixed Bangla+English (`Chrome browser`, `YouTube`, `CPU`, `RAM`, `workspace`) sentences transcribed verbatim offline.
- [x] **FastAPI + Bootstrap + WebSocket + Agent E2E Test:** `/`, `/ui/*`, `/api/bootstrap`, `/api/state` (`24` tools, `mic_on=False`), WebSocket handlers (`voice_persona`, `voice_mute`, `set_model`), and live Bangla `agent.run()` reply on local `gemma4:e4b` all passed.

---

## 4. Architectural Decisions & Next Optional Milestones

- **Decisions:**
  - Kept `stt.py` 100% offline-first via local Ollama `gemma4:e4b` (`num_ctx=8192` matching `providers.py` to prevent GPU VRAM reloads), with cloud STT (`Groq`/`Gemini`) strictly opt-in only if API keys exist in `.env`.
  - Preserved strict confirmation gate (`safety.py` + `#confirmWrap`), Recycle Bin-only deletion, System Tray minimize-on-close, and global `Ctrl+Shift+X` kill switch.
- **Pending Future Roadmap Phases (from `synthia_plan.md`, when requested by user):**
  - Phase 3–4: Playwright Chrome profile automation (`Browser` playbooks) & FFmpeg `Studio` media pipeline.
  - Phase 5: Telegram / Discord `Remote` bot bridge.
