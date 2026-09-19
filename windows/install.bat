@echo off
REM ---------------------------------------------------------------------------
REM  C2B - one-time installation on a Windows machine.
REM  Double-click this file. It creates a private Python environment next to the
REM  repository, installs C2B into it, and checks that everything works.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo During setup tick "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

echo Creating the C2B environment in .venv ...
py -3 -m venv .venv || goto :failed
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo Installing C2B and its dependencies ...
pip install -e ".[dev,render]" --quiet || goto :failed
REM pythonnet is a dependency on Windows, so the branded window comes with it. If it is
REM missing the tool still runs, in the plain window, and doctor says so below.
python -c "import clr" >nul 2>nul || echo   note: the branded window is unavailable - see the check below

echo.
echo Checking the installation ...
c2b doctor
echo.
echo Installation finished. Use C2B-run.bat to process a drawing,
echo or open a command prompt here and run:  .venv\Scripts\activate  then  c2b --help
echo.
pause
exit /b 0

:failed
echo.
echo Installation failed. Send the messages above to whoever maintains C2B.
pause
exit /b 1
