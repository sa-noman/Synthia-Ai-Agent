"""Synthia - Local AI Agent."""
from __future__ import annotations

import sys

__version__ = "0.1.0"

# Windows কনসোলে বাংলা ও ইমোজি প্রিন্টে যেন UnicodeEncodeError না আসে
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
