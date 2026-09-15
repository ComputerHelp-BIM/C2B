@echo off
REM ---------------------------------------------------------------------------
REM  C2B - process one client drawing.
REM  Drag a DXF (or DWG) onto this file, or double-click and type the path.
REM  Everything is written to an "out\<drawing name>" folder next to the drawing.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\activate.bat" (
  echo C2B is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat

set "DRAWING=%~1"
if "%DRAWING%"=="" set /p DRAWING=Path to the client drawing (DXF or DWG): 
if "%DRAWING%"=="" (
  echo No drawing given.
  pause
  exit /b 1
)

REM Optional: put your template DXF at templates\CH-TEMPLATE.dxf and it is used automatically.
set "SEED="
if exist "templates\CH-TEMPLATE.dxf" set "SEED=--seed templates\CH-TEMPLATE.dxf"

c2b run "%DRAWING%" %SEED% %2 %3 %4 %5
echo.
pause
