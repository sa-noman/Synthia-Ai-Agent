"""Synthia Agent - চিন্তা → টুল চালানো → ফলাফল দেখা → আবার চিন্তা (ReAct loop)।"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from ..learning import learning
from .events import bus
from .history import task_history
from .llm.providers import LLMError
from .llm.router import router
from .loop_guard import LoopGuard
from .monitoring import errors
from .tools import registry

SYSTEM_PROMPT = """You are **Synthia**, a powerful personal AI agent running locally on the user's Windows PC.
You can control the computer through tools: files, apps, browser, YouTube, system info and more.

# Language
- Reply in the SAME language the user used. If user writes Bangla (বাংলা) or Banglish, reply in natural Bangla.
  If English, reply in English. Keep replies short, warm and clear — like a smart assistant (Jarvis style).
- Address the user respectfully (e.g. "Boss" / "স্যার" is fine occasionally, not every sentence).

# How to work
- If a task needs action, CALL TOOLS. Do not just describe what you would do.
- When calling a tool, use standard tool-calling or respond with:
  Action: <tool_name>
  Action Input: {{"param": "value"}}
- Break multi-step tasks into steps and call tools one by one; check each result before continuing.
- Use folder shortcuts like "desktop", "downloads", "documents", "pictures", "videos", "music", "workspace".
- Save anything you create (scripts, reports, media) inside the "workspace" folder unless the user says otherwise.
- To modify existing files without rewriting everything, use 'edit_file' (replace target text) or 'apply_patch'.
- To run Python calculations, scripts, or data processing, use 'execute_python' or 'evaluate_math'.
- To organize chaotic folders by file type, use 'organize_folder'.
- If a tool returns ERROR, try to fix the problem (different path, search first) before giving up.
- Never invent file names or results. If you are unsure where something is, use search_files.
- When finished, give a brief summary of what you did (and paths of created files).

# External AI Websites & Autonomous Conversations
- You CAN open and interact with any external AI (Gemini, ChatGPT, Claude, DeepSeek, Perplexity, Grok, Copilot, Meta AI, Mistral, Poe) using your tools:
  - Open AI website in browser -> call `open_ai_website(ai_name=...)`.
  - Ask an external AI & bring back its answer -> call `ask_external_ai(ai_name=..., question=...)`.
  - Hold an autonomous multi-round conversation with an external AI -> call `converse_with_ai(ai_name=..., topic_or_first_message=..., rounds=3)`.
  - Read the latest reply from an open AI tab -> call `read_browser_ai_reply(ai_name=...)`.
  - Close Synthia's own browser window -> call `close_synthia_browser()`.
- NEVER claim you lack tools to open or talk to Gemini, ChatGPT, Claude, or other AIs. Always call these tools.

# Safety (STRICT)
- Deleting, overwriting, editing files outside workspace, or running shell commands ALWAYS requires the user's explicit approval.
  The tool itself will ask the user — just call it. NEVER say something was deleted unless the tool confirmed success.
- If the user denies, accept it and do not try another way to do the same thing.
- Never post, send messages, or purchase anything without the user clearly asking for it.

# Context
- Current time: {now}
- OS: {os}  | User home: {home}
- Synthia workspace folder: {workspace}
- Active Brain Model: {active_model} (mode: {brain_mode})
- Installed Local Models: {local_models}
"""


class Agent:
    def __init__(self) -> None:
        self.histories: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._cancel = asyncio.Event()
        self.loop_guard = LoopGuard()
        self.busy = False
        self.active_thread: str = f"chat_{int(time.time())}"
        self.active_mobile_thread: str = f"mob_{int(time.time())}"

    def _system(self, last_user_text: str = "", source: str = "ui") -> dict[str, Any]:
        lang_rule = _lang_directive(last_user_text)
        voice_rule = (
            "\n# Voice Turn\n- User spoke via microphone. Keep your final reply concise (1–3 natural sentences) so it sounds crisp when spoken aloud."
            if source in ("voice", "mobile_voice") else ""
        )
        active_cfg = next((m for m in settings.models if m.get("id") == router.active), None)
        active_str = f"{active_cfg.get('label', active_cfg['id'])} ({active_cfg.get('model')})" if active_cfg else str(router.active or "auto")
        local_str = ", ".join(f"{m.get('label')} [{m.get('model')}]" for m in settings.models if m.get("provider") == "ollama") or "none"
        return {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                now=time.strftime("%Y-%m-%d %H:%M (%A)"),
                os=f"{platform.system()} {platform.release()}",
                home=str(Path.home()),
                workspace=str(settings.path("paths.workspace", "./workspace")),
                active_model=active_str,
                brain_mode=router.mode,
                local_models=local_str,
            ) + f"\n{lang_rule}{voice_rule}" + (f"\n\n{learning.prompt_block()}" if learning.prompt_block() else ""),
        }

    async def _try_model_command(self, text: str) -> tuple[str, str, str] | None:
        """টেক্সট বা ভয়েস কমান্ডের মাধ্যমে তাৎক্ষণিকভাবে মডেল দেখা বা সুইচ করে।"""
        q = (text or "").strip().lower()
        if not q:
            return None

        is_en = not re.search(r"[\u0980-\u09FF]", text or "")
        status_phrases = (
            "কোন মডেল চল", "কোন মডেল চালু", "এখন কোন মডেল", "কোন মডেল ব্যবহার",
            "কী কী লোকাল মডেল", "কি কি লোকাল মডেল", "কোন কোন লোকাল মডেল", "লোকাল মডেল কি কি",
            "which model is running", "what model is running", "current model", "active model",
            "installed local model", "list local model",
        )
        if any(p in q for p in status_phrases):
            st = router.state()
            models = st.get("models", [])
            cur = next((m for m in models if m["id"] == st.get("active")), None)
            locals_ = [m for m in models if m.get("local")]
            cur_name = f"{cur.get('label')} ({cur.get('model')})" if cur else str(st.get("active") or "Unknown")
            mode_txt = "Manual Lock" if st.get("mode") == "manual" else "Auto-Switch"
            local_list = ", ".join(f"{m.get('label')} ({m.get('model')})" for m in locals_) or "None"
            if is_en:
                reply = f"Currently running model: **{cur_name}** in **{mode_txt}** mode.\nInstalled local models: {local_list}."
            else:
                reply = f"এখন চলছে: **{cur_name}** (**{mode_txt}** মোডে)।\nপিসিতে ইনস্টল থাকা লোকাল মডেল: {local_list}।"
            return (reply, cur.get("model", "") if cur else "", cur.get("label", "") if cur else "")

        non_model_words = (
            "ব্রাউজার", "browser", "ওয়েবসাইট", "ওয়েবসাইট", "website",
            "ওয়েব", "ওয়েব", "সাইট", "site", "লিংক", "link", "url",
            "http://", "https://", ".com", ".ai", ".org", "ট্যাব", "tab",
            "সার্চ", "search", "খোঁজ", "খুঁজে", "ইউটিউব", "youtube",
            "ক্রোম", "chrome", "edge",
        )
        if any(w in q for w in non_model_words):
            return None

        want_auto = any(k in q for k in ("অটো মোড", "auto mode", "অটোমেটিক মোড", "স্বয়ংক্রিয় মোড", "অটোতে", "switch to auto", "set mode auto"))
        want_manual = any(k in q for k in ("ম্যানুয়াল মোড", "ম্যানুয়াল মোড", "manual mode", "ম্যানুয়ালে", "ম্যানুয়ালে", "মডেল লক", "lock model", "switch to manual", "set mode manual"))
        action_verbs = (
            "সুইচ", "switch", "পরিবর্তন", "চেঞ্জ", "change", "চালাও", "চালান", "চালু",
            "সিলেক্ট", "select", "ব্যবহার", "ইউজ", "use", "দাও", "দিন", "যাও", "আসো",
            "activate", "লক", "lock", "সেট", "set", "কাজ কর",
        )
        brain_words = ("মডেল", "মডেলে", "মডেলটা", "model", "ব্রেন", "brain", "llm")
        model_aliases = (
            "qwen", "কুয়েন", "কোয়েন", "কোয়েন", "কিউয়েন", "কিউয়েন",
            "gemma", "জেমা", "গেমা", "e4b",
            "gemini", "জেমিনি", "gpt-4o", "gpt 4o", "4o mini",
            "openrouter", "ওপেনরাউটার", "groq", "গ্রক", "cerebras", "সেরেব্রাস",
            "mistral", "মিস্ট্রাল", "nvidia", "nim",
            "লোকাল মডেল", "local model", "অফলাইন মডেল", "offline model",
            "অন্য লোকাল", "আরেকটা লোকাল", "পরের লোকাল", "ভিন্ন লোকাল", "other local", "next local",
        )
        has_action = any(v in q for v in action_verbs)
        has_brain = any(w in q for w in brain_words)
        has_alias = any(a in q for a in model_aliases)

        if not ((has_action and has_brain and has_alias) or (has_action and has_brain) or want_auto or want_manual):
            return None

        target = router.find_model(text)
        if not target and not (want_auto or want_manual):
            return None

        target_mode: str | None = "auto" if want_auto else ("manual" if want_manual else ("manual" if target else None))
        res = await router.switch_by_command(query=text if target else "", mode=target_mode)
        cfg = res.get("model") or {}
        m_label = cfg.get("label", cfg.get("id", "Unknown"))
        m_code = cfg.get("model", cfg.get("id", ""))
        mode_now = res.get("mode", router.mode)
        mode_disp = "Manual Lock" if mode_now == "manual" else "Auto-Switch"
        if is_en:
            reply = f"Switched to **{m_label}** (`{m_code}`) in **{mode_disp}** mode."
        else:
            reply = f"✅ মডেল পরিবর্তন করা হয়েছে: এখন চলছে **{m_label}** (`{m_code}`) — **{mode_disp}** মোডে।"
        await bus.emit("signal", level="ok", title="model_switch", text=f"🔄 {m_label} ({mode_disp})")
        return (reply, m_code, m_label)

    def reset(self, session: str = "ui") -> None:
        self.histories.pop(session, None)
        if session == "ui":
            self.active_thread = f"chat_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        elif session == "mobile":
            self.active_mobile_thread = f"mob_{int(time.time())}_{uuid.uuid4().hex[:4]}"

    def cancel(self) -> None:
        self._cancel.set()

    @staticmethod
    def _trim(history: list[dict[str, Any]], max_msgs: int = 24) -> list[dict[str, Any]]:
        if len(history) <= max_msgs:
            return history
        cut = history[-max_msgs:]
        # tool মেসেজ দিয়ে শুরু হলে সেটা অনাথ — প্রথম user মেসেজ পর্যন্ত বাদ দাও
        while cut and cut[0]["role"] != "user":
            cut.pop(0)
        return cut

    async def run(self, text: str, session: str = "ui", source: str = "ui",
                  images: list[str] | None = None) -> str:
        async with self._lock:
            self.busy = True
            self._cancel.clear()
            self.loop_guard.reset()
            task_id = uuid.uuid4().hex[:8]
            try:
                return await self._run(text, session, source, images, task_id)
            finally:
                self.busy = False
                vm = getattr(sys.modules.get("synthia.voice.manager"), "voice", None)
                if vm and vm.speaking:
                    next_state = "speaking"
                elif vm and vm.listening:
                    next_state = "listening"
                else:
                    next_state = "idle"
                await bus.emit("status", state=next_state)

    async def _run(self, text: str, session: str, source: str,
                   images: list[str] | None, task_id: str) -> str:
        history = self.histories.setdefault(session, [])
        is_mob = session == "mobile" or str(source).startswith("mobile")
        log_session = self.active_mobile_thread if is_mob else (self.active_thread if session == "ui" else session)
        user_msg: dict[str, Any] = {"role": "user", "content": text}
        if images:
            user_msg["images"] = images
        history.append(user_msg)
        learning.log_message(log_session, "user", text)
        n_tools = n_ok = 0
        await bus.emit("chat", role="user", text=text, source=source, session=session)
        await bus.emit("task_start", task_id=task_id, text=text, source=source)
        task_history.start_task(task_id, text, source=source, session=session, model=router.active or "")

        max_steps = int(settings.get("brain.max_steps", 12))
        tools = registry.schemas()
        final = ""
        used_model = ""
        used_model_label = ""

        quick_model_res = await self._try_model_command(text)
        if quick_model_res is not None:
            final, used_model, used_model_label = quick_model_res
            history.append({"role": "assistant", "content": final})
            await bus.emit("chat", role="assistant", text=final, source=source, session=session,
                           model=used_model, model_label=used_model_label)
            await bus.emit("task_end", task_id=task_id)
            task_history.finish_task(task_id, final, status="completed")
            learning.log_message(log_session, "assistant", final)
            return final

        for step in range(1, max_steps + 1):
            if self._cancel.is_set():
                final = "⛔ কাজ বন্ধ করা হয়েছে (Kill switch)।"
                break
            await bus.emit("status", state="thinking", step=step)
            messages = [self._system(text, source)] + self._trim(history)
            try:
                resp = await router.chat(messages, tools, need_vision=bool(images))
                used_model = resp.get("model") or resp.get("model_id") or ""
                used_model_label = resp.get("model_label") or ""
            except LLMError as e:
                errors.record("brain_error", str(e))
                final = f"⚠️ Brain error: {e}"
                active_cfg = next((m for m in settings.models if m.get("id") == router.active), {})
                used_model = active_cfg.get("model", router.active or "")
                used_model_label = active_cfg.get("label", "")
                break

            calls = resp.get("tool_calls") or []
            content = (resp.get("content") or "").strip()
            if not calls:
                if step == 1:
                    from ..skills.ai_bridge import detect_external_ai_intent
                    ext_intent = detect_external_ai_intent(text)
                    if ext_intent:
                        t_name = ext_intent["tool"]
                        t_args = ext_intent["args"]
                        step_id = uuid.uuid4().hex[:6]
                        await bus.emit("status", state="acting", tool=t_name)
                        await bus.emit("tool_start", task_id=task_id, step_id=step_id, tool=t_name, args=t_args)
                        t0 = time.time()
                        result = await registry.call(t_name, t_args)
                        ok = not result.startswith("ERROR") and not result.startswith("DENIED")
                        n_tools += 1
                        n_ok += int(ok)
                        await bus.emit("tool_end", task_id=task_id, step_id=step_id, tool=t_name,
                                       ok=ok, result=result[:600], ms=int((time.time() - t0) * 1000))
                        final = result
                        history.append({"role": "assistant", "content": final})
                        break
                final = content or "✅"
                history.append({"role": "assistant", "content": final})
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content,
            }
            if resp.get("extra_content"):
                assistant_msg["extra_content"] = resp["extra_content"]
            if calls:
                assistant_msg["tool_calls"] = [
                    c.get("raw") or {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c["arguments"], ensure_ascii=False) if isinstance(c["arguments"], dict) else str(c["arguments"]),
                        },
                    }
                    for c in calls
                ]
            history.append(assistant_msg)
            if content:
                await bus.emit("chat", role="assistant", text=content, partial=True, session=session,
                               model=used_model, model_label=used_model_label)

            for c in calls:
                if self._cancel.is_set():
                    break
                step_id = uuid.uuid4().hex[:6]
                await bus.emit("status", state="acting", tool=c["name"])
                await bus.emit("tool_start", task_id=task_id, step_id=step_id,
                               tool=c["name"], args=c["arguments"])
                task_history.log_tool_start(task_id, step_id, c["name"], c["arguments"])

                verdict = self.loop_guard.check_call(c["name"], c["arguments"])
                t0 = time.time()
                if verdict.blocked:
                    await bus.emit("signal", level="warn", title="loop_guard", text=verdict.reason)
                    result = f"ERROR (Loop Guard): {verdict.reason} Do NOT repeat this tool call. Synthesize your final answer or try an alternative tool."
                    ok = False
                else:
                    if verdict.warned:
                        await bus.emit("signal", level="warn", title="loop_guard", text=verdict.reason)
                    result = await registry.call(c["name"], c["arguments"])
                    ok = not result.startswith("ERROR") and not result.startswith("DENIED")

                elapsed_ms = int((time.time() - t0) * 1000)
                n_tools += 1
                n_ok += int(ok)
                await bus.emit("tool_end", task_id=task_id, step_id=step_id, tool=c["name"],
                               ok=ok, result=result[:600], ms=elapsed_ms)
                task_history.log_tool_end(task_id, step_id, c["name"], ok, result, ms=elapsed_ms)
                history.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                "content": result})
        else:
            final = "⚠️ অনেকগুলো ধাপ হয়ে গেছে, কাজটা এখানে থামালাম। আরও চালাতে বলুন।"
            history.append({"role": "assistant", "content": final})

        # images বড় — হিস্টোরি থেকে সরিয়ে ফেলি
        for m in history:
            m.pop("images", None)
        status = "cancelled" if self._cancel.is_set() else ("error" if final.startswith("⚠️") else "completed")
        task_history.finish_task(task_id, final, status=status)
        await bus.emit("chat", role="assistant", text=final, source=source, session=session,
                       model=used_model, model_label=used_model_label)
        await bus.emit("task_end", task_id=task_id)
        learning.log_message(log_session, "assistant", final)
        learning.after_turn(log_session, text, history, n_tools, n_ok)
        return final


BANGLISH_WORDS = {
    "amar", "ami", "tumi", "apni", "koro", "koren", "dekhao", "kholo", "banao",
    "chalao", "bondho", "kemon", "acho", "ache", "ki", "keno", "kothay", "dao", "bolo",
}


def _lang_directive(text: str) -> str:
    if re.search(r"[\u0980-\u09FF]", text or ""):
        return "# STRICT LANGUAGE FOR THIS TURN: User spoke/wrote in বাংলা (Bengali). You MUST reply 100% in natural বাংলা script."
    words = set(re.findall(r"[a-zA-Z]+", (text or "").lower()))
    if len(words & BANGLISH_WORDS) >= 2:
        return "# STRICT LANGUAGE FOR THIS TURN: User wrote in Banglish (Bengali). Reply in natural বাংলা script."
    if words:
        return "# STRICT LANGUAGE FOR THIS TURN: User spoke/wrote in English. You MUST reply in English."
    return ""


agent = Agent()


def user_dirs() -> dict[str, Path]:
    home = Path.home()
    one = Path(os.environ.get("OneDrive", "")) if os.environ.get("OneDrive") else None

    def pick(name: str) -> Path:
        if one and (one / name).exists():
            return one / name
        return home / name

    return {
        "home": home,
        "desktop": pick("Desktop"),
        "documents": pick("Documents"),
        "downloads": home / "Downloads",
        "pictures": pick("Pictures"),
        "videos": home / "Videos",
        "music": home / "Music",
        "workspace": settings.path("paths.workspace", "./workspace"),
    }
