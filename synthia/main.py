"""Synthia চালু করার মূল ফাইল।

    Synthia.exe                       # পূর্ণাঙ্গ Windows সফটওয়্যার (টার্মিনাল ছাড়া + System Tray)
    python -m synthia.main            # ডেস্কটপ উইন্ডো + System Tray
    python -m synthia.main --browser  # ব্রাউজারে UI খুলবে
    python -m synthia.main --server   # শুধু ব্যাকগ্রাউন্ড সার্ভার
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from .config import ROOT, settings
from .desktop import (
    ICON_PATH,
    ensure_first_run_shortcuts,
    init_clr,
    install_shortcuts,
    set_app_id,
    setup_windowless_logging,
    shell,
)


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def _focus_existing(rt_file) -> bool:
    """Synthia আগে থেকেই চালু থাকলে তার উইন্ডো সামনে নিয়ে আসার চেষ্টা করে।"""
    if not rt_file.exists():
        return False
    try:
        import urllib.parse
        import urllib.request
        info = json.loads(rt_file.read_text(encoding="utf-8"))
        u = f"http://{info['host']}:{info['port']}/api/show?token={urllib.parse.quote(info['token'])}"
        req = urllib.request.Request(u, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _start_server(host: str, port: int) -> uvicorn.Server:
    from .server import app
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", ws_max_size=32 * 1024 * 1024)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="synthia-server").start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    return server


def _hotkey_thread() -> None:
    """Ctrl+Shift+X = Kill switch (যেকোনো জায়গা থেকে সব কাজ বন্ধ)।"""
    from . import server as srv
    user32 = ctypes.windll.user32
    MOD_CONTROL, MOD_SHIFT, VK_X, WM_HOTKEY = 0x2, 0x4, 0x58, 0x0312
    if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT, VK_X):
        print("[synthia] Kill switch hotkey (Ctrl+Shift+X) রেজিস্টার করা যায়নি")
        return
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY and srv.MAIN_LOOP:
            srv.MAIN_LOOP.call_soon_threadsafe(srv.kill_switch)


def main() -> None:
    setup_windowless_logging()
    set_app_id()
    init_clr()

    ap = argparse.ArgumentParser(description="Synthia AI Agent")
    ap.add_argument("--browser", action="store_true", help="open UI in default browser")
    ap.add_argument("--server", action="store_true", help="run server only")
    ap.add_argument("--install-shortcuts", action="store_true", help="create Desktop & Start Menu shortcuts")
    args = ap.parse_args()

    if args.install_shortcuts:
        done = install_shortcuts(desktop=True, start_menu=True)
        print("[synthia] Shortcuts created:", done)
        return

    host = settings.get("server.host", "127.0.0.1")
    port = int(settings.get("server.port", 8765))
    rt_file = ROOT / "synthia_data" / "runtime.json"

    if not _port_free(host, port):
        if _focus_existing(rt_file):
            return
        print(f"[synthia] পোর্ট {port} ব্যস্ত — Synthia হয়তো আগেই চালু আছে।")
        sys.exit(1)

    ensure_first_run_shortcuts()
    server = _start_server(host, port)
    from .server import ACCESS_TOKEN
    url = f"http://{host}:{port}/?token={ACCESS_TOKEN}"
    rt_file.parent.mkdir(parents=True, exist_ok=True)
    rt_file.write_text(
        json.dumps({"host": host, "port": port, "token": ACCESS_TOKEN, "url": url}, indent=2),
        encoding="utf-8",
    )
    threading.Thread(target=_hotkey_thread, daemon=True, name="synthia-hotkey").start()
    print(f"[synthia] ✅ Synthia চালু: {url}")
    print("[synthia] Kill switch: Ctrl+Shift+X")

    try:
        if args.server:
            shell.start_tray()
            while True:
                time.sleep(1)
        elif args.browser:
            shell.start_tray()
            webbrowser.open(url)
            while True:
                time.sleep(1)
        else:
            try:
                import webview
                win = webview.create_window(
                    "SYNTHIA · Command Bridge",
                    url,
                    width=1600,
                    height=900,
                    min_size=(1200, 720),
                    background_color="#05090d",
                )
                shell.attach(win)
                shell.start_tray()
                storage = str(ROOT / "synthia_data" / "webview")
                webview.start(
                    private_mode=False,
                    storage_path=storage,
                    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[synthia] Desktop window সমস্যা ({e}) — ব্রাউজারে খুলছি...")
                shell.start_tray()
                webbrowser.open(url)
                while True:
                    time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        rt_file.unlink(missing_ok=True)
        server.should_exit = True


if __name__ == "__main__":
    main()
