"""Synthia Desktop Shell — নেটিভ Windows সফটওয়্যার অভিজ্ঞতা:
  * টাস্কবার আইকন ও AppUserModelID (যেন টাস্কবারে পিন করা যায়)
  * System Tray আইকন (ঘড়ির পাশে) + Minimize-to-Tray
  * Desktop, Start Menu ও Windows Startup শর্টকাট তৈরি
  * Single-instance: Synthia চালু থাকা অবস্থায় আবার ক্লিক করলে উইন্ডো সামনে আসে
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Any

from .config import ROOT

APP_ID = "Synthia.CommandBridge.App"
ICON_PATH = ROOT / "synthia" / "assets" / "synthia.ico"
EXE_PATH = ROOT / "Synthia.exe"
_CLR_LOCK = threading.Lock()
_CLR_READY = False


def init_clr() -> None:
    """মেইন থ্রেডে একবারই pythonnet/CLR লোড করে নেয় যেন tray ও pywebview-র মাঝে রেস না হয়।"""
    global _CLR_READY
    with _CLR_LOCK:
        if _CLR_READY:
            return
        try:
            import pythonnet
            pythonnet.load("netfx")
        except Exception:  # noqa: BLE001
            pass
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            _CLR_READY = True
        except Exception:  # noqa: BLE001
            pass


def setup_windowless_logging() -> None:
    """pythonw.exe দিয়ে চললে stdout/stderr None থাকে — লগ ফাইলে রিডাইরেক্ট করি।"""
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        log_file = (log_dir / "synthia.log").open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file


def set_app_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass


def _shortcut_paths() -> dict[str, Path]:
    from .core.agent import user_dirs
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return {
        "desktop": user_dirs()["desktop"] / "Synthia.lnk",
        "start_menu": programs / "Synthia.lnk",
        "startup": programs / "Startup" / "Synthia.lnk",
    }


def _write_lnk(lnk_path: Path, target: Path, workdir: Path, icon: Path, desc: str) -> None:
    init_clr()
    from System import Activator, Type
    from System.Reflection import BindingFlags

    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    t = Type.GetTypeFromProgID("WScript.Shell")
    sh = Activator.CreateInstance(t)
    sc = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, None, sh, [str(lnk_path)])
    st = sc.GetType()
    st.InvokeMember("TargetPath", BindingFlags.SetProperty, None, sc, [str(target)])
    st.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, None, sc, [str(workdir)])
    st.InvokeMember("IconLocation", BindingFlags.SetProperty, None, sc, [f"{icon},0"])
    st.InvokeMember("Description", BindingFlags.SetProperty, None, sc, [desc])
    st.InvokeMember("Save", BindingFlags.InvokeMethod, None, sc, None)


def install_shortcuts(desktop: bool = True, start_menu: bool = True) -> list[str]:
    """Desktop ও Windows Start Menu-তে Synthia অ্যাপের আইকন তৈরি করে।"""
    target = EXE_PATH if EXE_PATH.exists() else (ROOT / "run_synthia.bat")
    paths = _shortcut_paths()
    created: list[str] = []
    for key, enabled in (("desktop", desktop), ("start_menu", start_menu)):
        if not enabled:
            continue
        try:
            _write_lnk(paths[key], target, ROOT, ICON_PATH, "Synthia · Personal Local AI Agent")
            created.append(str(paths[key]))
        except Exception as e:  # noqa: BLE001
            print(f"[desktop] shortcut ({key}) তৈরি করা যায়নি: {e}")
    return created


def is_startup_enabled() -> bool:
    return _shortcut_paths()["startup"].exists()


def set_startup(enabled: bool) -> bool:
    p = _shortcut_paths()["startup"]
    try:
        if enabled:
            target = EXE_PATH if EXE_PATH.exists() else (ROOT / "run_synthia.bat")
            _write_lnk(p, target, ROOT, ICON_PATH, "Synthia · Auto-start on login")
        else:
            p.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        print(f"[desktop] startup পরিবর্তন ব্যর্থ: {e}")
    return is_startup_enabled()


def ensure_first_run_shortcuts() -> None:
    marker = ROOT / "synthia_data" / ".app_registered"
    if marker.exists():
        return
    created = install_shortcuts(desktop=True, start_menu=True)
    if created:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("\n".join(created), encoding="utf-8")


class DesktopShell:
    def __init__(self) -> None:
        self.window: Any = None
        self.quitting = False
        self._tray_hint_shown = False
        self._notify_icon: Any = None

    def attach(self, window: Any) -> None:
        self.window = window
        window.events.closing += self._on_closing

    def _on_closing(self) -> bool | None:
        """উইন্ডোর X চাপলে পুরো বন্ধ না হয়ে System Tray-তে মিনিমাইজ হবে।"""
        if self.quitting:
            return None
        threading.Thread(target=self._hide_to_tray, daemon=True).start()
        return False  # pywebview: False মানে close বাতিল করো

    def _hide_to_tray(self) -> None:
        if self.window:
            try:
                self.window.hide()
            except Exception:  # noqa: BLE001
                pass
        if not self._tray_hint_shown and self._notify_icon is not None:
            self._tray_hint_shown = True
            try:
                import System.Windows.Forms as WF
                self._notify_icon.ShowBalloonTip(
                    3000,
                    "Synthia ব্যাকগ্রাউন্ডে সচল আছে 💠",
                    "আবার খুলতে ঘড়ির পাশের Synthia আইকনে ডাবল-ক্লিক করুন। পুরোপুরি বন্ধ করতে Right-Click → Exit দিন।",
                    WF.ToolTipIcon.Info,
                )
            except Exception:  # noqa: BLE001
                pass

    def show_window(self) -> None:
        if not self.window:
            return
        try:
            self.window.show()
            self.window.restore()
        except Exception:  # noqa: BLE001
            pass

    def quit_app(self) -> None:
        self.quitting = True
        if self._notify_icon is not None:
            try:
                self._notify_icon.Visible = False
                self._notify_icon.Dispose()
            except Exception:  # noqa: BLE001
                pass
        if self.window:
            try:
                self.window.destroy()
            except Exception:  # noqa: BLE001
                os._exit(0)
        else:
            os._exit(0)

    def start_tray(self) -> None:
        t = threading.Thread(target=self._tray_loop, daemon=True, name="synthia-tray")
        t.start()

    def _tray_loop(self) -> None:
        try:
            init_clr()
            import System.Drawing as SD
            import System.Threading as ST
            import System.Windows.Forms as WF

            ST.Thread.CurrentThread.SetApartmentState(ST.ApartmentState.STA)

            ni = WF.NotifyIcon()
            if ICON_PATH.exists():
                ni.Icon = SD.Icon(str(ICON_PATH))
            ni.Text = "Synthia AI · Command Bridge"
            ni.Visible = True

            menu = WF.ContextMenuStrip()

            item_open = WF.ToolStripMenuItem("💠 Open Synthia")
            item_open.Click += lambda s, e: threading.Thread(target=self.show_window, daemon=True).start()
            menu.Items.Add(item_open)

            item_stop = WF.ToolStripMenuItem("⛔ Stop Active Task (Ctrl+Shift+X)")

            def _do_stop(s, e):
                from . import server as srv
                if srv.MAIN_LOOP:
                    srv.MAIN_LOOP.call_soon_threadsafe(srv.kill_switch)

            item_stop.Click += _do_stop
            menu.Items.Add(item_stop)

            menu.Items.Add(WF.ToolStripSeparator())

            item_startup = WF.ToolStripMenuItem("🚀 Start with Windows")
            item_startup.Checked = is_startup_enabled()

            def _toggle_startup(s, e):
                item_startup.Checked = set_startup(not item_startup.Checked)

            item_startup.Click += _toggle_startup
            menu.Items.Add(item_startup)

            item_pin = WF.ToolStripMenuItem("📌 Create Desktop & Start Menu Icons")
            item_pin.Click += lambda s, e: install_shortcuts(desktop=True, start_menu=True)
            menu.Items.Add(item_pin)

            menu.Items.Add(WF.ToolStripSeparator())

            item_exit = WF.ToolStripMenuItem("✖ Exit Synthia")

            def _do_exit(s, e):
                threading.Thread(target=self.quit_app, daemon=True).start()
                WF.Application.ExitThread()

            item_exit.Click += _do_exit
            menu.Items.Add(item_exit)

            ni.ContextMenuStrip = menu
            ni.DoubleClick += lambda s, e: threading.Thread(target=self.show_window, daemon=True).start()
            self._notify_icon = ni

            WF.Application.Run()
        except Exception as e:  # noqa: BLE001
            print(f"[tray] System tray চালু করা যায়নি: {e}")


shell = DesktopShell()
