@echo off
REM  Starts AICAD for this PC and opens it in the browser.
REM  Leave this window open while working; closing it ends the program
REM  and the AI engine.
call "%~dp0_common.bat" || (pause & exit /b 1)
echo ==================================================================
echo   AICAD - http://127.0.0.1:8100   (leave this window open)
echo ==================================================================
%APY% "%~dp0app\run_web.py" --host 127.0.0.1 --port 8100 --open
pause
