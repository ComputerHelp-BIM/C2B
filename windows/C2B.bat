@echo off
REM ---------------------------------------------------------------------------
REM  C2B - the window. Double-click this file.
REM  You can also drag a client drawing onto it to start with that drawing.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo C2B is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m c2b.gui %1
