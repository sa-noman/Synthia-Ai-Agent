"""External AI Bridge & Browser Conversation Skill.

Synthia-কে যেকোনো এক্সটার্নাল AI ওয়েবসাইট (Gemini, ChatGPT, Claude, DeepSeek, Perplexity,
Grok, Copilot, Meta AI, Mistral, Poe) ব্রাউজারে ওপেন করতে, প্রশ্ন পাঠিয়ে উত্তর আনতে,
এবং স্বয়ংক্রিয়ভাবে একাধিক রাউন্ড কনভারসেশন চালিয়ে যেতে সাহায্য করে।
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import httpx
import psutil

from ..config import ROOT
from ..core.events import bus
from ..core.tools import tool

CDP_PORT = 9222
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
_SYNTHIA_BROWSER_PIDS: set[int] = set()

AI_PLATFORMS: dict[str, dict[str, Any]] = {
    "chatgpt": {
        "display": "ChatGPT",
        "url": "https://chatgpt.com",
        "domains": ("chatgpt.com", "chat.openai.com"),
        "aliases": ("chatgpt", "chat gpt", "চ্যাটজিপিটি", "চ্যাটজিপি", "চ্যাট জিপিটি", "চাটজিপিটি", "openai"),
        "input_selectors": ("#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', "textarea"),
        "reply_selectors": (
            '[data-message-author-role="assistant"] .markdown',
            '[data-message-author-role="assistant"]',
            "article .markdown",
        ),
    },
    "gemini": {
        "display": "Google Gemini",
        "url": "https://gemini.google.com",
        "domains": ("gemini.google.com",),
        "aliases": ("gemini", "জেমিনি", "জেমিনাই", "google gemini"),
        "input_selectors": (
            '.ql-editor[contenteditable="true"]',
            'rich-textarea div[contenteditable="true"]',
            'div[contenteditable="true"][role="textbox"]',
            "textarea",
        ),
        "reply_selectors": (
            "message-content .markdown",
            "model-response .markdown",
            "model-response",
        ),
    },
    "claude": {
        "display": "Claude AI",
        "url": "https://claude.ai",
        "domains": ("claude.ai",),
        "aliases": ("claude", "ক্লড", "ক্লউড", "অ্যানথ্রপিক", "anthropic"),
        "input_selectors": ('div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"]', "textarea"),
        "reply_selectors": (
            '[data-is-streaming="false"] .font-claude-response',
            ".font-claude-response",
            '[data-testid="assistant-message"]',
        ),
    },
    "deepseek": {
        "display": "DeepSeek Chat",
        "url": "https://chat.deepseek.com",
        "domains": ("chat.deepseek.com",),
        "aliases": ("deepseek", "ডিপসিক", "ডিপ সিক"),
        "input_selectors": ("textarea#chat-input", "textarea", 'div[contenteditable="true"]'),
        "reply_selectors": (".ds-markdown", '[class*="markdown"]'),
    },
    "perplexity": {
        "display": "Perplexity AI",
        "url": "https://www.perplexity.ai",
        "domains": ("perplexity.ai",),
        "aliases": ("perplexity", "পারপ্লেক্সিটি"),
        "input_selectors": ("textarea", 'div[contenteditable="true"]'),
        "reply_selectors": (".prose", '[class*="markdown"]'),
    },
    "grok": {
        "display": "Grok AI",
        "url": "https://grok.com",
        "domains": ("grok.com", "x.com/i/grok"),
        "aliases": ("grok", "গ্রক", "গ্রোক"),
        "input_selectors": ("textarea", 'div[contenteditable="true"]'),
        "reply_selectors": ('[class*="markdown"]', ".prose"),
    },
    "copilot": {
        "display": "Microsoft Copilot",
        "url": "https://copilot.microsoft.com",
        "domains": ("copilot.microsoft.com",),
        "aliases": ("copilot", "কোপাইলট"),
        "input_selectors": ("textarea#userInput", "textarea", 'div[contenteditable="true"]'),
        "reply_selectors": ('[data-content="ai-message"]', '[class*="markdown"]'),
    },
    "meta": {
        "display": "Meta AI",
        "url": "https://www.meta.ai",
        "domains": ("meta.ai",),
        "aliases": ("meta ai", "মেটা এআই"),
        "input_selectors": ("textarea", 'div[contenteditable="true"]'),
        "reply_selectors": ('[class*="markdown"]', '[dir="auto"]'),
    },
    "mistral": {
        "display": "Mistral Le Chat",
        "url": "https://chat.mistral.ai",
        "domains": ("chat.mistral.ai",),
        "aliases": ("le chat", "mistral", "মিস্ট্রাল"),
        "input_selectors": ("textarea", 'div[contenteditable="true"]'),
        "reply_selectors": ('[class*="markdown"]', ".prose"),
    },
    "poe": {
        "display": "Poe AI",
        "url": "https://poe.com",
        "domains": ("poe.com",),
        "aliases": ("poe", "পো"),
        "input_selectors": ("textarea", 'div[contenteditable="true"]'),
        "reply_selectors": ('[class*="Message_botMessageBubble"]', '[class*="Markdown"]'),
    },
}

# প্রতি এক্সটার্নাল AI-এর জন্য আলাদা কনভারসেশন হিস্ট্রি (multi-turn ধরে রাখার জন্য)
_AI_CONV_HISTORY: dict[str, list[dict[str, str]]] = {}


def resolve_ai_platform(ai_name: str) -> tuple[str, dict[str, Any]]:
    raw = (ai_name or "").strip().lower()
    for key, info in AI_PLATFORMS.items():
        if key == raw or any(alias in raw for alias in info["aliases"]):
            return key, info
    if raw.startswith(("http://", "https://")) or "." in raw:
        url = raw if re.match(r"^[a-z]+://", raw) else f"https://{raw}"
        dom = urllib.parse.urlparse(url).netloc or raw
        return raw, {
            "display": dom,
            "url": url,
            "domains": (dom,),
            "aliases": (raw,),
            "input_selectors": ('div[contenteditable="true"]', "textarea", '[role="textbox"]'),
            "reply_selectors": ('[data-message-author-role="assistant"]', ".markdown", ".prose", "article"),
        }
    return "chatgpt", AI_PLATFORMS["chatgpt"]


def _find_browser_exe() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


async def _cdp_targets() -> list[dict[str, Any]] | None:
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{CDP_BASE}/json")
            if r.status_code == 200:
                data = r.json()
                return [t for t in data if isinstance(t, dict) and t.get("type") == "page"]
    except Exception:
        pass
    return None


async def _ensure_cdp_browser(initial_url: str = "") -> bool:
    if await _cdp_targets() is not None:
        return True
    exe = _find_browser_exe()
    if not exe:
        return False
    profile_dir = ROOT / "synthia_data" / "chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if initial_url:
        cmd.append(initial_url)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.pid:
            _SYNTHIA_BROWSER_PIDS.add(proc.pid)
    except OSError:
        return False
    for _ in range(16):
        await asyncio.sleep(0.35)
        if await _cdp_targets() is not None:
            return True
    return False


async def open_in_synthia_browser(url: str) -> bool:
    """Synthia-র নিজস্ব Chrome/Edge প্রোফাইলে (chrome_profile) নতুন ট্যাবে URL ওপেন করে।"""
    had_cdp = (await _cdp_targets()) is not None
    if not had_cdp:
        return await _ensure_cdp_browser(url)
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            encoded = urllib.parse.quote(url, safe=":/?&=%#")
            r = await c.put(f"{CDP_BASE}/json/new?{encoded}")
            if r.status_code == 200:
                tab = r.json()
                if tab.get("id"):
                    await c.get(f"{CDP_BASE}/json/activate/{tab['id']}")
                return True
    except Exception:
        pass
    return await _ensure_cdp_browser(url)


async def _open_or_focus_tab(url: str, domains: tuple[str, ...]) -> dict[str, Any] | None:
    if not await _ensure_cdp_browser(url):
        return None
    targets = await _cdp_targets() or []
    for t in targets:
        t_url = (t.get("url") or "").lower()
        if any(d in t_url for d in domains):
            try:
                async with httpx.AsyncClient(timeout=2.0) as c:
                    await c.get(f"{CDP_BASE}/json/activate/{t['id']}")
            except Exception:
                pass
            return t
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            encoded = urllib.parse.quote(url, safe=":/?&=%")
            r = await c.put(f"{CDP_BASE}/json/new?{encoded}")
            if r.status_code == 200:
                tab = r.json()
                await asyncio.sleep(1.5)
                return tab
    except Exception:
        pass
    return None


class _CDPClient:
    """হালকা Chrome DevTools Protocol WebSocket ক্লায়েন্ট।"""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._ws: Any = None
        self._seq = 0

    async def __aenter__(self) -> "_CDPClient":
        import websockets
        self._ws = await websockets.connect(self.ws_url, max_size=8 * 1024 * 1024, open_timeout=5)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
        self._seq += 1
        cid = self._seq
        await self._ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=max(0.5, deadline - time.time()))
            msg = json.loads(raw)
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})
        raise TimeoutError(f"CDP timeout for {method}")

    async def eval_js(self, expr: str) -> Any:
        res = await self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        return (res.get("result") or {}).get("value")


async def _cdp_ask_on_page(
    tab: dict[str, Any], info: dict[str, Any], question: str, wait_sec: float = 28.0
) -> dict[str, Any]:
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"ok": False, "reason": "no_ws"}
    input_sels = json.dumps(list(info["input_selectors"]))
    reply_sels = json.dumps(list(info["reply_selectors"]))

    try:
        async with _CDPClient(ws_url) as cdp:
            await cdp.call("Runtime.enable")
            # পেজে ইনপুট বক্স আসা পর্যন্ত সর্বোচ্চ ৬ সেকেন্ড অপেক্ষা
            ready_info = None
            for _ in range(12):
                ready_info = await cdp.eval_js(
                    f"""(() => {{
                        const sels = {input_sels};
                        for (const s of sels) {{
                            const el = document.querySelector(s);
                            if (el && el.offsetParent !== null) {{
                                return {{found: true, selector: s, tag: el.tagName}};
                            }}
                        }}
                        const bodyTxt = (document.body && document.body.innerText || '').slice(0, 600);
                        return {{found: false, url: location.href, snippet: bodyTxt}};
                    }})()"""
                )
                if ready_info and ready_info.get("found"):
                    break
                await asyncio.sleep(0.5)

            if not ready_info or not ready_info.get("found"):
                return {
                    "ok": False,
                    "reason": "login_or_no_input",
                    "snippet": (ready_info or {}).get("snippet", ""),
                }

            # পুরনো রিপ্লাই সংখ্যা ও শেষ টেক্সট মাপা
            before = await cdp.eval_js(
                f"""(() => {{
                    const rSels = {reply_sels};
                    for (const s of rSels) {{
                        const els = document.querySelectorAll(s);
                        if (els.length) {{
                            const last = (els[els.length - 1].innerText || '').trim();
                            return {{count: els.length, last}};
                        }}
                    }}
                    return {{count: 0, last: ''}};
                }})()"""
            ) or {"count": 0, "last": ""}

            # কম্পোজার ফোকাস করে পুরনো টেক্সট পরিষ্কার করা
            sel = json.dumps(ready_info["selector"])
            await cdp.eval_js(
                f"""(() => {{
                    const el = document.querySelector({sel});
                    if (!el) return false;
                    el.focus();
                    if ('value' in el) el.value = '';
                    else el.innerText = '';
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    return true;
                }})()"""
            )
            await cdp.call("Input.insertText", {"text": question})
            await asyncio.sleep(0.25)

            # Enter চেপে অথবা Send বাটনে ক্লিক করে পাঠানো
            clicked = await cdp.eval_js(
                """(() => {
                    const btns = Array.from(document.querySelectorAll('button[type="submit"], button[aria-label*="Send"], button[aria-label*="পাঠান"], button[data-testid="send-button"]'));
                    const b = btns.find(x => !x.disabled && x.offsetParent !== null);
                    if (b) { b.click(); return true; }
                    return false;
                })()"""
            )
            if not clicked:
                await cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
                await cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})

            # উত্তর আসা এবং স্থির হওয়া পর্যন্ত পোলিং
            t_start = time.time()
            last_text = ""
            stable_ticks = 0
            while time.time() - t_start < wait_sec:
                await asyncio.sleep(0.8)
                cur = await cdp.eval_js(
                    f"""(() => {{
                        const rSels = {reply_sels};
                        for (const s of rSels) {{
                            const els = document.querySelectorAll(s);
                            if (els.length) {{
                                const last = (els[els.length - 1].innerText || '').trim();
                                return {{count: els.length, last}};
                            }}
                        }}
                        return {{count: 0, last: ''}};
                    }})()"""
                ) or {"count": 0, "last": ""}
                txt = cur.get("last") or ""
                changed_msg = (cur.get("count", 0) > before.get("count", 0)) or (txt and txt != before.get("last", ""))
                if changed_msg and txt:
                    if txt == last_text:
                        stable_ticks += 1
                        if stable_ticks >= 2:
                            return {"ok": True, "reply": txt}
                    else:
                        last_text = txt
                        stable_ticks = 0
            if last_text:
                return {"ok": True, "reply": last_text}
            return {"ok": False, "reason": "reply_timeout"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"cdp_error: {e}"}


async def _cdp_read_last_reply(tab: dict[str, Any], info: dict[str, Any]) -> str:
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return ""
    reply_sels = json.dumps(list(info["reply_selectors"]))
    try:
        async with _CDPClient(ws_url) as cdp:
            await cdp.call("Runtime.enable")
            res = await cdp.eval_js(
                f"""(() => {{
                    const rSels = {reply_sels};
                    for (const s of rSels) {{
                        const els = document.querySelectorAll(s);
                        if (els.length) {{
                            const last = (els[els.length - 1].innerText || '').trim();
                            if (last) return last;
                        }}
                    }}
                    return (document.body && document.body.innerText || '').trim().slice(-2500);
                }})()"""
            )
            return str(res or "").strip()
    except Exception:
        return ""


async def _bridge_ai_reply(ai_key: str, display: str, message: str) -> str:
    """যখন ব্রাউজারে লগইন না থাকে বা সরাসরি API/মডেল ব্রিজ দরকার হয়, তখন এক্সটার্নাল AI-এর সাথে কনভারসেশন হিস্ট্রি বজায় রেখে উত্তর আনে।"""
    from ..core.llm.router import router

    hist = _AI_CONV_HISTORY.setdefault(ai_key, [])
    sys_msg = {
        "role": "system",
        "content": (
            f"You are acting as {display} in a live assistant-to-assistant conversation with Synthia. "
            "Answer clearly, naturally, and accurately in the same language as the prompt (Bangla if asked in Bangla, English if English). "
            "Keep your reply concise and informative (2-6 sentences unless detail is requested)."
        ),
    }
    messages = [sys_msg] + hist[-10:] + [{"role": "user", "content": message}]
    resp = await router.chat(messages, tools=None, need_vision=False)
    reply = (resp.get("content") or "").strip() or "✅"
    hist.append({"role": "user", "content": message})
    hist.append({"role": "assistant", "content": reply})
    if len(hist) > 20:
        _AI_CONV_HISTORY[ai_key] = hist[-20:]
    return reply


@tool(
    "open_ai_website",
    "Open any external AI website in the browser (ChatGPT, Google Gemini, Claude, DeepSeek, Perplexity, Grok, Copilot, Meta AI, Mistral, Poe).",
    {"ai_name": {"type": "string", "description": "Name of AI platform or URL (e.g. chatgpt, gemini, claude, deepseek, perplexity, grok)"}},
    required=["ai_name"],
    category="web",
)
async def open_ai_website(ai_name: str) -> str:
    _, info = resolve_ai_platform(ai_name)
    url = info["url"]
    display = info["display"]
    tab = await _open_or_focus_tab(url, tuple(info["domains"]))
    if tab:
        return f"OK: ব্রাউজারে {display} ({url}) ওপেন ও ফোকাস করা হয়েছে (Synthia Chrome CDP প্রস্তুত)।"
    webbrowser.open(url)
    return f"OK: ডিফল্ট ব্রাউজারে {display} ({url}) ওপেন করা হয়েছে।"


@tool(
    "read_browser_ai_reply",
    "Read the latest response or visible conversation text from an open external AI browser tab (ChatGPT, Gemini, Claude, etc.).",
    {"ai_name": {"type": "string", "description": "Name of AI platform (e.g. chatgpt, gemini, claude). Optional if an AI tab is already open."}},
    required=[],
    category="web",
)
async def read_browser_ai_reply(ai_name: str = "") -> str:
    targets = await _cdp_targets() or []
    if not targets:
        return "ERROR: Synthia ব্রাউজারে কোনো খোলা AI ট্যাব পাওয়া যায়নি। আগে open_ai_website বা ask_external_ai চালান।"
    ai_key, info = resolve_ai_platform(ai_name or "chatgpt")
    tab = None
    if ai_name.strip():
        tab = next((t for t in targets if any(d in (t.get("url") or "").lower() for d in info["domains"])), None)
    if not tab:
        all_domains = tuple(d for p in AI_PLATFORMS.values() for d in p["domains"])
        tab = next((t for t in targets if any(d in (t.get("url") or "").lower() for d in all_domains)), targets[0])
    txt = await _cdp_read_last_reply(tab, info)
    if not txt:
        return f"ERROR: {tab.get('title') or info['display']} ট্যাব থেকে উত্তর পড়া যায়নি।"
    return f"📖 **{tab.get('title') or info['display']}**-এর সর্বশেষ উত্তর:\n{txt}"


@tool(
    "ask_external_ai",
    "Ask a question to an external AI (ChatGPT, Gemini, Claude, DeepSeek, Perplexity, Grok, etc.), optionally opening its browser website, and return the answer to the user.",
    {
        "ai_name": {"type": "string", "description": "Target AI name: chatgpt, gemini, claude, deepseek, perplexity, grok, copilot"},
        "question": {"type": "string", "description": "Exact question or prompt to ask the external AI"},
        "open_browser": {"type": "boolean", "description": "Whether to open/focus the AI website in browser (default true)"},
    },
    required=["ai_name", "question"],
    category="web",
)
async def ask_external_ai(ai_name: str, question: str, open_browser: bool = True) -> str:
    ai_key, info = resolve_ai_platform(ai_name)
    display = info["display"]
    url = info["url"]

    browser_status = ""
    if open_browser:
        tab = await _open_or_focus_tab(url, tuple(info["domains"]))
        if tab:
            cdp_res = await _cdp_ask_on_page(tab, info, question)
            if cdp_res.get("ok"):
                return f"🤖 **{display} (Live Browser)**-এর উত্তর:\n\n{cdp_res['reply']}"
            browser_status = f"ব্রাউজারে {display} ({url}) ওপেন করা আছে"
        else:
            webbrowser.open(url)
            browser_status = f"ডিফল্ট ব্রাউজারে {display} ({url}) ওপেন করা হয়েছে"

    reply = await _bridge_ai_reply(ai_key, display, question)
    prefix = f"🌐 {browser_status} (লগইন বা পেজ রেডি না থাকায় ডাইরেক্ট AI ব্রিজ দিয়ে উত্তর আনা হয়েছে)\n\n" if browser_status else ""
    return f"{prefix}🤖 **{display}**-এর উত্তর:\n\n{reply}"


@tool(
    "converse_with_ai",
    "Hold an autonomous multi-turn conversation with an external AI (Gemini, ChatGPT, Claude, DeepSeek, etc.) on a topic and bring back the full conversation transcript.",
    {
        "ai_name": {"type": "string", "description": "Target AI: gemini, chatgpt, claude, deepseek, perplexity, grok"},
        "topic_or_first_message": {"type": "string", "description": "Topic or opening message to discuss with the external AI"},
        "rounds": {"type": "integer", "description": "Number of conversation rounds (default 3, max 8)"},
        "open_browser": {"type": "boolean", "description": "Open the target AI website in browser first (default true)"},
    },
    required=["ai_name", "topic_or_first_message"],
    category="web",
)
async def converse_with_ai(
    ai_name: str,
    topic_or_first_message: str,
    rounds: int = 3,
    open_browser: bool = True,
) -> str:
    from ..core.llm.router import router

    n_rounds = max(1, min(int(rounds or 3), 8))
    ai_key, info = resolve_ai_platform(ai_name)
    display = info["display"]
    url = info["url"]

    tab = None
    use_live_dom = False
    if open_browser:
        tab = await _open_or_focus_tab(url, tuple(info["domains"]))
        if not tab:
            webbrowser.open(url)

    is_bn = bool(re.search(r"[\u0980-\u09FF]", topic_or_first_message or ""))
    cur_prompt = topic_or_first_message.strip()
    transcript_lines: list[str] = [
        f"💬 **Synthia ↔ {display}** স্বয়ংক্রিয় কনভারসেশন ({n_rounds} রাউন্ড)\n"
    ]
    convo_mem: list[str] = []

    for r_idx in range(1, n_rounds + 1):
        await bus.emit("signal", level="ok", title="ai_converse", text=f"💬 {display} — রাউন্ড {r_idx}/{n_rounds} চলছে...")
        ai_reply = ""
        if tab and (r_idx == 1 or use_live_dom):
            cdp_res = await _cdp_ask_on_page(tab, info, cur_prompt)
            if cdp_res.get("ok"):
                use_live_dom = True
                ai_reply = cdp_res["reply"]

        if not ai_reply:
            ai_reply = await _bridge_ai_reply(ai_key, display, cur_prompt)

        transcript_lines.append(f"**রাউন্ড {r_idx}**\n- **Synthia:** {cur_prompt}\n- **{display}:** {ai_reply}\n")
        convo_mem.append(f"Synthia: {cur_prompt}\n{display}: {ai_reply}")

        if r_idx < n_rounds:
            lang_hint = "Write in natural Bangla." if is_bn else "Write in English."
            follow_prompt = (
                f"You are Synthia having an autonomous conversation with {display} about: {topic_or_first_message}.\n"
                f"Conversation so far:\n" + "\n\n".join(convo_mem[-4:]) + "\n\n"
                f"Write ONE insightful, natural follow-up question or response to keep the conversation going deeply. "
                f"Output ONLY the message text to send next. {lang_hint}"
            )
            nxt = await router.chat(
                [{"role": "user", "content": follow_prompt}],
                tools=None,
                need_vision=False,
            )
            next_q = (nxt.get("content") or "").strip()
            if next_q:
                cur_prompt = next_q

    mode_note = "Live Browser" if use_live_dom else "Browser Open + Direct AI Bridge"
    transcript_lines.append(f"✅ *{n_rounds} রাউন্ডের কনভারসেশন সম্পন্ন ({mode_note})।*")
    return "\n".join(transcript_lines)


def _extract_clean_question(raw: str) -> str:
    """'চ্যাটজিপিটিকে জিজ্ঞেস করো X' জাতীয় বাক্য থেকে আসল প্রশ্নটি আলাদা করে।"""
    for pat in (
        r"(?:জিজ্ঞেস\s*করো|জিজ্ঞেস\s*কর|জিজ্ঞাসা\s*করো|প্রশ্ন\s*করো|বলে\s*দাও|বলো\s*যে|বলো)\s*[:,\-]?\s*(.+)$",
        r"(?:ask\s+\w+(?:\s+\w+)?(?:\s+to)?|tell\s+\w+(?:\s+\w+)?)\s*[:,\-]?\s*(.+)$",
    ):
        m = re.search(pat, raw, re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return raw


@tool(
    "close_synthia_browser",
    "Close ONLY the browser window/profile opened by Synthia (synthia_data/chrome_profile), leaving the user's personal browser windows untouched.",
    category="web",
)
async def close_synthia_browser() -> str:
    """শুধু Synthia যে chrome_profile ব্রাউজার ওপেন করেছে সেটাই বন্ধ করে, ইউজারের ব্যক্তিগত ব্রাউজার নয়।"""
    closed_cdp = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{CDP_BASE}/json/version")
            if r.status_code == 200:
                ws_url = (r.json() or {}).get("webSocketDebuggerUrl")
                if ws_url:
                    async with _CDPClient(ws_url) as cdp:
                        await cdp.call("Browser.close", timeout=3.0)
                        closed_cdp = True
    except Exception:
        pass

    if closed_cdp:
        await asyncio.sleep(0.4)

    killed = 0
    profile_marker = "chrome_profile"
    port_marker = f"--remote-debugging-port={CDP_PORT}"
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pname = (p.info.get("name") or "").lower()
            if pname not in ("chrome.exe", "msedge.exe", "chrome", "msedge"):
                continue
            cmd_str = " ".join(p.info.get("cmdline") or []).lower()
            pid = int(p.info["pid"])
            is_synthia_proc = (
                profile_marker in cmd_str
                or port_marker in cmd_str
                or pid in _SYNTHIA_BROWSER_PIDS
            )
            if is_synthia_proc:
                p.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    _SYNTHIA_BROWSER_PIDS.clear()

    if closed_cdp or killed:
        return "OK: শুধু Synthia-র ওপেন করা ব্রাউজার (chrome_profile) বন্ধ করা হয়েছে; আপনার ব্যক্তিগত ব্রাউজার অক্ষত আছে।"
    return "OK: Synthia-র কোনো আলাদা ব্রাউজার বর্তমানে চালু নেই (আপনার ব্যক্তিগত ব্রাউজার খোলা থাকলেও তা স্পর্শ করা হয়নি)।"


def detect_external_ai_intent(text: str) -> dict[str, Any] | None:
    """ইউজারের বাংলা/বাংলিশ/ইংরেজি কমান্ড থেকে এক্সটার্নাল AI বা Synthia ব্রাউজার সংক্রান্ত কাজ শনাক্ত করে।"""
    raw = (text or "").strip()
    q = raw.lower()
    if not q:
        return None

    # 0. শুধু Synthia-র প্রোফাইল ব্রাউজার বন্ধ করার কমান্ড
    if any(b in q for b in ("ব্রাউজার", "browser", "ক্রোম", "chrome", "এজ", "edge")) and any(
        c in q for c in ("ক্লোজ", "বন্ধ", "close", "exit", "quit", "কেটে দাও", "কেটে দে")
    ):
        return {"tool": "close_synthia_browser", "args": {}}

    # কোন এক্সটার্নাল AI-এর নাম উল্লেখ আছে খুঁজে বের করি
    matched_key: str | None = None
    for key, info in AI_PLATFORMS.items():
        if any(alias in q for alias in info["aliases"]):
            matched_key = key
            break
    if not matched_key:
        return None

    # মডেল পরিবর্তন কমান্ড হলে এটা এক্সটার্নাল AI ওয়েব কাজ নয় (যেমন: "জেমিনি মডেল ইউজ করো")
    if any(w in q for w in ("মডেল", "model", "ব্রেন", "brain")) and not any(
        w in q for w in ("ওয়েবসাইট", "ওয়েবসাইট", "website", "ব্রাউজার", "browser", "কনভারসেশন", "conversation", "জিজ্ঞেস", "প্রশ্ন", "কথা বল", "চ্যাট")
    ):
        return None

    # 1. নিজে নিজে কনভারসেশন চালানো
    converse_kw = (
        "কনভারসেশন", "conversation", "কথা বল", "কথোপকথন", "আলাপ", "আলোচনা",
        "নিজে নিজে", "চালায়া যা", "চালিয়ে যা", "চালিয়ে যা", "chat with", "talk with", "converse",
    )
    if any(k in q for k in converse_kw):
        m_rounds = re.search(r"([১-৮1-8])\s*(?:রাউন্ড|বার|টা|turn|round)", q)
        bn_map = {"১": 1, "২": 2, "৩": 3, "৪": 4, "৫": 5, "৬": 6, "৭": 7, "৮": 8}
        rounds = 3
        if m_rounds:
            ch = m_rounds.group(1)
            rounds = bn_map.get(ch) or int(ch)
        return {
            "tool": "converse_with_ai",
            "args": {"ai_name": matched_key, "topic_or_first_message": raw, "rounds": rounds, "open_browser": True},
        }

    # 2. আগের উত্তর পড়া
    read_kw = ("কী উত্তর", "কি উত্তর", "কী বল", "কি বল", "উত্তরটা দেখাও", "উত্তর পড়", "উত্তর পড়", "what did", "read reply", "read response")
    if any(k in q for k in read_kw) and not any(k in q for k in ("জিজ্ঞেস", "প্রশ্ন", "ask", "বলো", "বল", "পাঠাও")):
        return {
            "tool": "read_browser_ai_reply",
            "args": {"ai_name": matched_key},
        }

    # 3. প্রশ্ন করা / উত্তর আনা
    ask_kw = ("জিজ্ঞেস", "জিজ্ঞাসা", "প্রশ্ন", "বলো", "বলে দাও", "পাঠাও", "উত্তর", "ask ", "tell ", "query ")
    if any(k in q for k in ask_kw):
        return {
            "tool": "ask_external_ai",
            "args": {"ai_name": matched_key, "question": _extract_clean_question(raw), "open_browser": True},
        }

    # 4. ব্রাউজারে ওয়েবসাইট ওপেন করা / যাওয়া
    open_kw = ("ওপেন", "খোলো", "খুলো", "যাও", "চলে যাও", "নিয়ে যাও", "নিয়ে যাও", "open", "go to", "visit", "launch", "ব্রাউজার", "ওয়েবসাইট", "ওয়েবসাইট", "website")
    if any(k in q for k in open_kw):
        return {
            "tool": "open_ai_website",
            "args": {"ai_name": matched_key},
        }

    return None
