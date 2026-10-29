@echo off
REM ===================================================================
REM  Downloads an AI model from Hugging Face into models\ (internet needed).
REM
REM  Run it on any PC with internet, then copy the whole AICAD folder (or
REM  only models\) to the offline PC. Downloads resume after an
REM  interruption and every file is checked against its SHA-256 digest.
REM
REM    3_GET_AI_MODEL.bat                 menu
REM    3_GET_AI_MODEL.bat qwen3.6-27b-q4  one profile directly
REM  Pure ASCII on purpose: cmd.exe reads .bat files in the ANSI code page.
REM ===================================================================
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "GPY=python\python.exe"
if exist "%GPY%" goto :ready
REM not installed here: a bare runtime in tools\pyrt is enough (standard library only)
set "GPY=tools\pyrt\python.exe"
if exist "%GPY%" goto :ready
set "RT="
for %%F in ("runtime\python-3.11*-embed-amd64.zip") do set "RT=%%~fF"
if not defined RT goto :nort
echo   Unpacking a Python runtime for the download ...
mkdir "tools\pyrt" 2>nul
tar -xf "%RT%" -C "tools\pyrt"
if not exist "%GPY%" goto :nort

:ready
if not "%~1"=="" goto :direct
echo ==================================================================
echo   AICAD - AI model download (Hugging Face)
echo ==================================================================
echo.
echo   1  RTX 4090 / 24 GB GPU      Qwen3.6-27B Q4_K_M    17.7 GB
echo   2  RTX 6000 Ada / 48 GB GPU  Qwen3.6-27B Q6_K      23.5 GB
echo   3  both of the above                               41.2 GB
echo   4  fast MoE for 48 GB        Qwen3.6-35B-A3B Q4    23.0 GB
echo   5  8-16 GB GPU or CPU        Qwen3.5-9B Q4_K_M      6.6 GB
echo   6  CPU trial                 Qwen3.5-4B Q4_K_M      3.4 GB
echo   7  automatic for the GPU of THIS PC
echo.
set "CH="
set /p CH="  Choose 1-7: "
set "PROF="
if "%CH%"=="1" set "PROF=qwen3.6-27b-q4"
if "%CH%"=="2" set "PROF=qwen3.6-27b-q6"
if "%CH%"=="3" set "PROF=qwen3.6-27b-q4 qwen3.6-27b-q6"
if "%CH%"=="4" set "PROF=qwen3.6-35b-a3b-q4"
if "%CH%"=="5" set "PROF=qwen3.5-9b-q4"
if "%CH%"=="6" set "PROF=qwen3.5-4b"
if "%CH%"=="7" set "PROF=auto"
if not defined PROF goto :nochoice
"%GPY%" "%~dp0tools\get_model.py" %PROF%
pause
exit /b 0

:direct
"%GPY%" "%~dp0tools\get_model.py" %*
pause
exit /b 0

:nochoice
echo   No valid choice.
pause
exit /b 1

:nort
echo   runtime\python-3.11.x-embed-amd64.zip is missing or cannot be unpacked.
pause
exit /b 1
