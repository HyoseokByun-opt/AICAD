@echo off
REM ===================================================================
REM  Offline install - no internet, no administrator rights, no conda.
REM
REM    1. unpacks the Python runtime in runtime\ into python\ next to this
REM       file (the official python.org package; nothing is registered in
REM       Windows and nothing outside this folder changes)
REM    2. installs the packages in wheels\ into it (CadQuery, OpenCASCADE,
REM       Flask, PDFium, OpenCV, ...)
REM    3. checks every import and runs the short self-test
REM
REM  Deleting the python\ folder undoes everything this script did.
REM  Pure ASCII on purpose: cmd.exe reads .bat files in the ANSI code page.
REM ===================================================================
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo ==================================================================
echo   AICAD (AI-assisted CAD Modelling) - offline install
echo ==================================================================
echo.

set "HERE=%~dp0"
if not "%HERE:~80,1%"=="" (
    echo   This folder has a long path:
    echo       %HERE%
    echo   Windows limits a path to 260 characters. If the installation stops
    echo   with "file name too long", move the folder to a short path such as
    echo   C:\AICAD and run this again.
    echo.
)

if exist "python\python.exe" (
    echo   A python\ folder already exists here; it will be reused.
    echo   To rebuild it, delete the python folder and run this file again.
    goto :install
)

set "RT="
for %%F in ("runtime\python-3.11*-embed-amd64.zip") do set "RT=%%~fF"
if not defined RT (
    echo   runtime\python-3.11.x-embed-amd64.zip is missing.
    echo   Copy the complete AICAD folder from the release package.
    pause
    exit /b 1
)
echo   Unpacking %RT% ...
mkdir python
tar -xf "%RT%" -C python
if not exist "python\python.exe" (
    echo   The runtime could not be unpacked. Check that you may write here.
    pause
    exit /b 1
)
REM The path file of the runtime replaces the usual search path: it must
REM name the standard library, the packages and the program itself.
> "python\python311._pth" (
    echo python311.zip
    echo .
    echo Lib\site-packages
    echo ..\app
    echo import site
)
echo   Installing pip from wheels\ ...
set "PIPWHL="
for %%F in ("wheels\pip-*.whl") do set "PIPWHL=%%~fF"
mkdir "python\Lib\site-packages" 2>nul
tar -xf "%PIPWHL%" -C "python\Lib\site-packages"
"python\python.exe" -m pip --version
if errorlevel 1 (
    echo   pip could not be installed.
    pause
    exit /b 1
)

:install
echo.
echo   Installing the packages from wheels\ - nothing is downloaded ...
"python\python.exe" -m pip install --no-index --find-links "%~dp0wheels" --disable-pip-version-check --no-warn-script-location --constraint "%~dp0constraints-offline.txt" -r "%~dp0requirements-offline.txt"
if errorlevel 1 (
    echo.
    echo   The installation failed; the message above names the package.
    pause
    exit /b 1
)

echo.
echo   Checking that every part can be imported ...
"python\python.exe" "%~dp0tools\check_imports.py"
if errorlevel 1 (
    echo.
    echo   Something is still missing - the report above says what.
    pause
    exit /b 1
)

echo.
echo   Running the short self-test ...
"python\python.exe" "%~dp0app\selftest.py" --quick
echo.
echo ==================================================================
echo   Done. Start the program with 2_RUN_AICAD.bat.
echo   The AI model is not part of this package: put it into models\
echo   (3_GET_AI_MODEL.bat downloads it on a PC with internet).
echo ==================================================================
pause
exit /b 0
