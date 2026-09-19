@echo off
REM ---------------------------------------------------------------------------
REM  C2B - the window, with a console behind it.
REM
REM  C2B.bat starts C2B with pythonw.exe, which has no console, so anything the
REM  tool prints goes nowhere. Use this one when a window will not open or does
REM  not look right: everything C2B says appears in the black window behind it,
REM  and stays there when C2B closes.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo C2B is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
echo Checking the installation...
".venv\Scripts\python.exe" -m c2b.cli doctor --no-selftest
echo.
echo Starting C2B. Close the window to come back here.
echo.
".venv\Scripts\python.exe" -m c2b.gui %1
echo.
echo C2B closed. Anything above is worth sending to whoever maintains it.
pause
