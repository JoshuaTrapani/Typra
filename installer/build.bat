@echo off
setlocal EnableExtensions
REM Builds installer\Typra_Setup_<version>.exe with NSIS 3 (https://nsis.sourceforge.io)
REM Usage: installer\build.bat [version]

SET "MAKENSIS="
REM The NSIS installer records its folder in the registry (any drive)
FOR %%K IN ("HKLM\SOFTWARE\WOW6432Node\NSIS" "HKLM\SOFTWARE\NSIS" "HKCU\SOFTWARE\NSIS") DO (
    IF NOT DEFINED MAKENSIS FOR /F "skip=2 tokens=2,*" %%A IN ('REG QUERY %%K /ve 2^>NUL') DO (
        IF EXIST "%%B\makensis.exe" SET "MAKENSIS=%%B\makensis.exe"
    )
)
FOR %%P IN ("%ProgramFiles(x86)%\NSIS\makensis.exe" "%ProgramFiles%\NSIS\makensis.exe") DO (
    IF NOT DEFINED MAKENSIS IF EXIST "%%~P" SET "MAKENSIS=%%~P"
)
IF NOT DEFINED MAKENSIS (
    WHERE makensis >NUL 2>&1 && SET "MAKENSIS=makensis"
)
IF NOT DEFINED MAKENSIS (
    ECHO NSIS 3 not found. Install it from https://nsis.sourceforge.io/Download
    EXIT /B 1
)

SET "VERSION_ARG="
IF NOT "%~1"=="" SET "VERSION_ARG=/DVERSION=%~1"
"%MAKENSIS%" /V3 %VERSION_ARG% "%~dp0typra.nsi"
IF ERRORLEVEL 1 EXIT /B 1

REM Publish this checksum next to the release asset
FOR %%F IN ("%~dp0Typra_Setup_*.exe") DO certutil -hashfile "%%~F" SHA256
