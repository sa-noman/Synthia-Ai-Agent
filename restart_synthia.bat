@echo off
cd /d "%~dp0"
title Synthia - Clean Restart
echo [Synthia] Cleaning any lingering background processes...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765,8766 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
del /f /q "synthia_data\runtime.json" 2>nul
echo [Synthia] Starting clean Synthia instance...
if exist "Synthia.exe" (
  start "" "Synthia.exe"
) else (
  start "" ".venv\Scripts\pythonw.exe" -m synthia.main
)
echo [Synthia] Done!
