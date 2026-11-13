@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1

rem যদি পোর্ট ৮৭৬৫ কোনো কারণে অচল প্রসেস আটকে রাখে, তবে তা মুক্ত করো
powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue; if ($conn) { foreach ($c in $conn) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } }" 2>nul

if exist "Synthia.exe" (
  start "" "Synthia.exe" %*
  exit /b 0
)

start "" ".venv\Scripts\pythonw.exe" -m synthia.main %*
