"""Web Skill - ওয়েবসাইট খোলা, ইউটিউবে প্লে, ওয়েব সার্চ, ওয়েবপেজ পড়া।

(ধাপ ৩-এ এগুলো Synthia-র নিজস্ব Chrome প্রোফাইলে Playwright দিয়ে চলবে।
 আপাতত ডিফল্ট ব্রাউজারে খোলে।)
"""
from __future__ import annotations

import html
import re
import urllib.parse
import webbrowser

import httpx

from ..core.tools import tool

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


@tool("open_url", "Open a website URL in the browser.", {"url": {"type": "string"}},
      required=["url"], category="web")
def open_url(url: str) -> str:
    if not re.match(r"^[a-z]+://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"OK: opened {url}"


@tool("play_youtube", "Search YouTube and play the best matching video (song, video, tutorial) in the browser.",
      {"query": {"type": "string", "description": "what to play, e.g. 'Arijit Singh latest song'"}},
      required=["query"], category="web")
async def play_youtube(query: str) -> str:
    search = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}) as c:
            r = await c.get(search)
        ids = re.findall(r'"videoId":"([\w-]{11})"', r.text)
        titles = re.findall(r'"title":\{"runs":\[\{"text":"(.*?)"\}', r.text)
    except httpx.HTTPError:
        webbrowser.open(search)
        return f"Offline/blocked — opened YouTube search page for '{query}'."
    if not ids:
        webbrowser.open(search)
        return f"Could not find a direct video; opened search results for '{query}'."
    vid = ids[0]
    webbrowser.open(f"https://www.youtube.com/watch?v={vid}&autoplay=1")
    title = html.unescape(titles[0]) if titles else vid
    return f"OK: playing on YouTube: {title}"


@tool("web_search", "Search the internet and return top results (title, link, snippet). Use for research/questions.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "description": "default 6"}},
      required=["query"], category="web")
async def web_search(query: str, max_results: int = 6) -> str:
    try:
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": UA}, follow_redirects=True) as c:
            r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
    except httpx.HTTPError as e:
        return f"ERROR: no internet / search failed: {e}"
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>.*?class="result__snippet".*?>(.*?)</a>',
        r.text, re.S)
    out = []
    for href, title, snip in blocks[:max_results]:
        m = re.search(r"uddg=([^&]+)", href)
        link = urllib.parse.unquote(m.group(1)) if m else href
        clean = lambda s: html.unescape(re.sub(r"<.*?>", "", s)).strip()  # noqa: E731
        out.append(f"- {clean(title)}\n  {link}\n  {clean(snip)}")
    return "\n".join(out) if out else "No results found."


@tool("read_webpage", "Fetch a web page and return its readable text (for research/summary).",
      {"url": {"type": "string"}, "max_chars": {"type": "integer", "description": "default 6000"}},
      required=["url"], category="web")
async def read_webpage(url: str, max_chars: int = 6000) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}, follow_redirects=True) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        return f"ERROR: could not fetch page: {e}"
    text = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", r.text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:max_chars] + ("...[truncated]" if len(text) > max_chars else "")
