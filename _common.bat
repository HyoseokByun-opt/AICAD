@echo off
REM ===================================================================
REM  Sets APY = the Python that runs AICAD.
REM  The offline installation (1_INSTALL_OFFLINE.bat) puts it in python\
REM  next to this file; nothing outside this folder is used or changed.
REM  Pure ASCII on purpose: cmd.exe reads .bat files in the ANSI code page.
REM ===================================================================
set "AICAD_ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%AICAD_ROOT%python\python.exe" (
    set "APY="%AICAD_ROOT%python\python.exe""
    exit /b 0
)
echo.
echo   AICAD is not installed yet. Run 1_INSTALL_OFFLINE.bat first.
exit /b 1
