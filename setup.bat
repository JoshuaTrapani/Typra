@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM -- Find 64-bit Python 3.11 -----------------------------------------------
REM python.org default locations first, then the py launcher.
SET "PYEXE="
IF EXIST "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" SET "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
IF NOT DEFINED PYEXE IF EXIST "%ProgramW6432%\Python311\python.exe" SET "PYEXE=%ProgramW6432%\Python311\python.exe"
IF DEFINED PYEXE GOTO :check_python
py -3.11 -c "import sys" >NUL 2>&1
IF ERRORLEVEL 1 GOTO :no_python
FOR /F "delims=" %%i IN ('py -3.11 -c "import sys; print(sys.executable)"') DO SET "PYEXE=%%i"

:check_python
REM Microsoft Store builds are not supported (sandboxed app, install folder replaced on every update)
ECHO "%PYEXE%" | FIND /I "\WindowsApps\" >NUL && GOTO :store_python
"%PYEXE%" -c "import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" >NUL 2>&1
IF ERRORLEVEL 1 GOTO :no_python
ECHO Using Python: %PYEXE%

REM -- Create (or repair) the virtual environment -----------------------------
IF EXIST ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -I -c "import pip, sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" >NUL 2>&1
    IF ERRORLEVEL 1 (
        ECHO The existing .venv does not work: recreating it...
        RMDIR /S /Q .venv
    )
)
IF NOT EXIST ".venv\Scripts\python.exe" (
    ECHO Creating virtual environment...
    "%PYEXE%" -I -m venv .venv
    IF ERRORLEVEL 1 ( ECHO ERROR: venv creation failed. & EXIT /B 1 )
)

REM -- Install dependencies: exact versions, SHA-256 verified, wheels only ---
REM truststore = use the Windows certificate store, so pip also works behind
REM antivirus or corporate HTTPS inspection
ECHO Installing dependencies...
".venv\Scripts\python.exe" -I -m pip install --use-feature=truststore --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r requirements.lock
IF NOT ERRORLEVEL 1 GOTO :done
REM pip before 22.2 does not know the feature, and pip before 24.0 needs
REM truststore installed separately: retry with pip's own certificates
".venv\Scripts\python.exe" -I -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r requirements.lock
IF ERRORLEVEL 1 ( ECHO ERROR: pip install failed. & EXIT /B 1 )

:done
REM run.bat compares this copy with requirements.lock to apply future updates
COPY /Y requirements.lock .venv\typra-requirements.lock >NUL
ECHO Setup complete.
EXIT /B 0

:store_python
ECHO ERROR: only the Microsoft Store build of Python 3.11 was found, which is not supported.
:no_python
ECHO ERROR: 64-bit Python 3.11 not found.
ECHO Install "Windows installer (64-bit)" from https://www.python.org/downloads/release/python-3119/
ECHO and run this script again.
EXIT /B 1
