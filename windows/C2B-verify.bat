@echo off
REM ---------------------------------------------------------------------------
REM  C2B - re-check a template DXF after a drafter has edited it.
REM  Drag the <name>.template.dxf onto this file.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\activate.bat" (
  echo C2B is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat

set "TEMPLATE=%~1"
if "%TEMPLATE%"=="" set /p TEMPLATE=Path to the template DXF: 
c2b verify "%TEMPLATE%"
echo.
pause
