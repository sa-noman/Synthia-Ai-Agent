"""Synthia App Builder — কাস্টম আইকন (synthia.ico) ও নেটিভ Windows সফটওয়্যার লঞ্চার (Synthia.exe) তৈরি করে।"""
from __future__ import annotations

import math
import struct
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "synthia" / "assets"
ICON_PATH = ASSETS / "synthia.ico"
CS_PATH = ROOT / "scripts" / "launcher.cs"
EXE_PATH = ROOT / "Synthia.exe"


def _png_bytes(size: int) -> bytes:
    """গ্লোয়িং নিয়ন টিল-ভায়োলেট সাই-ফাই অরব আইকন (RGBA PNG) তৈরি করে।"""
    rows = bytearray()
    cx = cy = (size - 1) / 2.0
    half = size / 2.0

    for y in range(size):
        rows.append(0)  # PNG filter byte: None
        ny = (y - cy) / half  # -1..1
        for x in range(size):
            nx = (x - cx) / half  # -1..1
            # Rounded squircle mask: |x|^4.5 + |y|^4.5 <= 0.94^4.5
            squircle = (abs(nx) ** 4.5 + abs(ny) ** 4.5) ** (1 / 4.5)
            if squircle > 0.96:
                rows.extend((0, 0, 0, 0))
                continue

            # Anti-aliased edge
            edge_alpha = min(1.0, max(0.0, (0.96 - squircle) * (size * 0.45)))

            # Dark space background (#050d14 -> #091a24)
            d = math.hypot(nx, ny)
            r = 6 + max(0.0, (1.0 - d)) * 10
            g = 14 + max(0.0, (1.0 - d)) * 26
            b = 22 + max(0.0, (1.0 - d)) * 34

            # Subtle squircle border glow
            if 0.87 < squircle <= 0.96:
                bd = 1.0 - abs(squircle - 0.915) / 0.045
                r += 35 * bd
                g += 195 * bd
                b += 180 * bd

            # Outer orbital ring 1 (tilted ellipse)
            rx1 = nx * 0.92 + ny * 0.38
            ry1 = (-nx * 0.38 + ny * 0.92) * 2.35
            ring1 = abs(math.hypot(rx1, ry1) - 0.66)
            if ring1 < 0.055:
                w = (1.0 - ring1 / 0.055) ** 1.6
                r += 46 * w * 0.85
                g += 242 * w * 0.85
                b += 208 * w * 0.85

            # Outer orbital ring 2 (violet counter-tilt)
            rx2 = nx * 0.85 - ny * 0.52
            ry2 = (nx * 0.52 + ny * 0.85) * 2.5
            ring2 = abs(math.hypot(rx2, ry2) - 0.58)
            if ring2 < 0.05:
                w = (1.0 - ring2 / 0.05) ** 1.6
                r += 167 * w * 0.75
                g += 139 * w * 0.75
                b += 250 * w * 0.75

            # Central glowing Synthia orb
            if d < 0.62:
                glow = (1.0 - d / 0.62) ** 2.1
                r += 38 * glow
                g += 235 * glow
                b += 205 * glow
            if d < 0.28:
                core = (1.0 - d / 0.28) ** 1.7
                r += 220 * core
                g += 255 * core
                b += 255 * core

            rows.extend((
                min(255, int(r)),
                min(255, int(g)),
                min(255, int(b)),
                min(255, int(edge_alpha * 255)),
            ))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def build_ico() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [256, 64, 48, 32, 16]
    blobs = [_png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for s, blob in zip(sizes, blobs):
        wh = 0 if s == 256 else s
        entries.extend(struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(blob), offset))
        offset += len(blob)
    ICON_PATH.write_bytes(header + bytes(entries) + b"".join(blobs))
    print(f"[build] Icon generated: {ICON_PATH} ({ICON_PATH.stat().st_size:,} bytes)")


LAUNCHER_CS = r"""using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: AssemblyTitle("Synthia AI")]
[assembly: AssemblyDescription("Synthia · Personal Local AI Command Bridge")]
[assembly: AssemblyProduct("Synthia AI")]
[assembly: AssemblyVersion("0.1.0.0")]

static class Program
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string AppID);

    [STAThread]
    static int Main(string[] args)
    {
        try { SetCurrentProcessExplicitAppUserModelID("Synthia.CommandBridge.App"); } catch { }

        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtimeJson = Path.Combine(root, "synthia_data", "runtime.json");

        // যদি Synthia আগে থেকেই ব্যাকগ্রাউন্ডে (System Tray) চালু থাকে, তাহলে উইন্ডোটি সামনে নিয়ে আসো
        if (File.Exists(runtimeJson) && args.Length == 0)
        {
            try
            {
                string json = File.ReadAllText(runtimeJson, Encoding.UTF8);
                Match pm = Regex.Match(json, "\"port\"\\s*:\\s*(\\d+)");
                Match tm = Regex.Match(json, "\"token\"\\s*:\\s*\"([^\"]+)\"");
                if (pm.Success && tm.Success)
                {
                    string url = "http://127.0.0.1:" + pm.Groups[1].Value + "/api/show?token=" + Uri.EscapeDataString(tm.Groups[1].Value);
                    HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                    req.Method = "POST";
                    req.ContentLength = 0;
                    req.Timeout = 1500;
                    using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                    {
                        if ((int)resp.StatusCode == 200)
                            return 0;
                    }
                }
            }
            catch
            {
                // পুরনো runtime.json বা সার্ভার বন্ধ — নিচে নতুন করে চালু হবে
            }
        }

        string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show(
                "Synthia চালু করার জন্য .venv\\Scripts\\pythonw.exe পাওয়া যায়নি।\nঅনুগ্রহ করে সেটআপ চেক করুন।",
                "Synthia AI",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }

        StringBuilder argStr = new StringBuilder("-m synthia.main");
        foreach (string a in args)
        {
            argStr.Append(" \"");
            argStr.Append(a.Replace("\"", "\\\""));
            argStr.Append("\"");
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = pythonw;
        psi.Arguments = argStr.ToString();
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";

        Process.Start(psi);
        return 0;
    }
}
"""


def build_exe() -> None:
    CS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CS_PATH.write_text(LAUNCHER_CS, encoding="utf-8")
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.exists():
        raise FileNotFoundError(f"csc.exe not found at {csc}")
    cmd = [
        str(csc),
        "/nologo",
        "/optimize+",
        "/target:winexe",
        f"/out:{EXE_PATH}",
        f"/win32icon:{ICON_PATH}",
        "/r:System.dll",
        "/r:System.Windows.Forms.dll",
        str(CS_PATH),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"csc failed:\n{r.stdout}\n{r.stderr}")
    print(f"[build] Native Windows App compiled: {EXE_PATH} ({EXE_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build_ico()
    build_exe()
