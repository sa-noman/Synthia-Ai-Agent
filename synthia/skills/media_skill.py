"""Synthia Media Squad — এআই ইমেজ জেনারেশন, স্ক্রিনশট ও মাল্টিমোডাল ভিশন টুলস।"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..core.events import bus
from ..core.llm.router import router
from ..core.tools import tool
from .files import resolve


def _get_workspace_dir(sub: str) -> Path:
    ws = resolve("workspace") / sub
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _sanitize_name(raw: str, default: str = "media") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\u0980-\u09FF-]", "_", raw.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:45] if cleaned else default


@tool("generate_image",
      "Generate an AI image from a text description using FLUX, SDXL, or Imagen. Saves directly to workspace/images/.",
      {"prompt": {"type": "string", "description": "Detailed text description of the image to create"},
       "filename": {"type": "string", "description": "Optional filename (e.g. 'futuristic_city.png')"},
       "engine": {"type": "string", "description": "Engine to use: 'flux' (default, free FLUX.1), 'turbo', 'sdxl', or 'imagen'"},
       "width": {"type": "integer", "description": "Width in pixels (default 1024)"},
       "height": {"type": "integer", "description": "Height in pixels (default 1024)"}},
      required=["prompt"],
      category="media")
async def generate_image(prompt: str, filename: str = "", engine: str = "auto",
                         width: int = 1024, height: int = 1024) -> str:
    """এআই দিয়ে নতুন ছবি জেনারেট করে workspace/images ফোল্ডারে সেভ করে।"""
    if not prompt or not prompt.strip():
        return "ERROR: প্রম্পট খালি রাখা যাবে না। কী ধরণের ছবি বানাতে চান তা লিখুন।"

    p_clean = prompt.strip()
    target_dir = _get_workspace_dir("images")

    if not filename:
        slug = _sanitize_name(p_clean[:30], "synthia_art")
        fname = f"{slug}_{int(time.time())}.png"
    else:
        fname = filename if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) else f"{filename}.png"

    dest = target_dir / fname
    eng = (engine or "auto").lower().strip()

    # ১. Google Imagen 3 (যদি engine='imagen' থাকে এবং GEMINI_API_KEY থাকে)
    gemini_key = settings.env("GEMINI_API_KEY")
    if eng == "imagen" and gemini_key:
        try:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={gemini_key}"
            payload = {
                "instances": [{"prompt": p_clean}],
                "parameters": {"sampleCount": 1, "aspectRatio": "1:1", "outputMimeType": "image/png"},
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(api_url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    preds = data.get("predictions", [])
                    if preds and "bytesBase64Encoded" in preds[0]:
                        b64_bytes = base64.b64decode(preds[0]["bytesBase64Encoded"])
                        dest.write_bytes(b64_bytes)
                        rel = os.path.relpath(dest, Path.cwd()).replace("\\", "/")
                        await bus.emit("signal", level="ok", title="media", text=f"🎨 Imagen ছবি তৈরি: {fname}")
                        return (
                            f"✅ এআই ছবি সফলভাবে তৈরি করা হয়েছে (Google Imagen 3)!\n"
                            f"📁 পাথ: {dest}\n"
                            f"🖼️ প্রিভিউ: ![{p_clean}]({rel})"
                        )
        except Exception:
            pass  # Fallback to Pollinations FLUX

    # ২. Pollinations FLUX / Turbo / SDXL (ফ্রি, অত্যন্ত দ্রুত ও উচ্চমানের)
    model_name = "turbo" if eng == "turbo" else ("sdxl" if eng == "sdxl" else "flux")
    w = max(256, min(width, 1536))
    h = max(256, min(height, 1536))
    seed = random.randint(1, 9999999)
    encoded = urllib.parse.quote(p_clean)
    poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&model={model_name}&nologo=true&seed={seed}"

    try:
        async with httpx.AsyncClient(timeout=75.0) as client:
            resp = await client.get(poll_url, follow_redirects=True)
            if resp.status_code != 200 or len(resp.content) < 500:
                return f"ERROR: ইমেজ জেনারেশন সার্ভার ত্রুটি দিয়েছে (HTTP {resp.status_code})"

            dest.write_bytes(resp.content)
            rel = os.path.relpath(dest, Path.cwd()).replace("\\", "/")
            await bus.emit("signal", level="ok", title="media", text=f"🎨 এআই ছবি তৈরি: {fname}")
            return (
                f"✅ এআই ছবি সফলভাবে তৈরি করা হয়েছে ({model_name.upper()})!\n"
                f"📁 সংরক্ষিত পাথ: `{dest}`\n"
                f"🖼️ ফাইল: `{fname}` ({len(resp.content) // 1024} KB)\n"
                f"![{p_clean}]({rel})"
            )
    except Exception as e:
        return f"ERROR: ইমেজ জেনারেশন ব্যর্থ হয়েছে: {e}"


@tool("capture_screen",
      "Capture the primary desktop screen and optionally analyze it with multimodal AI vision.",
      {"filename": {"type": "string", "description": "Optional output filename (saved in workspace/screenshots)"},
       "analyze": {"type": "boolean", "description": "If true, analyzes what is on screen using multimodal AI"},
       "prompt": {"type": "string", "description": "Specific question or analysis prompt for the screenshot"}},
      category="media")
async def capture_screen(filename: str = "", analyze: bool = False, prompt: str = "") -> str:
    """বর্তমান ডেস্কটপ স্ক্রিনের স্ক্রিনশট নেয় এবং প্রয়োজনে এআই দিয়ে বিশ্লেষণ করে।"""
    target_dir = _get_workspace_dir("screenshots")
    fname = filename if filename else f"screen_{int(time.time())}.png"
    if not fname.lower().endswith(".png"):
        fname += ".png"
    dest = target_dir / fname

    captured = False
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(dest, format="PNG")
        captured = True
    except Exception:
        # Fallback via PowerShell
        import subprocess
        ps = f'''
        Add-Type -AssemblyName System.Windows.Forms,System.Drawing
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
        $bmp.Save('{dest}', [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose()
        $bmp.Dispose()
        '''
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        captured = dest.exists() and dest.stat().st_size > 1000

    if not captured or not dest.exists():
        return "ERROR: স্ক্রিনশট নেওয়া সম্ভব হয়নি (ডেস্কটপ হ্যান্ডেল অ্যাক্সেস ব্যর্থ)।"

    rel = os.path.relpath(dest, Path.cwd()).replace("\\", "/")
    await bus.emit("signal", level="ok", title="media", text=f"📸 স্ক্রিনশট সেভ হয়েছে: {fname}")

    if analyze or (prompt and prompt.strip()):
        q = prompt.strip() if prompt else "আমার বর্তমান স্ক্রিনের অবস্থা ও বিষয়বস্তু বিস্তারিত বিশ্লেষণ করো।"
        analysis = await analyze_image(str(dest), q)
        return (
            f"📸 **স্ক্রিনশট সফলভাবে নেওয়া হয়েছে!**\n"
            f"📁 ফাইল: `{dest}`\n\n"
            f"🔍 **স্ক্রিন বিশ্লেষণ:**\n{analysis}"
        )

    return f"📸 স্ক্রিনশট সফলভাবে নেওয়া হয়েছে এবং সেভ করা হয়েছে!\n📁 পাথ: `{dest}`\n🖼️ প্রিভিউ: ![{fname}]({rel})"


@tool("analyze_image",
      "Analyze a local image or screenshot using multimodal AI vision (explain diagrams, read text, debug errors).",
      {"path": {"type": "string", "description": "Path or shortcut to the image (e.g. 'workspace/images/pic.png', 'downloads/error.png')"},
       "prompt": {"type": "string", "description": "What to look for, questions to answer, or instructions"}},
      required=["path"],
      category="media")
async def analyze_image(path: str, prompt: str = "Describe this image in detail and extract key information") -> str:
    """যেকোনো লোকাল ছবি বা ডায়াগ্রাম মাল্টিমোডাল এআই ভিশন দিয়ে বিশ্লেষণ করে।"""
    target = resolve(path)
    if not target.exists() or not target.is_file():
        return f"ERROR: ফাইল পাওয়া যায়নি: {path}"

    try:
        from PIL import Image
        with Image.open(target) as img:
            # Resize if unnecessarily gigantic to optimize speed & token usage
            max_side = 2048
            if max(img.size) > max_side:
                ratio = max_side / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            fmt = "JPEG" if img.format in ("JPEG", "JPG") else "PNG"
            img.convert("RGB").save(buf, format=fmt)
            b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        return f"ERROR: ছবি লোড করা যায়নি ({e})"

    messages = [
        {
            "role": "user",
            "content": prompt or "Describe what you see in this image in detail.",
            "images": [b64_str],
        }
    ]

    try:
        resp = await router.chat(messages, tools=None, need_vision=True)
        content = resp.get("content", "").strip()
        model_name = resp.get("model", "")
        return f"{content}\n\n*(বিশ্লেষণ করেছে: {model_name})*" if model_name else content
    except Exception as e:
        return f"ERROR: এআই ভিশন মডেল রেসপন্স করতে পারেনি: {e}"


@tool("media_info",
      "Get metadata and details of an image, audio or video file (resolution, format, size).",
      {"path": {"type": "string", "description": "Path to the media file"}},
      required=["path"],
      category="media")
def media_info(path: str) -> str:
    """মিডিয়া ফাইলের ফরম্যাট, সাইজ এবং রেজুলেশন দেখায়।"""
    target = resolve(path)
    if not target.exists() or not target.is_file():
        return f"ERROR: ফাইল পাওয়া যায়নি: {path}"

    size_bytes = target.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    out = [
        f"📄 ফাইল: {target.name}",
        f"📁 অবস্থান: {target}",
        f"💾 সাইজ: {size_mb:.2f} MB ({size_bytes:,} bytes)",
        f"🕒 মডিফাইড: {time.ctime(target.stat().st_mtime)}",
    ]

    ext = target.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        try:
            from PIL import Image
            with Image.open(target) as img:
                out.append(f"🖼️ ফরম্যাট: {img.format}")
                out.append(f"📐 রেজুলেশন: {img.width} x {img.height} পিক্সেল")
                out.append(f"🎨 কালার মোড: {img.mode}")
        except Exception:
            pass

    return "\n".join(out)
