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
    check_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket() as s:
        return s.connect_ex((check_host, port)) != 0


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
        with urllib.request.urlopen(req, timeout=2.0) as r:
            if r.status == 200:
                body = r.read().decode("utf-8")
                return '"shown":true' in body.replace(" ", "").lower()
    except Exception:  # noqa: BLE001
        pass
    return False


def _kill_stale_port_owner(port: int) -> bool:
    """যদি কোনো অপ্রয়োজনীয়/অচল python প্রসেস পোর্টটি আটকে রেখে থাকে তবে তা কিল করে।"""
    try:
        import os
        import psutil
        current_pid = os.getpid()
        killed = False
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port:
                pid = conn.pid
                if pid and pid != current_pid:
                    try:
                        p = psutil.Process(pid)
                        name = p.name().lower()
                        if "python" in name or "synthia" in name:
                            p.kill()
                            killed = True
                    except Exception:
                        pass
        if killed:
            time.sleep(0.6)
            return True
    except Exception:
        pass
    return False


def _find_free_port(host: str, start_port: int = 8765, max_tries: int = 10) -> int:
    """৮৭৬৫ পোর্ট কোনো কারণে ব্যস্ত থাকলে ডায়নামিকভাবে পরবর্তী ফ্রি পোর্ট খুঁজে নেয়।"""
    for p in range(start_port, start_port + max_tries):
        if _port_free(host, p):
            return p
    return start_port


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
        # ১. আগে চালু থাকা উইন্ডো সামনে আনার চেষ্টা
        if _focus_existing(rt_file):
            return

        # ২. অচল বা হ্যাং হওয়া ব্যাকগ্রাউন্ড প্রসেস পোর্ট দখল করে থাকলে তা বন্ধ করো
        _kill_stale_port_owner(port)

        # ৩. যদি পোর্ট এখনো মুক্ত না হয়, পরবর্তী ফ্রি পোর্ট নাও যেন Synthia সবসময় নিশ্চিত ওপেন হয়
        if not _port_free(host, port):
            port = _find_free_port(host, port + 1)

    ensure_first_run_shortcuts()
    server = _start_server(host, port)
    from .server import ACCESS_TOKEN
    local_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{local_host}:{port}/?token={ACCESS_TOKEN}"
    rt_file.parent.mkdir(parents=True, exist_ok=True)
    rt_file.write_text(
        json.dumps({"host": local_host, "port": port, "token": ACCESS_TOKEN, "url": url}, indent=2),
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
