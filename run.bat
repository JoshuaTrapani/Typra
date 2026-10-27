@echo off
cd /d "%~dp0"

REM -- Set up on first run, after requirements.lock changed, or if broken -----
FC /B requirements.lock .venv\typra-requirements.lock >NUL 2>&1
IF ERRORLEVEL 1 GOTO :setup
".venv\Scripts\python.exe" -I -c "import PyQt6, faster_whisper, sounddevice, pynput" >NUL 2>&1
IF NOT ERRORLEVEL 1 GOTO :launch
:setup
CALL "%~dp0setup.bat"
IF ERRORLEVEL 1 ( PAUSE & EXIT /B 1 )

:launch
REM -- Launch without a console window ---------------------------------------
REM A second instance exits by itself (single-instance guard in main.py).
REM -E: ignore PYTHONPATH/PYTHONHOME set for other Python programs
START "" ".venv\Scripts\pythonw.exe" -E "%~dp0main.py"
