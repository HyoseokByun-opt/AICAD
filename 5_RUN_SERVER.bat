@echo off
REM  Starts AICAD for the local network: other PCs open http://<this PC>:8100
REM  The AI runs on this PC's GPU; Windows may ask to allow the port once.
call "%~dp0_common.bat" || (pause & exit /b 1)
echo ==================================================================
echo   AICAD on the local network, port 8100   (leave this window open)
echo ==================================================================
ipconfig | findstr /R /C:"IPv4"
%APY% "%~dp0app\run_web.py" --host 0.0.0.0 --port 8100
pause
