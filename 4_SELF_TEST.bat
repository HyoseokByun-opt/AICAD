@echo off
REM  Full self-test: kernel, STEP round trip, drawing import, dimension
REM  resolver, the example references, the AI engine files and the GPU.
REM  Add --ai to also load the AI model and ask it one question.
call "%~dp0_common.bat" || (pause & exit /b 1)
%APY% "%~dp0app\selftest.py" %*
pause
