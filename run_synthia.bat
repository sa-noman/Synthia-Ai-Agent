@echo off
cd /d "%~dp0"
if exist "Synthia.exe" (
  start "" "Synthia.exe" %*
  exit /b 0
)
chcp 65001 >nul
set PYTHONUTF8=1
".venv\Scripts\pythonw.exe" -m synthia.main %*
